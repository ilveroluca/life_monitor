import pytest
import logging
import lifemonitor.auth as auth
import lifemonitor.common as common
import lifemonitor.api.models as models
import lifemonitor.api.controllers as controllers
import lifemonitor.api.serializers as serializers
from lifemonitor.lang import messages
from lifemonitor.auth.models import User
from unittest.mock import MagicMock, patch
from tests.conftest import assert_status_code
from lifemonitor.auth.oauth2.client.models import OAuthIdentityNotFoundException

logger = logging.getLogger(__name__)


@pytest.fixture
def user():
    u = User()
    auth.login_user(u)
    yield u
    auth.logout_user()


@pytest.fixture
def registry():
    r = MagicMock()
    r.name = "WorkflowRegistry"
    auth.login_registry(r)
    yield r
    auth.logout_registry()


@patch("lifemonitor.api.controllers.lm")
def test_get_workflows_no_authorization(m, base_request_context):
    assert auth.current_user.is_anonymous, "Unexpected user in session"
    assert auth.current_registry is not None, "Unexpected registry in session"
    with pytest.raises(auth.NotAuthorizedException):
        controllers.workflows_get()


@patch("lifemonitor.api.controllers.lm")
def test_get_workflows_with_user(m, base_request_context, user):
    # add one user to the current session
    assert not auth.current_user.is_anonymous, "Unexpected user in session"
    assert auth.current_user == user, "Unexpected user in session"
    logger.debug("Current registry: %r", auth.current_registry)
    assert not auth.current_registry, "Unexpected registry in session"
    # add one fake workflow
    data = {"uuid": "123456"}
    m.get_user_workflows.return_value = [data]
    response = controllers.workflows_get()
    m.get_user_workflows.assert_called_once()
    assert isinstance(response, dict), "Unexpected result type"
    assert response == serializers.WorkflowSchema().dump([data], many=True)


@patch("lifemonitor.api.controllers.lm")
def test_get_workflows_with_registry(m, base_request_context, registry):
    assert auth.current_user.is_anonymous, "Unexpected user in session"
    assert auth.current_registry, "Unexpected registry in session"
    # add one fake workflow
    data = {"uuid": "123456"}
    m.get_registry_workflows.return_value = [data]
    response = controllers.workflows_get()
    m.get_registry_workflows.assert_called_once()
    assert isinstance(response, dict), "Unexpected result type"
    assert response == serializers.WorkflowSchema().dump([data], many=True)


@patch("lifemonitor.api.controllers.lm")
def test_post_workflows_no_authorization(m, base_request_context):
    assert auth.current_user.is_anonymous, "Unexpected user in session"
    assert not auth.current_registry, "Unexpected registry in session"
    with pytest.raises(auth.NotAuthorizedException):
        controllers.workflows_post(body={})


@patch("lifemonitor.api.controllers.lm")
def test_post_workflow_by_user_error_no_registry_uri(m, base_request_context, user):
    assert not auth.current_user.is_anonymous, "Unexpected user in session"
    assert auth.current_user == user, "Unexpected user in session"
    assert not auth.current_registry, "Unexpected registry in session"
    response = controllers.workflows_post(body={})
    assert response.status_code == 400, "Expected a Bad Request"
    assert messages.no_registry_uri_provided in response.data.decode(), \
        "Unexpected response message"


@patch("lifemonitor.api.controllers.lm")
def test_post_workflow_by_user_error_invalid_registry_uri(m, base_request_context, user):
    assert not auth.current_user.is_anonymous, "Unexpected user in session"
    assert auth.current_user == user, "Unexpected user in session"
    assert not auth.current_registry, "Unexpected registry in session"
    # add one fake workflow
    data = {"registry_uri": "123456"}
    m.get_workflow_registry_by_uri.side_effect = common.EntityNotFoundException(models.WorkflowRegistry)
    response = controllers.workflows_post(body=data)
    m.get_workflow_registry_by_uri.assert_called_once_with(data["registry_uri"]), \
        "get_workflow_registry_by_uri should be used"
    logger.debug("Response: %r, %r", response, str(response.data))
    assert response.status_code == 404, "Unexpected Workflow registry"


@patch("lifemonitor.api.controllers.lm")
def test_post_workflow_by_user_error_missing_input_data(m, base_request_context, user):
    assert not auth.current_user.is_anonymous, "Unexpected user in session"
    assert auth.current_user == user, "Unexpected user in session"
    assert not auth.current_registry, "Unexpected registry in session"
    # add one fake workflow
    data = {"registry_uri": "123456"}
    m.get_workflow_registry_by_uri.return_value = MagicMock()
    response = controllers.workflows_post(body=data)
    m.get_workflow_registry_by_uri.assert_called_once_with(data["registry_uri"]), \
        "get_workflow_registry_by_uri should be used"
    logger.debug("Response: %r, %r", response, str(response.data))
    assert_status_code(response.status_code, 400)


