import json
import pytest
import logging

from tests import utils
from tests.conftest_types import ClientAuthenticationMethod


logger = logging.getLogger()


@pytest.mark.parametrize("client_auth_method", [
    #    ClientAuthenticationMethod.BASIC,
    ClientAuthenticationMethod.API_KEY,
    ClientAuthenticationMethod.AUTHORIZATION_CODE,
    ClientAuthenticationMethod.CLIENT_CREDENTIALS
], indirect=True)
def test_get_instance(app_client, client_auth_method, user1, user1_auth):
    w, workflow = utils.pick_and_register_workflow(user1, "sort-and-change-case")
    assert len(workflow.test_suites) > 0, "Unexpected number of test suites"
    suite = workflow.test_suites[0]
    logger.debug("The test suite: %r", suite)
    assert len(suite.test_instances) > 0, "Unexpected number of test instances"
    instance = suite.test_instances[0]
    logger.debug("The test instance: %r", instance)

    response = app_client.get(f"{utils.build_instances_path(instance.uuid)}",
                              headers=user1_auth)
    logger.debug(response)
    utils.assert_status_code(200, response.status_code)
    data = json.loads(response.data)
    logger.debug("Response data: %r", data)
    # redundant check: the validation is performed by the connexion framework
    utils.assert_properties_exist(["name", "service"], data)
    assert data['uuid'] == str(instance.uuid), "Invalid UUID"


@pytest.mark.parametrize("client_auth_method", [
    #    ClientAuthenticationMethod.BASIC,
    ClientAuthenticationMethod.API_KEY,
    ClientAuthenticationMethod.AUTHORIZATION_CODE,
    ClientAuthenticationMethod.CLIENT_CREDENTIALS
], indirect=True)
def test_get_instance_builds(app_client, client_auth_method, user1, user1_auth):
    w, workflow = utils.pick_and_register_workflow(user1, "sort-and-change-case")
    assert len(workflow.test_suites) > 0, "Unexpected number of test suites"
    suite = workflow.test_suites[0]
    logger.debug("The test suite: %r", suite)
    assert len(suite.test_instances) > 0, "Unexpected number of test instances"
    instance = suite.test_instances[0]
    logger.debug("The test instance: %r", instance)

    response = app_client.get(f"{utils.build_instances_path(instance.uuid)}/latest-builds",
                              headers=user1_auth)
    logger.debug(response)
    utils.assert_status_code(200, response.status_code)
    data = json.loads(response.data)
    logger.debug("Response data: %r", data)
    # redundant check: the validation is performed by the connexion framework
    assert "items" in data, "Missing item property"
    assert len(data['items']) > 0, "Unexpected number of items"
    item = data['items'][0]
    utils.assert_properties_exist(["build_id", "instance"], item)


@pytest.mark.parametrize("client_auth_method", [
    #    ClientAuthenticationMethod.BASIC,
    ClientAuthenticationMethod.API_KEY,
    ClientAuthenticationMethod.AUTHORIZATION_CODE,
    ClientAuthenticationMethod.CLIENT_CREDENTIALS
], indirect=True)
def test_get_instance_build(app_client, client_auth_method, user1, user1_auth):
    w, workflow = utils.pick_and_register_workflow(user1, "sort-and-change-case")
    assert len(workflow.test_suites) > 0, "Unexpected number of test suites"
    suite = workflow.test_suites[0]
    logger.debug("The test suite: %r", suite)
    assert len(suite.test_instances) > 0, "Unexpected number of test instances"
    instance = suite.test_instances[0]
    logger.debug("The test instance: %r", instance)
    assert len(instance.test_builds) > 0, "Unexpected number of test builds"
    build = instance.test_builds[0]

    response = app_client.get(f"{utils.build_instances_path(instance.uuid)}/builds/{build.id}",
                              headers=user1_auth)
    logger.debug(response)
    utils.assert_status_code(response.status_code, 200)
    data = json.loads(response.data)
    logger.debug("Response data: %r", data)
    # redundant check: the validation is performed by the connexion framework
    utils.assert_properties_exist(["build_id", "instance"], data)


@pytest.mark.parametrize("client_auth_method", [
    #    ClientAuthenticationMethod.BASIC,
    ClientAuthenticationMethod.API_KEY,
    ClientAuthenticationMethod.AUTHORIZATION_CODE,
    ClientAuthenticationMethod.CLIENT_CREDENTIALS
], indirect=True)
def test_get_instance_build_logs(app_client, client_auth_method, user1, user1_auth):
    w, workflow = utils.pick_and_register_workflow(user1, "sort-and-change-case")
    assert len(workflow.test_suites) > 0, "Unexpected number of test suites"
    suite = workflow.test_suites[0]
    logger.debug("The test suite: %r", suite)
    assert len(suite.test_instances) > 0, "Unexpected number of test instances"
    instance = suite.test_instances[0]
    logger.debug("The test instance: %r", instance)
    assert len(instance.test_builds) > 0, "Unexpected number of test builds"
    build = instance.test_builds[0]

    response = app_client.get(f"{utils.build_instances_path(instance.uuid)}/builds/{build.id}/logs",
                              headers=user1_auth)
    logger.debug(response)
    utils.assert_status_code(response.status_code, 200)
    data = json.loads(response.data)
    logger.debug("Response data: %r", data)
    # redundant check: the validation is performed by the connexion framework
    assert isinstance(data, str), "Unexpected result type"