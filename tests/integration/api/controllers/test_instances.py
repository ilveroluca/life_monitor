# Copyright (c) 2020-2021 CRS4
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

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
    ClientAuthenticationMethod.CLIENT_CREDENTIALS,
    ClientAuthenticationMethod.REGISTRY_CODE_FLOW
], indirect=True)
def test_get_instance(app_client, client_auth_method, user1, user1_auth, valid_workflow):
    w, workflow = utils.pick_and_register_workflow(user1, valid_workflow)
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
    ClientAuthenticationMethod.CLIENT_CREDENTIALS,
    ClientAuthenticationMethod.REGISTRY_CODE_FLOW
], indirect=True)
def test_get_instance_builds(app_client, client_auth_method, user1, user1_auth, valid_workflow):
    w, workflow = utils.pick_and_register_workflow(user1, valid_workflow)
    assert len(workflow.test_suites) > 0, "Unexpected number of test suites"
    suite = workflow.test_suites[0]
    logger.debug("The test suite: %r", suite)
    assert len(suite.test_instances) > 0, "Unexpected number of test instances"
    instance = suite.test_instances[0]
    logger.debug("The test instance: %r", instance)

    response = app_client.get(f"{utils.build_instances_path(instance.uuid)}/latest-builds?limit=2",
                              headers=user1_auth)
    logger.debug(response)
    utils.assert_status_code(200, response.status_code)
    data = json.loads(response.data)
    logger.debug("Response data: %r", data)
    # redundant check: the validation is performed by the connexion framework
    assert "items" in data, "Missing item property"
    num_items = len(data['items'])
    logger.info("Number of items: %d", num_items)
    assert num_items > 0, "Unexpected number of items"
    # check one item
    item = data['items'][0]
    utils.assert_properties_exist(["build_id", "instance"], item)


@pytest.mark.parametrize("client_auth_method", [
    #    ClientAuthenticationMethod.BASIC,
    ClientAuthenticationMethod.API_KEY,
    ClientAuthenticationMethod.AUTHORIZATION_CODE,
    ClientAuthenticationMethod.CLIENT_CREDENTIALS,
    ClientAuthenticationMethod.REGISTRY_CODE_FLOW
], indirect=True)
def test_get_instance_builds_limit_parameter(app_client, client_auth_method, user1, user1_auth, valid_workflow):
    w, workflow = utils.pick_and_register_workflow(user1, valid_workflow)
    assert len(workflow.test_suites) > 0, "Unexpected number of test suites"
    suite = workflow.test_suites[0]
    logger.debug("The test suite: %r", suite)
    assert len(suite.test_instances) > 0, "Unexpected number of test instances"
    instance = suite.test_instances[0]
    logger.debug("The test instance: %r", instance)

    # check limit parameter
    for limit in range(1, 4):
        response = app_client.get(f"{utils.build_instances_path(instance.uuid)}/latest-builds?limit={limit}",
                                  headers=user1_auth)
        logger.debug(response)
        utils.assert_status_code(200, response.status_code)
        data = json.loads(response.data)
        logger.debug("Response data: %r", data)
        # redundant check: the validation is performed by the connexion framework
        assert "items" in data, "Missing item property"
        num_items = len(data['items'])
        logger.info("Number of items: %d", num_items)
        assert num_items == limit, "Unexpected number of items"
        logger.info("Loaded builds: %s", data)


@pytest.mark.parametrize("client_auth_method", [
    #    ClientAuthenticationMethod.BASIC,
    ClientAuthenticationMethod.API_KEY,
    ClientAuthenticationMethod.AUTHORIZATION_CODE,
    ClientAuthenticationMethod.CLIENT_CREDENTIALS,
    ClientAuthenticationMethod.REGISTRY_CODE_FLOW
], indirect=True)
def test_get_instance_build(app_client, client_auth_method, user1, user1_auth, valid_workflow):
    w, workflow = utils.pick_and_register_workflow(user1, valid_workflow)
    assert len(workflow.test_suites) > 0, "Unexpected number of test suites"
    suite = workflow.test_suites[0]
    logger.debug("The test suite: %r", suite)
    assert len(suite.test_instances) > 0, "Unexpected number of test instances"
    instance = suite.test_instances[0]
    logger.debug("The test instance: %r", instance)
    assert len(instance.get_test_builds()) > 0, "Unexpected number of test builds"
    build = instance.get_test_builds()[0]

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
    ClientAuthenticationMethod.CLIENT_CREDENTIALS,
    ClientAuthenticationMethod.REGISTRY_CODE_FLOW
], indirect=True)
def test_get_instance_build_logs(app_client, client_auth_method, user1, user1_auth, valid_workflow):
    w, workflow = utils.pick_and_register_workflow(user1, valid_workflow)
    assert len(workflow.test_suites) > 0, "Unexpected number of test suites"
    suite = workflow.test_suites[0]
    logger.debug("The test suite: %r", suite)
    assert len(suite.test_instances) > 0, "Unexpected number of test instances"
    instance = suite.test_instances[0]
    logger.debug("The test instance: %r", instance)
    assert len(instance.get_test_builds()) > 0, "Unexpected number of test builds"
    build = instance.get_test_builds()[0]

    response = app_client.get(f"{utils.build_instances_path(instance.uuid)}/builds/{build.id}/logs",
                              headers=user1_auth)
    logger.debug(response.data)
    utils.assert_status_code(response.status_code, 200)
    data = json.loads(response.data)
    logger.debug("Response data: %r", data)
    # redundant check: the validation is performed by the connexion framework
    assert isinstance(data, str), "Unexpected result type"
