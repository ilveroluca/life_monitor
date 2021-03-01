from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List, Union

import lifemonitor.api.models as models
import requests
from authlib.integrations.base_client import RemoteApp
from lifemonitor.api.models import db
from lifemonitor.auth.models import (ExternalServiceAccessAuthorization,
                                     Resource, User)
from lifemonitor.auth.oauth2.client.models import OAuthIdentity
from lifemonitor.auth.oauth2.client.services import oauth2_registry
from lifemonitor.exceptions import (EntityNotFoundException,
                                    NotAuthorizedException)
from lifemonitor.utils import ClassManager, download_url
from sqlalchemy.ext.associationproxy import association_proxy

# set module level logger
logger = logging.getLogger(__name__)


class WorkflowRegistryClient(ABC):

    client_types = ClassManager('lifemonitor.api.models.registries', class_suffix="WorkflowRegistryClient", skip=["registry"])

    def __init__(self, registry: WorkflowRegistry):
        self._registry = registry
        try:
            self._oauth2client: RemoteApp = getattr(oauth2_registry, self.registry.name)
        except AttributeError:
            raise RuntimeError(f"Unable to find a OAuth2 client for the {self.registry.name} service")

    @property
    def registry(self):
        return self._registry

    def _get_access_token(self, user_id):
        # get the access token related with the user of this client registry
        return OAuthIdentity.find_by_user_id(user_id, self.registry.name).token

    def _get(self, user, *args, **kwargs):
        with requests.Session() as session:
            for auth in user.get_authorization(self.registry):
                session.headers['Authorization'] = auth.as_http_header()
                r = session.get(*args, **kwargs)
                if r.status_code == 401 or r.status_code == 403:
                    raise NotAuthorizedException(details=r.content)
                r.raise_for_status()
                return r

    def download_url(self, url, user, target_path=None):
        return download_url(url, target_path,
                            authorization=f'Bearer {self._get_access_token(user.id)["access_token"]}')

    def get_external_id(self, uuid, version, user: User) -> str:
        """ Return CSV of uuid and version"""
        return ",".join([str(uuid), str(version)])

    @abstractmethod
    def build_ro_link(self, w: models.WorkflowVersion) -> str:
        pass

    @abstractmethod
    def get_workflows_metadata(self, user, details=False):
        pass

    @abstractmethod
    def get_workflow_metadata(self, user, w: Union[models.WorkflowVersion, str]):
        pass

    @abstractmethod
    def filter_by_user(workflows: list, user: User):
        pass

    @classmethod
    def get_client_class(cls, client_type):
        return cls.client_types.get_class(client_type)


class WorkflowRegistry(Resource):

    id = db.Column(db.Integer, db.ForeignKey(Resource.id), primary_key=True)
    registry_type = db.Column(db.String, nullable=False)
    _client_id = db.Column(db.Integer, db.ForeignKey('oauth2_client.id', ondelete='CASCADE'))
    _server_id = db.Column(db.Integer, db.ForeignKey('oauth2_identity_provider.id', ondelete='CASCADE'))
    client_credentials = db.relationship("Client", uselist=False, cascade="all, delete")
    server_credentials = db.relationship("OAuth2IdentityProvider",
                                         uselist=False, cascade="all, delete",
                                         foreign_keys=[_server_id],
                                         backref="workflow_registry")
    client_id = association_proxy('client_credentials', 'client_id')

    _client = None

    registry_types = ClassManager('lifemonitor.api.models.registries', class_suffix="WorkflowRegistry", skip=["registry"])

    __mapper_args__ = {
        'polymorphic_identity': 'workflow_registry'
    }

    def __init__(self, registry_type, client_credentials, server_credentials):
        super().__init__(self.__class__.__name__,
                         server_credentials.api_base_url, name=server_credentials.name)
        self.registry_type = registry_type
        self.client_credentials = client_credentials
        self.server_credentials = server_credentials
        self._client = None

    def __repr__(self):
        return '<WorkflowRegistry ({}) -- name {}, url {}>'.format(
            self.uuid, self.name, self.uri)

    @property
    def api(self) -> Resource:
        return self.server_credentials.api_resource

    @property
    def client(self) -> WorkflowRegistryClient:
        if self._client is None:
            rtype = self.__class__.__name__.replace("WorkflowRegistry", "").lower()
            return WorkflowRegistryClient.get_client_class(rtype)(self)
        return self._client

    def get_external_id(self, uuid, version, user: User):
        return self.client.get_external_id(uuid, version, user)

    def build_ro_link(self, w: models.WorkflowVersion) -> str:
        return self.client.build_ro_link(w)

    def download_url(self, url, user, target_path=None):
        return self.client.download_url(url, user, target_path=target_path)

    @property
    def users(self) -> List[User]:
        return self.get_users()

    @property
    def registered_workflows(self):
        return self.ro_crates

    def get_user(self, user_id) -> User:
        for u in self.users:
            logger.debug(f"Checking {u.id} {user_id}")
            if u.id == user_id:
                return u
        raise EntityNotFoundException(User, entity_id=user_id)

    def get_users(self) -> List[User]:
        try:
            return [i.user for i in OAuthIdentity.query
                    .filter(OAuthIdentity.provider == self.server_credentials).all()]
        except Exception as e:
            raise EntityNotFoundException(e)

    def get_authorization(self, user: User):
        auths = ExternalServiceAccessAuthorization.find_by_user_and_resource(user, self)
        # check for sub-resource authorizations

        return auths

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def get_workflow(self, uuid, version=None):
        try:
            return models.WorkflowVersion.get_registry_workflow(self.uuid, uuid, version=version)
        except Exception as e:
            raise EntityNotFoundException(models.Workflow, details=str(e), entity_id=uuid)

    def get_workflow_versions(self, uuid):
        try:
            workflows = models.WorkflowVersion.query.with_parent(self)\
                .filter(models.WorkflowVersion.uuid == uuid).order_by(models.WorkflowVersion.version.desc())
            return {w.version: w for w in workflows}
        except Exception as e:
            raise EntityNotFoundException(e)

    def get_user_workflows(self, user: User):
        return self.client.filter_by_user(self.registered_workflows, user)

    @classmethod
    def all(cls):
        return cls.query.all()

    @classmethod
    def find_by_id(cls, uuid) -> WorkflowRegistry:
        try:
            return cls.query.filter(cls.uuid == uuid).one()
        except Exception as e:
            raise EntityNotFoundException(WorkflowRegistry, entity_id=uuid, exception=e)

    @classmethod
    def find_by_name(cls, name):
        try:
            return cls.query.filter(WorkflowRegistry.name == name).one()
        except Exception as e:
            raise EntityNotFoundException(WorkflowRegistry, entity_id=name, exception=e)

    @classmethod
    def find_by_uri(cls, uri):
        try:
            return cls.query.filter(WorkflowRegistry.uri == uri).one()
        except Exception as e:
            raise EntityNotFoundException(WorkflowRegistry, entity_id=uri, exception=e)

    @classmethod
    def find_by_client_id(cls, client_id):
        try:
            return cls.query.filter_by(client_id=client_id).first()
        except Exception as e:
            raise EntityNotFoundException(WorkflowRegistry, entity_id=client_id, exception=e)

    @classmethod
    def get_registry_class(cls, registry_type):
        return cls.registry_types.get_class(registry_type)

    @classmethod
    def new_instance(cls, registry_type, client_credentials, server_credentials):
        return cls.get_registry_class(registry_type)(client_credentials,
                                                     server_credentials)
