import argparse
import os
import webbrowser
from threading import Timer


HOST = "127.0.0.1"


def main() -> None:
	parser = argparse.ArgumentParser(description="Launch the GeoBrain dashboard.")
	parser.add_argument("--port", type=int, default=8050)
	parser.add_argument("--debug", action="store_true")
	args = parser.parse_args()

	from geobrain.app.server import create_app

	app = create_app()

	# Open the browser once, after the server has had a moment to start. The
	# WERKZEUG_RUN_MAIN guard keeps the reloader from opening a new tab on
	# every hot reload.
	if not os.environ.get("WERKZEUG_RUN_MAIN"):
		url = f"http://{HOST}:{args.port}"
		Timer(1, lambda: webbrowser.open(url)).start()

	app.run(host=HOST, port=args.port, debug=args.debug)


if __name__ == "__main__":
	main()
