import os
import logging
from typing import List, Type

import dotenv

from .db import db_uri
from .utils import bool_from_string

basedir = os.path.abspath(os.path.dirname(__file__))


# load "settings.conf" to the environment
settings = {}


def load_settings(file_path="settings.conf"):
    result = None
    if os.path.exists(file_path):
        result = dotenv.dotenv_values(dotenv_path=file_path)
        os.environ.update(result)
        settings.update(result)
    return result
        


class BaseConfig:
    CONFIG_NAME = "base"
    USE_MOCK_EQUIVALENCY = False
    DEBUG = bool_from_string(os.getenv("DEBUG", "false"))
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'DEBUG' if DEBUG else 'INFO')
    # Add a random secret (required to enable HTTP sessions)
    SECRET_KEY = os.urandom(24)
    SQLALCHEMY_DATABASE_URI = db_uri()
    # FSADeprecationWarning: SQLALCHEMY_TRACK_MODIFICATIONS adds significant
    # overhead and will be disabled by default in the future.  Set it to True
    # or False to suppress this warning.
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DevelopmentConfig(BaseConfig):
    CONFIG_NAME = "development"
    # Add a random secret (required to enable HTTP sessions)
    SECRET_KEY = os.getenv(
        "DEV_SECRET_KEY", "LifeMonitor Development Secret Key"
    )
    DEBUG = True
    LOG_LEVEL = "DEBUG"
    TESTING = False


class ProductionConfig(BaseConfig):
    CONFIG_NAME = "production"
    SECRET_KEY = os.getenv("PROD_SECRET_KEY", "LifeMonitor Production Secret Key")
    TESTING = False


class TestingConfig(BaseConfig):
    CONFIG_NAME = "testing"
    SECRET_KEY = os.getenv("TEST_SECRET_KEY", "Thanos did nothing wrong")
    DEBUG = True
    TESTING = True
    LOG_LEVEL = "DEBUG"
    SQLALCHEMY_DATABASE_URI = "sqlite:///{0}/app-test.db".format(basedir)


_EXPORT_CONFIGS: List[Type[BaseConfig]] = [
    DevelopmentConfig,
    TestingConfig,
    ProductionConfig,
]
_config_by_name = {cfg.CONFIG_NAME: cfg for cfg in _EXPORT_CONFIGS}


def get_config_by_name(name):
    try:
        config = _config_by_name[name]
        if settings:
            # append properties from settings.conf
            # to the default configuration
            for k, v in settings.items():
                setattr(config, k, v)
        return config
    except KeyError:
        return ProductionConfig


def configure_logging(app):
    level_str = app.config.get('LOG_LEVEL', 'INFO')
    error = False
    try:
        level_value = getattr(logging, level_str)
    except AttributeError:
        level_value = logging.INFO
        error = True

    logging.basicConfig(level=level_value)
    if error:
        app.logger.error("LOG_LEVEL value %s is invalid. Defaulting to INFO", level_str)

    app.logger.info('Logging is active. Log level: %s', logging.getLevelName(app.logger.getEffectiveLevel()))