@patch("lifemonitor.api.controllers.lm")
def test_post_workflow_by_user(m, base_request_context, user):
    assert not auth.current_user.is_anonymous, "Unexpected user in session"
    assert auth.current_user == user, "Unexpected user in session"
    assert not auth.current_registry, "Unexpected registry in session"
    # add one fake workflow
    data = {
        "registry_uri": "123456",
        "uuid": "1212121212121212",
        "version": "1.0",
        "roc_link": "https://registry.org/roc_crate/download"
    }
    m.get_workflow_registry_by_uri.return_value = MagicMock()
    w = MagicMock()
    w.uuid = data['uuid']
    w.version = data['version']
    m.register_workflow.return_value = w
    response = controllers.workflows_post(body=data)
    m.get_workflow_registry_by_uri.assert_called_once_with(data["registry_uri"]), \
        "get_workflow_registry_by_uri should be used"
    assert_status_code(response[1], 201)
    assert response[0]["wf_uuid"] == data['uuid'] and \
        response[0]["wf_version"] == data['version']


@patch("lifemonitor.api.controllers.lm")
def test_post_workflow_by_registry_error_registry_uri(m, base_request_context, registry):
    assert auth.current_user.is_anonymous, "Unexpected user in session"
    assert auth.current_registry, "Unexpected registry in session"
    # add one fake workflow
    data = {"registry_uri": "123456"}
    response = controllers.workflows_post(body=data)
    logger.debug("Response: %r, %r", response, str(response.data))
    assert_status_code(response.status_code, 400)
    assert messages.unexpected_registry_uri in response.data.decode(),\
        "Unexpected error message"


@patch("lifemonitor.api.controllers.lm")
def test_post_workflow_by_registry_error_missing_submitter_id(m, base_request_context, registry):
    assert auth.current_user.is_anonymous, "Unexpected user in session"
    assert auth.current_registry, "Unexpected registry in session"
    # add one fake workflow
    data = {}
    response = controllers.workflows_post(body=data)
    logger.debug("Response: %r, %r", response, str(response.data))
    assert_status_code(response.status_code, 400)
    assert messages.no_submitter_id_provided in response.data.decode(),\
        "Unexpected error message"


@patch("lifemonitor.api.controllers.lm")
def test_post_workflow_by_registry_error_submitter_not_found(m, base_request_context, registry):
    assert auth.current_user.is_anonymous, "Unexpected user in session"
    assert auth.current_registry, "Unexpected registry in session"
    # add one fake workflow
    data = {"submitter_id": 1}
    m.find_registry_user_identity.side_effect = OAuthIdentityNotFoundException()
    response = controllers.workflows_post(body=data)
    logger.debug("Response: %r, %r", response, str(response.data))
    assert_status_code(response.status_code, 401)
    assert messages.no_user_oauth_identity_on_registry \
        .format(data["submitter_id"], registry.name) in response.data.decode(),\
        "Unexpected error message"


@patch("lifemonitor.api.controllers.lm")
def test_post_workflow_by_registry(m, base_request_context, registry):
    assert auth.current_user.is_anonymous, "Unexpected user in session"
    assert auth.current_registry, "Unexpected registry in session"
    # add one fake workflow
    data = {
        "uuid": "1212121212121212",
        "version": "1.0",
        "submitter_id": "1",
        "roc_link": "https://registry.org/roc_crate/download"
    }
    w = MagicMock()
    w.uuid = data['uuid']
    w.version = data['version']
    m.register_workflow.return_value = w
    response = controllers.workflows_post(body=data)
    logger.debug("Response: %r", response)
    assert_status_code(response[1], 201)
    assert response[0]["wf_uuid"] == data['uuid'] and \
        response[0]["wf_version"] == data['version']


@patch("lifemonitor.api.controllers.lm")
def test_post_workflow_by_registry_invalid_rocrate(m, base_request_context, registry):
    assert auth.current_user.is_anonymous, "Unexpected user in session"
    assert auth.current_registry, "Unexpected registry in session"
    # add one fake workflow
    data = {
        "uuid": "1212121212121212",
        "version": "1.0",
        "submitter_id": "1",
        "roc_link": "https://registry.org/roc_crate/download"
    }
    w = MagicMock()
    w.uuid = data['uuid']
    w.version = data['version']
    m.register_workflow.side_effect = common.NotValidROCrateException()
    response = controllers.workflows_post(body=data)
    logger.debug("Response: %r", response)
    assert_status_code(response.status_code, 400)
    assert messages.invalid_ro_crate in response.data.decode()


@patch("lifemonitor.api.controllers.lm")
def test_post_workflow_by_registry_not_authorized(m, base_request_context, registry):
    assert auth.current_user.is_anonymous, "Unexpected user in session"
    assert auth.current_registry, "Unexpected registry in session"
    # add one fake workflow
    data = {
        "uuid": "1212121212121212",
        "version": "1.0",
        "submitter_id": "1",
        "roc_link": "https://registry.org/roc_crate/download"
    }
    w = MagicMock()
    w.uuid = data['uuid']
    w.version = data['version']
    m.register_workflow.side_effect = common.NotAuthorizedException()
    response = controllers.workflows_post(body=data)
    logger.debug("Response: %r", response)
    assert_status_code(response.status_code, 403)
    assert messages.not_authorized_registry_access\
        .format(registry.name) in response.data.decode()