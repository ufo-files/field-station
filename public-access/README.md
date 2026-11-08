# Public read-only entry point

The onion service forwards to loopback port 8093. This proxy serves the existing app from port 8091, including Models and its read-only metrics, training history, and saved test results. Every mutation method is rejected before reaching the app; credentials and private paths are stripped from public JSON. Model testing and training controls are hidden.

Deploy these three runtime files to `/Volumes/UFO-Field/station-runtime/public-access` and restart `app.ufo-files.field.public-web`. Preserve the separately provisioned Tor identity and configuration.

Run `python3 -m unittest discover -s public-access` for route, redaction, and mutation-isolation checks.
