import os
import dotenv
import logging
import requests
from flask import g
from tests import utils
from .conftest_types import ClientAuthenticationMethod
from urllib.parse import urlparse
from flask_login import login_user, logout_user
import lifemonitor.db as lm_db
from lifemonitor.app import create_app, initialize_app
from lifemonitor.auth.services import generate_new_api_key
from lifemonitor.auth.models import User
from lifemonitor.api.models import WorkflowRegistry

# set the module level logger
logger = logging.getLogger(__name__)


def get_headers(extra_data=None):
    data = {"Content-type": "application/vnd.api+json",
            "Accept": "application/vnd.api+json",
            "Accept-Charset": "ISO-8859-1"}
    if extra_data:
        data.update(extra_data)
    return data


def load_settings(filename):
    logger.debug("Loading settings file: %r", filename)
    if os.path.exists(filename):
        return dotenv.dotenv_values(dotenv_path=filename)
    return {}


def get_admin_user():
    admin = User.find_by_username("admin")
    if admin is None:
        admin = User("admin")
        admin.password = "admin"
        admin.id = 1
        lm_db.db.session.add(admin)
        lm_db.db.session.commit()
    return admin


def init_db():
    admin = get_admin_user()
    create_client_credentials_registry(admin)


def clean_db():
    lm_db.db.session.rollback()
    for table in reversed(lm_db.db.metadata.sorted_tables):
        lm_db.db.session.execute(table.delete())
    lm_db.db.session.commit()


def process_auto_login():
    enabled = "auto_login" in g and g["auto_login"] is True
    logger.info("AutoLogin enabled: %r", enabled)
    if enabled:
        if "user" in g:
            logger.info("Login user: %r", g.user)
            login_user(g.user)


def enable_auto_login():
    g["auto_login"] = True


def disable_auto_login():
    g["auto_login"] = False


def app_context(request_settings,
                init_db=True, clean_db=True, drop_db=False):
    try:
        os.environ.pop("FLASK_APP_CONFIG_FILE", None)
        conn_param = lm_db.db_connection_params(request_settings)
        if init_db:
            lm_db.create_db(conn_params=conn_param)
            logger.debug("DB created (conn params=%r)", conn_param)
        flask_app = create_app(env="testing", settings=request_settings, init_app=False)
        flask_app.before_request(process_auto_login)
        with flask_app.app_context() as ctx:
            logger.info("Starting application")
            initialize_app(flask_app, ctx)
            if init_db:
                logger.debug("Initializing DB...")
                lm_db.db.create_all()
                logger.debug("DB initialized!")
            yield ctx
        # clean the database and
        # close all sessions and connections
        with flask_app.app_context() as ctx:
            if clean_db:
                # _clean_db()
                logger.debug("DB cleanup")
            if drop_db:
                lm_db.db.close_all_sessions()
                lm_db.db.engine.pool.dispose()
                lm_db.drop_db(conn_param)
                logger.debug("DB deleted (connection params=%r)", conn_param)
    except Exception as e:
        logger.exception(e)
        raise RuntimeError(e)


def get_user_workflows(_application, _registry_type, _public=True, _to_skip=None, index_user=0):
    """ Parametric fixture: available params are {wfhub}"""
    try:
        wf_loader = globals()[f"{_registry_type.value}_workflow".lower()]
        return wf_loader(_application, _registry_type, _public, _to_skip, index_user)
    except KeyError as e:
        logger.exception(e)
        raise RuntimeError("Authorization provider {} is not supported".format(_registry_type))
    except AttributeError as e:
        logger.exception(e)
        raise RuntimeError("Parametrized fixture. "
                           "You need to pass a provider type as request param")


