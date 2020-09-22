import os
import logging
from typing import List, Type

import dotenv

from .db import db_uri
from .utils import bool_from_string

basedir = os.path.abspath(os.path.dirname(__file__))


def load_settings(file_path="settings.conf"):
    result = None
    if os.path.exists(file_path):
        result = dotenv.dotenv_values(dotenv_path=file_path)
    return result


class BaseConfig:
    CONFIG_NAME = "base"
    USE_MOCK_EQUIVALENCY = False
    DEBUG = bool_from_string(os.getenv("DEBUG", "false"))
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'DEBUG' if DEBUG else 'INFO')
    # Add a random secret (required to enable HTTP sessions)
    SECRET_KEY = os.urandom(24)
    # FSADeprecationWarning: SQLALCHEMY_TRACK_MODIFICATIONS adds significant
    # overhead and will be disabled by default in the future.  Set it to True
    # or False to suppress this warning.
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DevelopmentConfig(BaseConfig):
    CONFIG_NAME = "development"
    # Add a random secret (required to enable HTTP sessions)
    SECRET_KEY = os.getenv("DEV_SECRET_KEY", BaseConfig.SECRET_KEY)
    DEBUG = True
    LOG_LEVEL = "DEBUG"
    TESTING = False


class ProductionConfig(BaseConfig):
    CONFIG_NAME = "production"
    SECRET_KEY = os.getenv("PROD_SECRET_KEY", BaseConfig.SECRET_KEY)
    TESTING = False


class TestingConfig(BaseConfig):
    CONFIG_NAME = "testing"
    SECRET_KEY = os.getenv("TEST_SECRET_KEY", BaseConfig.SECRET_KEY)
    DEBUG = True
    TESTING = True
    LOG_LEVEL = "DEBUG"
    # SQLALCHEMY_DATABASE_URI = "sqlite:///{0}/app-test.db".format(basedir)


_EXPORT_CONFIGS: List[Type[BaseConfig]] = [
    DevelopmentConfig,
    TestingConfig,
    ProductionConfig,
]
_config_by_name = {cfg.CONFIG_NAME: cfg for cfg in _EXPORT_CONFIGS}


def get_config_by_name(name, settings=None):
    try:
        config = type(f"AppConfigInstance{name}".title(), (_config_by_name[name],), {})
        # load "settings.conf" to the environment
        if settings is None:
            settings = load_settings()
        if settings and "SQLALCHEMY_DATABASE_URI" not in settings:
            settings["SQLALCHEMY_DATABASE_URI"] = db_uri(settings)
        # always set the FLASK_APP_CONFIG_FILE variable to the environment
        if "FLASK_APP_CONFIG_FILE" in settings:
            os.environ["FLASK_APP_CONFIG_FILE"] = settings["FLASK_APP_CONFIG_FILE"]
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