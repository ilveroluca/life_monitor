from __future__ import annotations

import logging

import flask
from authlib.integrations.flask_client import FlaskRemoteApp

from flask import flash, url_for, redirect, request, session, Blueprint, current_app, abort
from flask_login import current_user, login_user

from lifemonitor.auth.models import User
from .models import OAuthUserProfile, OAuthIdentity
from .services import oauth2_registry
from authlib.integrations.base_client.errors import OAuthError
from lifemonitor.auth.oauth2.client.models import OAuthIdentityNotFoundException

# Config a module level logger
logger = logging.getLogger(__name__)

_OAUTH2_NEXT_URL = "oauth2.next"


def create_blueprint(merge_identity_view):
    authorization_handler = AuthorizatonHandler(merge_identity_view)

    def _handle_authorize(provider: FlaskRemoteApp, token, user_info):
        return authorization_handler.handle_authorize(provider, token, OAuthUserProfile.from_dict(user_info))

    blueprint = Blueprint('oauth2provider', __name__)

    @blueprint.route('/authorize/<name>', methods=('GET', 'POST'))
    def authorize(name):
        remote = oauth2_registry.create_client(name)
        if remote is None:
            abort(404)

        next_url = flask.request.args.get('next')
        if next_url:
            return redirect(url_for(".login", name=name, next=next_url))

        try:
            id_token = request.values.get('id_token')
            if request.values.get('code'):
                token = remote.authorize_access_token()
                if id_token:
                    token['id_token'] = id_token
            elif id_token:
                token = {'id_token': id_token}
            elif request.values.get('oauth_verifier'):
                # OAuth 1
                token = remote.authorize_access_token()
            else:
                # handle failed
                return _handle_authorize(remote, None, None)
            if 'id_token' in token:
                user_info = remote.parse_id_token(token)
            else:
                remote.token = token
                user_info = remote.userinfo(token=token)
            return _handle_authorize(remote, token, user_info)
        except OAuthError as e:
            logger.debug(e)
            if not request.args.get("state", False):
                return redirect(url_for(".login", name=name, next=remote.api_base_url))
            return e.description, 401

    @blueprint.route('/login/<name>')
    def login(name):
        remote = oauth2_registry.create_client(name)
        if remote is None:
            abort(404)
        # save the 'next' parameter to allow automatic redirect after OAuth2 authorization
        next_url = flask.request.args.get('next')
        if next_url:
            session[_OAUTH2_NEXT_URL] = next_url
        redirect_uri = url_for('.authorize', name=name, _external=True)
        conf_key = '{}_AUTHORIZE_PARAMS'.format(name.upper())
        params = current_app.config.get(conf_key, {})
        return remote.authorize_redirect(redirect_uri, **params)

    return blueprint


class AuthorizatonHandler:

    def __init__(self, merge_view="auth.merge") -> None:
        self.merge_view = merge_view

    def handle_authorize(self, provider: FlaskRemoteApp, token, user_info: OAuthUserProfile):
        logger.debug("Remote: %r", provider.name)
        logger.debug("Acquired token: %r", token)
        logger.debug("Acquired user_info: %r", user_info)

        try:
            identity = OAuthIdentity.find_by_provider(provider.name, user_info.sub)
            logger.debug("Found OAuth identity <%r,%r>: %r",
                         provider.name, user_info.sub, identity)
            # update identity with the last token and userinfo
            identity.user_info = user_info.to_dict()
            identity.token = token
        except OAuthIdentityNotFoundException:
            logger.debug("Not found OAuth identity <%r,%r>", provider.name, user_info.sub)
            identity = OAuthIdentity(
                provider_user_id=user_info.sub,
                provider=provider.name,
                user_info=user_info.to_dict(),
                token=token,
            )

        # Now, figure out what to do with this token. There are 2x2 options:
        # user login state and token link state.
        if current_user.is_anonymous:
            # If the user is not logged in and the token is linked,
            # log the identity user
            if identity.user:
                login_user(identity.user)
            else:
                # If the user is not logged in and the token is unlinked,
                # create a new local user account and log that account in.
                # This means that one person can make multiple accounts, but it's
                # OK because they can merge those accounts later.
                user = User.find_by_username(user_info.preferred_username)
                if not user:
                    user = User(username=user_info.preferred_username)
                identity.user = user
                identity.save()
                login_user(user)
                flash("OAuth identity linked to the current user account.")
        else:
            if identity.user:
                # If the user is logged in and the token is linked, check if these
                # accounts are the same!
                if current_user != identity.user:
                    # Account collision! Ask user if they want to merge accounts.
                    return redirect(url_for(self.merge_view,
                                            provider=identity.provider,
                                            username=identity.user.username))
            # If the user is logged in and the token is unlinked or linked yet,
            # link the token to the current user
            identity.user = current_user
            identity.save()
            flash("Successfully linked GitHub account.")

        # Determine the right next hop
        next_url = flask.request.args.get('next')
        logger.debug("Request redirect (next URL stored on the 'next' request param: %r)", next_url)
        if not next_url:
            next_url = flask.session.pop(_OAUTH2_NEXT_URL, False)
            logger.debug("Request redirect (next URL stored on session: %r)", next_url)
        return redirect(next_url or '/')