def seek_workflow(application, provider, public, to_skip=None, index_user=0):
    # This function assumes that at least one workflow is already loaded on WfHub
    # and accessible through the API Key user
    with requests.session() as s:
        wfhub_url = application.config["SEEK_API_BASE_URL"]
        wfhub_workflows_url = os.path.join(wfhub_url, 'workflows')
        if index_user > 0:
            api_key = application.config["API_KEYS"][f"SEEK_API_KEY_{index_user}"]
        else:
            api_key = application.config["API_KEYS"]["SEEK_API_KEY"]
        headers = get_headers({'Authorization': f'Bearer {api_key}'})
        wr = s.get(wfhub_workflows_url, headers=headers)
        if wr.status_code != 200:
            raise RuntimeError(f"ERROR {wr.status_code}: Unable to get workflows")
        # pick the first and details
        workflows = wr.json()["data"]
        logger.debug("Seek workflows: %r", workflows)
        workflow = None
        result = []
        for w in workflows:
            try:
                wf_id = w['id']
                if to_skip and wf_id in to_skip:
                    continue
                wf_r = s.get(f"{wfhub_workflows_url}/{wf_id}", headers=headers)
                if wf_r.status_code == 200:
                    workflow = wf_r.json()["data"]
                    logger.debug("The workflow: %r", workflow)
                    policy = workflow['attributes'].get('policy', None)
                    is_public = policy and policy.get("access", None) != 'no_access'
                    result.append({
                        'public': is_public,
                        'external_id': workflow['id'],
                        'uuid': workflow['meta']['uuid'],
                        'version': str(workflow["attributes"]["versions"][0]['version']),  # pick the first version
                        'name': workflow["attributes"]["title"],
                        'roc_link': f'{workflow["attributes"]["content_blobs"][0]["link"]}/download',
                        'registry_uri': application.config["SEEK_API_BASE_URL"]
                    })
            except Exception as e:
                logger.exception(e)
        if len(result) == 0:
            raise RuntimeError("Unable to get workflow details")
        return result


def seek_user_session(application, index=None):
    with requests.session() as session:
        wfhub_url = application.config["SEEK_API_BASE_URL"]
        wfhub_people_details = os.path.join(wfhub_url, 'people/current')
        logger.debug("URL: %s", wfhub_people_details)
        api_key = application.config["API_KEYS"]["SEEK_API_KEY" if not index else f"SEEK_API_KEY_{index}"]
        headers = get_headers({'Authorization': f'Bearer {api_key}'})
        user_info_r = session.get(wfhub_people_details, headers=headers)
        assert user_info_r.status_code == 200, "Unable to get user info from Workflow Hub: code {}" \
            .format(user_info_r.status_code)
        wfhub_user_info = user_info_r.json()['data']
        logger.debug("WfHub user info: %r", wfhub_user_info)
        application.config.pop("SEEK_API_KEY", None)
        login_r = session.get(f"{application.config.get('BASE_URL')}/oauth2/login/seek")
        assert login_r.status_code == 200, "Login Error: status code {} !!!".format(login_r.status_code)
        return User.find_by_username(wfhub_user_info['id']), session, wfhub_user_info


def get_user_session(application, provider, index=None):
    """ Parametric fixture: available params are {seek}"""
    try:
        user_loader = globals()[f"{provider.value}_user_session".lower()]
        user, session, user_info = user_loader(application, index)
        assert user is not None, "Invalid USER NONE"
        logger.debug("USER: %r", user)
        logger.debug("USER SESSION: %r", session)
        return user, session, user_info
    except KeyError as e:
        logger.exception(e)
        raise RuntimeError("Authorization provider {} is not supported".format(provider))
    except AttributeError as e:
        logger.exception(e)
        raise RuntimeError("Parametrized fixture. "
                           "You need to pass a provider type as request param")


def user(_app_context, _provider_type, _user_index=1, _register_workflows=False):
    try:
        user, session, user_info = get_user_session(_app_context.app,
                                                    _provider_type, index=_user_index)
        # load a workflow set
        workflows = get_user_workflows(_app_context.app, _provider_type,
                                       _public=False, index_user=_user_index)
        # user object
        user_obj = {
            "user": user,
            "user_info": user_info,
            "session": session,
            "workflows": workflows
        }
        if _register_workflows:
            utils.register_workflows(user_obj)
        yield user_obj
        if user and not user.is_anonymous:
            try:
                logout_user()
            except Exception:
                pass
    except KeyError as e:
        logger.exception(e)
        raise RuntimeError(f"Authorization provider {_provider_type} is not supported")
    except AttributeError as e:
        logger.exception(e)
        raise RuntimeError("Parametrized fixture. "
                           "You need to pass a provider type as request param")


def _fake_callback_uri():
    return "http://fake_client_uri"


def create_authorization_code_flow_client(_admin_user):
    # FIXME: replace with service; do not DB directly
    from lifemonitor.auth.oauth2.server import server
    client = server.create_client(_admin_user,
                                  "test_code_flow", _fake_callback_uri(),
                                  ['authorization_code', 'token', 'id_token'],
                                  ["code", "token"], "read write",
                                  _fake_callback_uri(), "client_secret_post")
    print("CLIENT ID: %s" % client.client_id)
    print("CLIENT SECRET: %s" % client.client_secret)
    logger.debug("Registered client: %r", client)
    return client
    # client.delete()


