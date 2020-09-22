from __future__ import annotations

import re
import logging
import jenkins
import uuid as _uuid
from typing import Union
from importlib import import_module
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional
from authlib.integrations.base_client import RemoteApp
from sqlalchemy.dialects.postgresql import UUID, JSONB
from lifemonitor.db import db
from lifemonitor.auth.models import User
from sqlalchemy.ext.associationproxy import association_proxy
from lifemonitor.auth.oauth2.client.services import oauth2_registry
from lifemonitor.common import (SpecificationNotValidException, EntityNotFoundException,
                                SpecificationNotDefinedException, TestingServiceNotSupportedException,
                                NotImplementedException, TestingServiceException, LifeMonitorException)
from lifemonitor.utils import download_url, to_camel_case
from lifemonitor.auth.oauth2.client.models import OAuthIdentity

# set module level logger
logger = logging.getLogger(__name__)


class WorkflowRegistryClient(ABC):

    def __init__(self, registry: WorkflowRegistry):
        self._registry = registry
        try:
            self._oauth2client: RemoteApp = getattr(oauth2_registry, self.registry.name)
        except AttributeError:
            raise RuntimeError(f"Unable to find a OAuth2 client for the {self.name} service")

    @property
    def registry(self):
        return self._registry

    def _get_access_token(self, user_id):
        # get the access token related with the user of this client registry
        return OAuthIdentity.find_by_user_provider(user_id,
                                                   self.registry.name).token

    def _get(self, user, *args, **kwargs):
        # update token
        self._oauth2client.token = self._get_access_token(user.id)
        return self._oauth2client.get(*args, **kwargs)

    def download_url(self, url, user, target_path=None):
        return download_url(url, target_path, self._get_access_token(user.id)["access_token"])

    def get_external_id(self, uuid, version, user: User) -> str:
        """ Return CSV of uuid and version"""
        return ",".join([str(uuid), str(version)])

    @abstractmethod
    def build_ro_link(self, w: Workflow) -> str:
        pass

    @abstractmethod
    def get_workflows_metadata(self, user, details=False):
        pass

    @abstractmethod
    def get_workflow_metadata(self, user, w: Union[Workflow, str]):
        pass

    @abstractmethod
    def filter_by_user(workflows: list, user: User):
        pass


class WorkflowRegistry(db.Model):

    uuid = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
    name = db.Column(db.Text, unique=True)
    uri = db.Column(db.Text, unique=True)
    _client_id = db.Column(
        db.Integer, db.ForeignKey('client.id', ondelete='CASCADE')
    )
    client_credentials = db.relationship("Client", uselist=False, cascade="all, delete")
    registered_workflows = db.relationship("Workflow",
                                           back_populates="workflow_registry", cascade="all, delete")
    client_id = association_proxy('client_credentials', 'client_id')
    _client = None

    def __init__(self, name, client_credentials):
        self.__instance = self
        self.name = name
        self.uri = client_credentials.client_metadata['client_uri']
        self.client_credentials = client_credentials
        self._client = None

    @property
    def client(self) -> WorkflowRegistryClient:
        if self._client is None:
            m = f"lifemonitor.api.registry.{self.name}"
            try:
                mod = import_module(m)
                self._client = getattr(mod, "WorkflowRegistryClient")(self)
            except ModuleNotFoundError:
                raise LifeMonitorException(f"ModuleNotFoundError: Unable to load module {m}")
            except AttributeError:
                raise LifeMonitorException(f"Unable to create an instance of WorkflowRegistryClient from module {m}")
        return self._client

    def build_ro_link(self, w: Workflow) -> str:
        return self.client.build_ro_link(w)

    def download_url(self, url, user, target_path=None):
        return self.client.download_url(url, user, target_path=target_path)

    def get_users(self):
        pass

    def add_workflow(self, workflow_uuid, workflow_version,
                     workflow_submitter: User,
                     roc_link, roc_metadata=None,
                     external_id=None, name=None):
        if external_id is None:
            try:
                external_id = self.client.get_external_id(
                    workflow_uuid, workflow_version, workflow_submitter)
            except Exception as e:
                logger.exception(e)

        return Workflow(self, workflow_submitter,
                        workflow_uuid, workflow_version, roc_link,
                        roc_metadata=roc_metadata,
                        external_id=external_id, name=name)

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def get_workflow(self, uuid, version):
        try:
            return Workflow.query.with_parent(self)\
                .filter(Workflow.uuid == uuid).filter(Workflow.version == version).one()
        except Exception as e:
            raise EntityNotFoundException(e)

    def get_user_workflows(self, user: User):
        return self.client.filter_by_user(self.registered_workflows, user)

    @classmethod
    def all(cls):
        return cls.query.all()

    @classmethod
    def find_by_id(cls, uuid) -> WorkflowRegistry:
        return cls.query.get(uuid)

    @classmethod
    def find_by_name(cls, name):
        return cls.query.filter(WorkflowRegistry.name == name).first()

    @classmethod
    def find_by_uri(cls, uri):
        return cls.query.filter(WorkflowRegistry.uri == uri).first()

    @classmethod
    def find_by_client_id(cls, client_id):
        return cls.query.filter_by(client_id=client_id).first()


