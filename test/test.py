import ConfigParser
import argparse
import json
import os
import sys
import tempfile
import threading
import time
from StringIO import StringIO

from mozlog.structured import structuredlog, reader
from mozlog.structured.handlers import BaseHandler, StreamHandler, StatusHandler
from mozlog.structured.formatters import MachFormatter
from wptrunner import wptcommandline, wptrunner

here = os.path.abspath(os.path.dirname(__file__))

def setup_wptrunner_logging(logger):
    structuredlog.set_default_logger(logger)
    wptrunner.logger = logger
    wptrunner.setup_stdlib_logger()

class ResultHandler(BaseHandler):
    def __init__(self, verbose=False, logger=None):
        self.inner = StreamHandler(sys.stdout, MachFormatter())
        BaseHandler.__init__(self, self.inner)
        self.product = None
        self.verbose = verbose
        self.logger = logger

        self.register_message_handlers("wptrunner-test", {"set-product": self.set_product})

    def set_product(self, product):
        self.product = product

    def __call__(self, data):
        if self.product is not None and data["action"] in ["suite_start", "suite_end"]:
            # Hack: don't count these suite_* events for the purposes of figuring out if
            # events are balanced
            self.logger._state.suite_started = True
            return

        if (not self.verbose and
            (data["action"] == "process_output" or
             data["action"] == "log" and data["level"] not in ["error", "critical"])):
            return

        if "test" in data:
            data = data.copy()
            data["test"] = "%s: %s" % (self.product, data["test"])

        return self.inner(data)

def test_settings():
    return {
        "include": "_test",
        "manifest-update": "",
        "no-capture-stdio": ""
    }

def read_config():
    parser = ConfigParser.ConfigParser()
    parser.read("test.cfg")

    rv = {"general":{},
          "products":{}}

    rv["general"].update(dict(parser.items("general")))

    # This only allows one product per whatever for now
    for product in parser.sections():
        if product != "general":
            rv["products"][product] = dict(parser.items(product))

    return rv

def run_tests(product, kwargs):
    kwargs["test_paths"]["/_test/"] = {"tests_path": os.path.join(here, "testdata"),
                                       "metadata_path": os.path.join(here, "metadata")}

    wptrunner.run_tests(**kwargs)

def settings_to_argv(settings):
    rv = []
    for name, value in settings.iteritems():
        rv.append("--%s" % name)
        if value:
            rv.append(value)
    return rv

def get_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true", default=False,
                        help="verbose log output")
    return parser

def main():
    config = read_config()

    args = get_parser().parse_args()

    logger = structuredlog.StructuredLogger("web-platform-tests")
    logger.add_handler(ResultHandler(logger=logger, verbose=args.verbose))
    setup_wptrunner_logging(logger)

    parser = wptcommandline.create_parser()

    logger.suite_start(tests=[])

    for product, product_settings in config["products"].iteritems():
        settings = test_settings()
        settings.update(config["general"])
        settings.update(product_settings)
        settings["product"] = product

        kwargs = vars(parser.parse_args(settings_to_argv(settings)))
        wptcommandline.check_args(kwargs)

        logger.send_message("wptrunner-test", "set-product", product)

        run_tests(product, kwargs)

    logger.send_message("wptrunner-test", "set-product", None)
    logger.suite_end()

if __name__ == "__main__":
    import pdb, traceback
    try:
        main()
    except Exception:
        print traceback.format_exc()
        pdb.post_mortem()
