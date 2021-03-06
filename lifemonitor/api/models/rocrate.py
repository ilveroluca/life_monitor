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

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

import lifemonitor.exceptions as lm_exceptions
from lifemonitor.api.models import db
from lifemonitor.auth.models import Resource
from lifemonitor.models import JSON
from lifemonitor.test_metadata import get_old_format_tests
from lifemonitor.utils import download_url, extract_zip
from rocrate.rocrate import ROCrate as ROCrateHelper
from sqlalchemy.ext.hybrid import hybrid_property

# set module level logger
logger = logging.getLogger(__name__)


class ROCrate(Resource):

    id = db.Column(db.Integer, db.ForeignKey(Resource.id), primary_key=True)
    hosting_service_id = db.Column(db.Integer, db.ForeignKey("resource.id"), nullable=True)
    hosting_service = db.relationship("Resource", uselist=False,
                                      backref=db.backref("ro_crates", cascade="all, delete-orphan"),
                                      foreign_keys=[hosting_service_id])
    _metadata = db.Column("metadata", JSON, nullable=True)
    _test_metadata = None
    _local_path = None
    _metadata_loaded = False

    __mapper_args__ = {
        'polymorphic_identity': 'ro_crate',
        "inherit_condition": id == Resource.id
    }

    def __init__(self, uri, uuid=None, name=None,
                 version=None, hosting_service=None) -> None:
        super().__init__(uri, uuid=uuid, name=name, version=version)
        self.hosting_service = hosting_service
        self._crate_helper = None

    @hybrid_property
    def crate_metadata(self):
        if not self._metadata_loaded:
            self.load_metadata()
        return self._metadata

    @property
    def dataset_name(self):
        if not self._metadata_loaded:
            self.load_metadata()
        if not self._crate_helper:
            raise RuntimeError("ROCrate not correctly loaded")
        return self._crate_helper.name

    @property
    def test_metadata(self):
        if not self._metadata_loaded:
            self.load_metadata()
        return self._test_metadata

    def _get_authorizations(self):
        authorizations = self.authorizations.copy()
        authorizations.append(None)
        return authorizations

    def load_metadata(self):
        errors = []
        # try either with authorization hedaer and without authorization
        for authorization in self._get_authorizations():
            try:
                auth_header = authorization.as_http_header() if authorization else None
                logger.debug(auth_header)
                self._crate_helper, self._metadata, self._test_metadata = \
                    self.load_metadata_files(self.uri, authorization_header=auth_header)
                self._metadata_loaded = True
                return self._metadata, self._test_metadata
            except Exception as e:
                errors.append(e)

        if len([e for e in errors if isinstance(e, lm_exceptions.NotAuthorizedException)]) == len(errors):
            raise lm_exceptions.NotAuthorizedException()
        raise lm_exceptions.LifeMonitorException("ROCrate download error", errors=errors)

    @staticmethod
    def extract_rocrate(roc_link, target_path=None, authorization_header=None):
        with tempfile.NamedTemporaryFile(dir="/tmp") as archive_path:
            zip_archive = download_url(roc_link, target_path=archive_path.name, authorization=authorization_header)
            logger.debug("ZIP Archive: %s", zip_archive)
            roc_path = target_path or Path(tempfile.mkdtemp(dir="/tmp"))
            logger.info("Extracting RO Crate @ %s", roc_path)
            extract_zip(archive_path, target_path=roc_path.as_posix())
            return roc_path

    @classmethod
    def load_metadata_files(cls, roc_link, authorization_header=None):
        roc_path = cls.extract_rocrate(roc_link, authorization_header=authorization_header)
        try:
            roc_posix_path = roc_path.as_posix()
            logger.debug(os.listdir(roc_posix_path))
            crate = ROCrateHelper(roc_posix_path)
            metadata_path = Path(roc_posix_path) / crate.metadata.id
            with open(metadata_path, "rt") as f:
                metadata = json.load(f)
            # create a new Workflow instance with the loaded metadata
            test_metadata = get_old_format_tests(crate)
            return crate, metadata, test_metadata
        finally:
            shutil.rmtree(roc_path, ignore_errors=True)