class Workflow(db.Model):
    _id = db.Column('id', db.Integer, primary_key=True)
    uuid = db.Column(UUID)
    version = db.Column(db.Text, nullable=False)
    roc_link = db.Column(db.Text, nullable=False)
    roc_metadata = db.Column(JSONB, nullable=True)
    submitter_id = db.Column(db.Integer,
                             db.ForeignKey(User.id), nullable=False)
    _registry_id = \
        db.Column("registry_id", UUID(as_uuid=True),
                  db.ForeignKey(WorkflowRegistry.uuid), nullable=False)
    external_id = db.Column(db.String, nullable=True)
    workflow_registry = db.relationship("WorkflowRegistry", uselist=False, back_populates="registered_workflows")
    name = db.Column(db.Text, nullable=True)
    test_suites = db.relationship("TestSuite", back_populates="workflow", cascade="all, delete")
    submitter = db.relationship("User", uselist=False)

    # additional relational specs
    __tablename__ = "workflow"
    __table_args__ = (
        db.UniqueConstraint(uuid, version),
        db.UniqueConstraint(_registry_id, external_id),
    )

    def __init__(self, registry: WorkflowRegistry, submitter: User,
                 uuid, version, rock_link,
                 roc_metadata=None, external_id=None, name=None) -> None:
        self.uuid = uuid
        self.version = version
        self.roc_link = rock_link
        self.roc_metadata = roc_metadata
        self.name = name
        self.external_id = external_id
        self.workflow_registry = registry
        self.submitter = submitter

    def __repr__(self):
        return '<Workflow ({}, {}); name: {}; link: {}>'.format(
            self.uuid, self.version, self.name, self.roc_link)

    def check_health(self) -> dict:
        health = {'healthy': True, 'issues': []}
        for suite in self.test_suites:
            for test_instance in suite.test_instances:
                try:
                    testing_service = test_instance.testing_service
                    if not testing_service.last_test_build.is_successful():
                        health["healthy"] = False
                except TestingServiceException as e:
                    health["issues"].append(str(e))
                    health["healthy"] = "Unknown"
        return health

    @property
    def is_healthy(self) -> Union[bool, str]:
        return self.check_health()["healthy"]

    def add_test_suite(self, submitter: User, test_suite_metadata):
        return TestSuite(self, submitter, test_suite_metadata)

    def to_dict(self, test_suite=False, test_build=False, test_output=False):
        health = self.check_health()
        data = {
            'uuid': str(self.uuid),
            'version': self.version,
            'name': self.name,
            'roc_link': self.roc_link,
            'isHealthy': health["healthy"],
            'issues': health["issues"]
        }
        if test_suite:
            data['test_suite'] = [s.to_dict(test_build=test_build, test_output=test_output)
                                  for s in self.test_suites]
        return data

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    @classmethod
    def all(cls):
        return cls.query.all()

    @classmethod
    def find_by_id(cls, uuid, version):
        return cls.query.filter(Workflow.uuid == uuid) \
            .filter(Workflow.version == version).first()

    @classmethod
    def find_by_submitter(cls, submitter: User):
        return cls.query.filter(Workflow.submitter_id == submitter.id).first()


