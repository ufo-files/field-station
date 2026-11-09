# YouTube camera and RF broadcast

`youtube_broadcast.py` sends a 1280×720, 30 fps hardware-encoded RTMPS feed with the station’s two receive-only RF spectrum plots. It uses the existing local camera preview and RF snapshot; it does not open either HackRF, transmit RF, or expose operator controls.

The encoder has an independent camera feeder. On startup, a camera outage lasting three seconds, or a recognized Cam Link no-signal slate, it sends the existing alien “WE’LL BE RIGHT BACK” screen. Fresh camera frames automatically restore the picture. RF readings continue on the standby screen; stale receivers are marked reconnecting. Losing the encoder host or its Internet connection cannot be concealed by this local fallback.

## Run

Keep the private JSON configuration on external storage with mode 0600. It contains `publish_url` (an encrypted YouTube ingestion URL including the secret stream key) and `source` (`http://127.0.0.1:8090/preview.mjpeg?fps=30`). Optional fields are `rf_path`, `preview_url`, and `standby_path`. Never commit the configuration or print the stream key.

```sh
# Local encoder validation, no broadcast:
venv/bin/python capture-station/youtube_broadcast.py --config /Volumes/UFO-Field/station-runtime/youtube/encoder.json --validate --seconds 12

# Bounded broadcast, after checking the intended event and visibility in Studio:
venv/bin/python capture-station/youtube_broadcast.py --config /Volumes/UFO-Field/station-runtime/youtube/encoder.json --seconds 120
```

Tests default to 120 seconds, with a maximum duration of one hour per invocation. This helper does not change YouTube event privacy or create an event. Verify those in Studio before starting. Audio is silent. The existing `m1_live.py` raw encoder remains available; use this new helper for the composite feed.

The standby JPEG is a rendered video frame of the app’s existing HTML/CSS and alien art, not replacement website markup. Regenerate it with `node scripts/render-broadcast-standby.cjs` after changing that screen (requires Playwright and Python/Pillow; use `PYTHON` to select the interpreter). Its 4:2:2 JPEG sampling matches the camera preview so a transition does not reset FFmpeg’s filter graph.

The camera retains only its latest compressed frame in memory. RF rendering updates independently twice per second and feeds a cached transparent overlay at 5 fps. The encoder never saves camera recordings to the internal disk.
