import logging
from flask import Blueprint
from flask.cli import with_appcontext
from lifemonitor.auth.models import User

# set module level logger
logger = logging.getLogger(__name__)

# define the blueprint for DB commands
blueprint = Blueprint('db', __name__)


@blueprint.cli.command('init')
@with_appcontext
def db_init():
    """
    Initialize the DB
    """
    from lifemonitor.db import db
    logger.debug("Initializing DB...")
    db.create_all()
    logger.info("DB initialized")
    # create a default admin user
    admin = User("admin")
    admin.password = "admin"
    db.session.add(admin)
    db.session.commit()