class Test:

    def __init__(self,
                 project: TestSuite,
                 name: str, specification: object) -> None:
        self.name = name
        self.project = project
        self.specification = specification

    def __repr__(self):
        return '<Test {} of testing project {} (workflow {}, version {})>'.format(
            self.name, self.project, self.project.workflow.uuid, self.project.workflow.version)

    @property
    def instances(self) -> list:
        return self.project.get_test_instance_by_name(self.name)


class TestSuite(db.Model):
    uuid = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
    _workflow_id = db.Column("workflow_id", db.Integer,
                             db.ForeignKey(Workflow._id), nullable=False)
    workflow = db.relationship("Workflow", back_populates="test_suites")
    test_definition = db.Column(JSONB, nullable=False)
    submitter_id = db.Column(db.Integer,
                             db.ForeignKey(User.id), nullable=False)
    submitter = db.relationship("User", uselist=False)
    test_instances = db.relationship("TestInstance",
                                     back_populates="test_suite",
                                     cascade="all, delete")

    def __init__(self,
                 w: Workflow, submitter: User,
                 test_definition: object) -> None:
        self.workflow = w
        self.submitter = submitter
        self.test_definition = test_definition
        self._parse_test_definition()

    def __repr__(self):
        return '<TestSuite {} of workflow {} (version {})>'.format(
            self.uuid, self.workflow.uuid, self.workflow.version)

    def _parse_test_definition(self):
        try:
            for test in self.test_definition["test"]:
                for instance_data in test["instance"]:
                    logger.debug("Instance_data: %r", instance_data)
                    testing_service_data = instance_data["service"]
                    testing_service = TestingService.new_instance(
                        testing_service_data["type"],
                        testing_service_data["url"], testing_service_data["resource"])
                    logger.debug("Created TestService: %r", testing_service)
                    test_instance = TestInstance(self, self.submitter,
                                                 test["name"], testing_service)
                    logger.debug("Created TestInstance: %r", test_instance)
        except KeyError as e:
            raise SpecificationNotValidException(f"Missing property: {e}")

    def get_test_instance_by_name(self, name) -> list:
        result = []
        for ti in self.test_instances:
            if ti.name == name:
                result.append(ti)
        return result

    def to_dict(self, test_build=False, test_output=False) -> dict:
        return {
            'uuid': str(self.uuid),
            'test': [t.to_dict(test_build=test_build, test_output=test_output)
                     for t in self.test_instances]
        }

    def add_test_instance(self, submitter: User,
                          test_name, testing_service_type, testing_service_url):
        testing_service = \
            TestingService.new_instance(testing_service_type, testing_service_url)
        test_instance = TestInstance(self, submitter, test_name, testing_service)
        logger.debug("Created TestInstance: %r", test_instance)
        return test_instance

    @property
    def tests(self) -> Optional[dict]:
        if not self.test_definition:
            raise SpecificationNotDefinedException('Not test definition for the test suite {}'.format(self.uuid))
        if "test" not in self.test_definition:
            raise SpecificationNotValidException("'test' property not found")
        # TODO: implement a caching mechanism: with a custom setter for the test_definition collection
        result = {}
        for test in self.test_definition["test"]:
            result[test["name"]] = Test(self, test["name"],
                                        test["specification"] if "specification" in test else None)
        return result

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    @classmethod
    def all(cls):
        return cls.query.all()

    @classmethod
    def find_by_id(cls, uuid) -> TestSuite:
        return cls.query.get(uuid)


class TestInstance(db.Model):
    uuid = db.Column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
    _test_suite_uuid = \
        db.Column("test_suite_uuid", UUID(as_uuid=True), db.ForeignKey(TestSuite.uuid), nullable=False)
    name = db.Column(db.Text, nullable=False)
    parameters = db.Column(JSONB, nullable=True)
    submitter_id = db.Column(db.Integer,
                             db.ForeignKey(User.id), nullable=False)
    # configure relationships
    submitter = db.relationship("User", uselist=False)
    test_suite = db.relationship("TestSuite", back_populates="test_instances")
    testing_service = db.relationship("TestingService", uselist=False, back_populates="test_instance",
                                      cascade="all, delete", lazy='joined')

    def __init__(self, testing_suite: TestSuite, submitter: User,
                 test_name, testing_service: TestingService) -> None:
        self.test_suite = testing_suite
        self.submitter = submitter
        self.name = test_name
        self.testing_service = testing_service

    def __repr__(self):
        return '<TestInstance {} on TestSuite {}>'.format(self.uuid, self.test_suite.uuid)

    @property
    def test(self):
        if not self.test_suite:
            raise EntityNotFoundException(Test)
        return self.test_suite.tests[self.name]

    def to_dict(self, test_build=False, test_output=False):
        data = {
            'uuid': str(self.uuid),
            'name': self.name,
            'parameters': self.parameters,
            'testing_service': self.testing_service.to_dict(test_builds=False)
        }
        if test_build:
            data.update(self.testing_service.get_test_builds_as_dict(test_output=test_output))
        return data

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    @classmethod
    def all(cls):
        return cls.query.all()

    @classmethod
    def find_by_id(cls, uuid) -> TestInstance:
        return cls.query.get(uuid)


