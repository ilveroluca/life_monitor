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

import glob
import logging
from importlib import import_module
from os.path import basename, dirname, isfile, join

# set module level logger
logger = logging.getLogger(__name__)


def register_commands(app):
    modules_files = glob.glob(join(dirname(__file__), "*.py"))
    modules = ['{}.{}'.format(__name__, basename(f)[:-3])
               for f in modules_files if isfile(f) and not f.endswith('__init__.py')]
    # Load modules and register their blueprints
    we_had_errors = False
    for m in modules:
        try:
            # Try to load the command module 'm'
            mod = import_module(m)
            try:
                logger.debug("Lookup blueprint on commands.%s", m)
                # Lookup 'blueprint' object
                blueprint = getattr(mod, "blueprint")
                # Register the blueprint object
                app.register_blueprint(blueprint)
                logger.debug("Registered %s commands.", m)
            except AttributeError:
                logger.error("Unable to find the 'blueprint' attribute in module %s", m)
                we_had_errors = True
        except ModuleNotFoundError:
            logger.error("ModuleNotFoundError: Unable to load module %s", m)
            we_had_errors = True
    if we_had_errors:
        logger.error("** There were some errors loading application modules.**")
        logger.error("Some commands may not be available.")
