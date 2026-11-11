import os
import sys

import dash
import diskcache
from dash import Dash, DiskcacheManager

from geobrain.app.layout import build_layout

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".geobrain_cache")


def create_app() -> Dash:
	"""Create and configure the Dash app (layout + callbacks registered)."""
	# macOS: Dash's diskcache background-callback worker is launched via
	# multiprocess.Process, which defaults to *fork* on macOS. Forking the
	# multithreaded Flask dev server trips Apple's Objective-C fork-safety guard
	# ("+[NSNumber initialize] may have been in progress ... Crashing instead"),
	# killing the worker before the callback runs - so e.g. "Load atlas" silently
	# does nothing. The env var can't fix this (libobjc reads it at launch, before
	# Python runs), so switch to *spawn*, which re-execs a clean interpreter and
	# never forks. This is the same start method already used on Windows, where
	# these background callbacks run fine.
	if sys.platform == "darwin":
		import multiprocess

		multiprocess.set_start_method("spawn", force=True)

	cache = diskcache.Cache(_CACHE_DIR)
	background_manager = DiskcacheManager(cache)

	# dash-mantine-components 3 requires React 19; Dash ships it but still
	# defaults to 18 - https://www.dash-mantine-components.com/migration
	dash._dash_renderer._set_react_version("19.2.4")

	app = Dash(
		__name__,
		assets_folder=ASSETS_DIR,
		background_callback_manager=background_manager,
		title="geobrain",
		suppress_callback_exceptions=True,
		update_title=None,
	)

	app.layout = build_layout()

	# Imported for the side effect of registering callbacks against `app`.
	from geobrain.app import callbacks  # noqa: F401

	callbacks.register_callbacks(app)
	return app