class TestingServiceToken:
    def __init__(self, key, secret):
        self.key = key
        self.secret = secret

    def __composite_values__(self):
        return self.key, self.secret

    def __repr__(self):
        return "<TestingServiceToken (key=%r, secret=****)>" % self.key

    def __eq__(self, other):
        return isinstance(other, TestingServiceToken) and other.key == self.key and other.secret == self.secret

    def __ne__(self, other):
        return not self.__eq__(other)


class TestingService(db.Model):
    uuid = db.Column("uuid", UUID(as_uuid=True), db.ForeignKey(TestInstance.uuid), primary_key=True)
    _type = db.Column("type", db.String, nullable=False)
    _key = db.Column("key", db.Text, nullable=True)
    _secret = db.Column("secret", db.Text, nullable=True)
    url = db.Column(db.Text, nullable=False)
    resource = db.Column(db.Text, nullable=False)
    # configure nested object
    token = db.composite(TestingServiceToken, _key, _secret)
    # configure relationships
    test_instance = db.relationship("TestInstance", back_populates="testing_service",
                                    cascade="all, delete", lazy='joined')

    __mapper_args__ = {
        'polymorphic_on': _type,
        'polymorphic_identity': 'testing_service'
    }

    def __init__(self, url: str, resource: str) -> None:
        self.url = url
        self.resource = resource

    def __repr__(self):
        return f'<TestingService {self.url}, resource {self.resource} ({self.uuid})>'

    @property
    def test_instance_name(self):
        return self.test_instance.name

    @property
    def is_workflow_healthy(self) -> bool:
        raise NotImplementedException()

    @property
    def last_test_build(self) -> TestBuild:
        raise NotImplementedException()

    @property
    def last_successful_test_build(self) -> TestBuild:
        raise NotImplementedException()

    @property
    def last_failed_test_build(self) -> TestBuild:
        raise NotImplementedException()

    @property
    def test_builds(self) -> list:
        raise NotImplementedException()

    def get_test_builds_as_dict(self, test_output):
        last_test_build = self.last_test_build
        last_successful_test_build = self.last_successful_test_build
        last_failed_test_build = self.last_failed_test_build
        return {
            'last_test_build': last_test_build.to_dict(test_output) if last_test_build else None,
            'last_successful_test_build':
                last_successful_test_build.to_dict(test_output) if last_successful_test_build else None,
            'last_failed_test_build':
                last_failed_test_build.to_dict(test_output) if last_failed_test_build else None,
            "test_builds": [t.to_dict(test_output) for t in self.test_builds]
        }

    def to_dict(self, test_builds=False, test_output=False) -> dict:
        data = {
            'uuid': str(self.uuid),
            'testing_service_url': self.url,
            'workflow_healthy': self.is_workflow_healthy,
        }
        if test_builds:
            data["test_build"] = self.get_test_builds_as_dict(test_output=test_output)
        return data

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    @classmethod
    def all(cls):
        return cls.query.all()

    @classmethod
    def find_by_id(cls, uuid) -> TestingService:
        return cls.query.get(uuid)

    @classmethod
    def new_instance(cls, service_type, url: str, resource: str):
        try:
            service_class = globals()["{}TestingService".format(to_camel_case(service_type))]
        except KeyError:
            raise TestingServiceNotSupportedException(f"Not supported testing service type '{service_type}'")
        return service_class(url, resource)


