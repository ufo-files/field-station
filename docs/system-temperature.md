# Private temperature display

The local header displays the field Mac CPU sensor in Fahrenheit. `/api/system-temperature` returns a cached Celsius reading. Sampling runs in a background thread at most once every 15 seconds, times out after five seconds, and discards readings older than 45 seconds. The public read-only proxy does not allow this endpoint; public pages do not create or poll the display.

The field SSD contains the upstream `vladkens/macmon` v0.10.0 executable at `$XDG_RUNTIME_DIR/tools/macmon-0.10.0/macmon`. `MACMON` can override the executable path. The release tarball SHA-256 is `0ccff60b7bf67bcb9e09cc8f804656a1cafa7eeae7297ee83d10e460ead7d43d`. Source and release: https://github.com/vladkens/macmon/releases/tag/v0.10.0. No root access or temperature history files are needed. Missing or failed sensors display `CPU —`.
