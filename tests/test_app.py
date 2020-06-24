import json
import uuid
import logging
from .fixtures import client, clean_db
from lifemonitor.app import LifeMonitor
from lifemonitor.model import (
    Workflow, TestSuite, TestConfiguration,
    TestingService, JenkinsTestingService
)

logger = logging.getLogger()

roc_link = "http://172.30.10.100:3000/workflows/2/ro_crate?version=1"
workflow_uuid = str(uuid.uuid4())
workflow_version = "1.0"

workflow = None
project = None


def test_workflow_registration(client, clean_db):
    lm = LifeMonitor.get_instance()
    lm.register_workflow(workflow_uuid, workflow_version, roc_link, "prova")


def test_suite_registration(client):
    global workflow, project
    lm = LifeMonitor.get_instance()
    with open("test-definition.json") as td:
        test_definition = json.load(td)
    logger.debug("TestDefinition: %r", test_definition)
    project = lm.register_test_suite(workflow_uuid, workflow_version, test_definition)
    assert len(project.workflow.test_suites) == 1, \
        "Unexpected number of test_suites for the workflow {}".format(project.workflow.uuid)
    logger.debug("Project: %r", project)
    assert len(project.tests) == 1, "Unexpected number of tests for the testing project {}".format(project)
    for t in project.tests:
        logger.debug("- test: %r", t)
    assert len(project.test_configurations) == 1, "Unexpected number of test_configurations " \
                                                  "for the testing project {}".format(project)
    for t in project.test_configurations:
        logger.debug("- test instance: %r --> Service: %r,%s", t, t.testing_service, t.testing_service.url)


def test_jenkins_service_type(client):
    w = Workflow.find_by_id(workflow_uuid, workflow_version)
    suite = w.test_suites[0]
    conf = suite.test_configurations[0]
    service = conf.testing_service
    assert isinstance(service, JenkinsTestingService), "Unexpected type for service"
    assert service.server is not None, "Not found _server property"


def test_workflow_health_status(client):
    lm = LifeMonitor.get_instance()
    status = lm.get_workflow_health_status(workflow_uuid, workflow_version, True)
    logger.debug("Status: %r", status)
    with open("health_status.json", "w") as out:
        out.write(json.dumps(status, indent=2))


def test_project_deregistration(client):
    global project
    assert project, "Project not initialized!"
    logger.debug("The current TestinProject: %r", project)
    lm = LifeMonitor.get_instance()
    lm.deregister_test_suite(project.uuid)
    w = Workflow.find_by_id(workflow_uuid, workflow_version)
    assert len(w.test_suites) == 0, \
        "Unexpected number of test_suites for the workflow {}".format(w.uuid)
    assert len(Workflow.all()) == 1, "Unexpected number of workflows"


def test_workflow_deregistration(client):
    global workflow
    lm = LifeMonitor.get_instance()
    lm.deregister_workflow(workflow_uuid, workflow_version)
    workflow = None
    assert len(Workflow.all()) == 0, "Unexpected number of workflows"