class TestBuild(ABC):
    class Result(Enum):
        SUCCESS = 0
        FAILED = 1

    def __init__(self, testing_service: TestingService, metadata) -> None:
        self.testing_service = testing_service
        self._metadata = metadata

    def is_successful(self):
        return self.result == TestBuild.Result.SUCCESS

    @property
    def metadata(self):
        return self._metadata

    @property
    @abstractmethod
    def build_number(self) -> int:
        pass

    @property
    @abstractmethod
    def last_built_revision(self):
        pass

    @property
    @abstractmethod
    def duration(self) -> int:
        pass

    @property
    @abstractmethod
    def output(self) -> str:
        pass

    @property
    @abstractmethod
    def result(self) -> TestBuild.Result:
        pass

    @property
    @abstractmethod
    def url(self) -> str:
        pass

    def to_dict(self, test_output=False) -> dict:
        data = {
            'success': self.is_successful(),
            'build_number': self.build_number,
            'last_build_revision': self.last_built_revision,
            'duration': self.duration
        }
        if test_output:
            data['output'] = self.output
        return data


class JenkinsTestBuild(TestBuild):

    @property
    def build_number(self) -> int:
        return self.metadata['number']

    @property
    def last_built_revision(self):
        rev_info = list(map(lambda x: x["lastBuiltRevision"],
                            filter(lambda x: "lastBuiltRevision" in x, self.metadata["actions"])))
        return rev_info[0] if len(rev_info) == 1 else None

    @property
    def duration(self) -> int:
        return self.metadata['duration']

    @property
    def output(self) -> str:
        return self.testing_service.get_test_build_output(self.build_number)

    @property
    def result(self) -> TestBuild.Result:
        return TestBuild.Result.SUCCESS \
            if self.metadata["result"] == "SUCCESS" else TestBuild.Result.FAILED

    @property
    def url(self) -> str:
        return self.metadata['url']


class JenkinsTestingService(TestingService):
    _server = None
    _job_name = None
    __mapper_args__ = {
        'polymorphic_identity': 'jenkins_testing_service'
    }

    def __init__(self, url: str, resource: str) -> None:
        super().__init__(url, resource)
        try:
            self._server = jenkins.Jenkins(self.url)
        except Exception as e:
            raise TestingServiceException(e)

    @property
    def server(self):
        if not self._server:
            self._server = jenkins.Jenkins(self.url)
        return self._server

    @property
    def job_name(self):
        # extract the job name from the resource path
        if self._job_name is None:
            logger.debug(f"Getting project metadata - resource: {self.resource}")
            self._job_name = re.sub("(?s:.*)/", "", self.resource.strip('/'))
            logger.debug(f"The job name: {self._job_name}")
            if not self._job_name or len(self._job_name) == 0:
                raise TestingServiceException(
                    f"Unable to get the Jenkins job from the resource {self._job_name}")
        return self._job_name

    @property
    def is_workflow_healthy(self) -> bool:
        return self.last_test_build.is_successful()

    @property
    def last_test_build(self) -> Optional[JenkinsTestBuild]:
        if self.project_metadata['lastBuild']:
            return self.get_test_build(self.project_metadata['lastBuild']['number'])
        return None

    @property
    def last_successful_test_build(self) -> Optional[JenkinsTestBuild]:
        if self.project_metadata['lastSuccessfulBuild']:
            return self.get_test_build(self.project_metadata['lastSuccessfulBuild']['number'])
        return None

    @property
    def last_failed_test_build(self) -> Optional[JenkinsTestBuild]:
        if self.project_metadata['lastFailedBuild']:
            return self.get_test_build(self.project_metadata['lastFailedBuild']['number'])
        return None

    @property
    def test_builds(self) -> list:
        builds = []
        for build_info in self.project_metadata['builds']:
            builds.append(self.get_test_build(build_info['number']))
        return builds

    @property
    def project_metadata(self):
        try:
            return self.server.get_job_info(self.job_name)
        except jenkins.JenkinsException as e:
            raise TestingServiceException(f"{self}: {e}")

    def get_test_build(self, build_number) -> JenkinsTestBuild:
        try:
            build_metadata = self.server.get_build_info(self.job_name, build_number)
            return JenkinsTestBuild(self, build_metadata)
        except jenkins.JenkinsException as e:
            raise TestingServiceException(e)

    def get_test_build_output(self, build_number):
        try:
            return self.server.get_build_console_output(self.job_name, build_number)
        except jenkins.JenkinsException as e:
            raise TestingServiceException(e)