def create_authorization_code_access_token(_application,
                                           _authorization_code_flow_client,
                                           _user=None, _session=None):
    """ Parametric fixture: available params are {seek}"""
    try:
        client = _authorization_code_flow_client
        application = _application
        logger.debug(_user)
        logger.debug(_session)
        user, session = _user, _session
        g.user = None  # store the user on g to allow the auto login; None to avoid the login
        client_id = client.client_id
        client_secret = client.client_info["client_secret"]
        authorization_url = f"{application.config['BASE_URL']}/oauth/authorize"
        token_url = f"{application.config['BASE_URL']}/oauth/token"
        # base_url = application.config[f"{registry_type}_API_BASE_URL".upper()]

        session.auth = None
        auth_response = session.post(authorization_url, params={
            "client_id": client_id,
            "grant_type": "authorization_code",
            "response_type": "code",
            "confirm": "true",
            "state": "5ca75bd30",
            "redirect_uri": _fake_callback_uri(),
            "scope": "read write"
        }, data={"client_secret": client_secret}, allow_redirects=False)
        assert auth_response.status_code == 302, "No redirection with auth code"
        # get the auth code from response header
        location = urlparse(auth_response.headers.get("Location"))
        query_params = location.query.split('&')
        code = query_params[0].replace("code=", "")
        logger.debug("Authorization code: %r", code)

        # remove auth basic
        session.auth = None
        session.headers.update({"Content-type": "application/x-www-form-urlencoded"})
        token_response = session.post(token_url, data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _fake_callback_uri(),
            "client_id": client_id,
            "client_secret": client_secret
        })
        assert token_response.status_code == 200, f"Invalid token response: {token_response.description}"
        logger.debug("TOKEN response: %r" % token_response)
        token = token_response.json()
        token["user"] = user
        return token
    except AttributeError as e:
        logger.exception(e)
        raise RuntimeError("Parametrized fixture. "
                           "You need to pass a provider type as request param")


def create_client_credentials_access_token(application, credentials):
    token_url = f"{application.config.get('BASE_URL')}/oauth/token"
    response = requests.post(token_url, data={
        'grant_type': 'client_credentials',
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scope': 'read write'
    })
    logger.debug("TOKEN RESPONSE: %r", response.content)
    assert response.status_code == 200, "Error"
    return response.json()


def create_app_client_headers(_client_auth_method, _application,
                              _client_credentials_registry,
                              _app_user, _app_user_session=None):
    registry = _client_credentials_registry
    access_token = api_key = None
    if _client_auth_method == ClientAuthenticationMethod.AUTHORIZATION_CODE:
        _client = create_authorization_code_flow_client(_app_user)
        access_token = create_authorization_code_access_token(
            _application, _client,
            _user=_app_user, _session=_app_user_session)["access_token"]
    elif _client_auth_method == ClientAuthenticationMethod.CLIENT_CREDENTIALS:
        _client = None
        access_token = create_client_credentials_access_token(
            _application, registry.client_credentials)["access_token"]
    elif _client_auth_method == ClientAuthenticationMethod.API_KEY:
        api_key = generate_new_api_key(_app_user, "read write").key
    try:
        headers = None
        if access_token:
            headers = get_headers({'Authorization': f'Bearer {access_token}'})
        elif api_key:
            headers = get_headers({'ApiKey': f'{api_key}'})
        else:
            headers = get_headers()
        return headers
    except KeyError as e:
        logger.exception(e)
        return get_headers()


def get_user_auth_headers(_auth_method, _application, _registry, _user, _session):
    return create_app_client_headers(_auth_method,
                                     _application, _registry,
                                     _user, _session)


def create_client_credentials_registry(_admin_user):
    # FIXME: replace with service; do not DB directly
    from lifemonitor.auth.oauth2.server import server
    client = server.create_client(_admin_user,
                                  "seek", "https://seek:3000",
                                  'client_credentials', ["token"], "read write",
                                  "", "client_secret_post")
    logger.debug("Registered client: %r", client)
    registry = WorkflowRegistry("seek", client)
    registry.save()
    return registry


def get_registry(_admin_user):
    registry = WorkflowRegistry.find_by_name("seek")
    if registry is None:
        registry = create_client_credentials_registry(_admin_user)
    return registry