# YouTube camera and RF broadcast

`youtube_broadcast.py` sends a 1280×720, 30 fps constant-bitrate RTMPS feed with the station’s two receive-only RF spectrum plots. It uses the existing local camera preview and RF snapshot; it does not open either HackRF, transmit RF, or expose operator controls.

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

The camera retains only its latest compressed frame in memory. RF graphs and anomalous detection boxes are rendered on a transparent overlay at 5 fps. Detection status is fetched independently from the local app; slow status requests never block camera frames. The encoder never saves camera recordings to the internal disk.

## Continuous operation

`youtube_service.py --config ...` removes all encoder duration limits. It requires `enabled: true` in the private config and uses a lock to prevent duplicate services. The field Mini loads it through `~/Library/LaunchAgents/app.ufo-files.field.youtube.plist`, with RunAtLoad, KeepAlive, and a 10-second restart throttle. Use launchd `ProcessType: Interactive` for real-time video; Background scheduling throttles this workload. The Mini automatically logs into `ufo-field`, which loads the agent after reboot. This depends on the existing macOS automatic-login configuration and mounted field SSD.

The service terminates an encoder that makes no frame progress for 45 seconds; launchd restarts it. It writes status and three rotating logs of at most 1 MB each next to the private config on the external SSD. Stop and unload the agent to stop broadcasting. YouTube event lifecycle is separate: an event explicitly ended in Studio must be replaced before ingest can resume.

## Detection boxes

The YouTube encoder draws fresh anomalous model detections using the same colors and labels as the camera page. Confirmed tracks have solid mint boxes; other model suggestions have dashed yellow boxes. Non-anomalous objects and display-only proposals are excluded. Native display tags require camera timestamp alignment within half a second; inference objects expire after three seconds. All boxes are suppressed during standby. Delayed queued analysis is never presented as a detection on the current live scene.

## Stable ingest bitrate

The composite broadcast uses x264 (`veryfast`, `zerolatency`, two encoder threads) at 4 Mbps with matching minimum/maximum rates and CBR HRD filler. VideoToolbox produced only about 0.55 Mbps on a dark sky even with its constant-bitrate flag, triggering YouTube's ingest warning. The x264 configuration measured 3.94 Mbps over a 12-second private test, approximately 30 fps, no dropped frames, and 0.49 CPU cores averaged for the encoder. Padding does not add visual noise or change the camera image. The original raw `m1_live.py` helper still uses hardware encoding.

## Broadcast branding and RF layout

The top-left watermark uses the user-provided saucer/radio-tower mark from `https://chatgpt.com/s/m_6af1435927fc8191967145745d83a2c7`, retained as `assets/field-station-mark.jpg`. Its original white-on-black pixels supply the compositing mask; only outer preview margins are trimmed. The URL is `UFO-FILES.APP` in SF Rounded Regular. The mark and text adapt to the underlying image and use the standby palette during camera loss. The prior site SVG remains available in the assets directory but is no longer the active watermark.

The broadcast RF panel is 420×204 pixels at 720p, with larger labels, separate footer scale labels, aligned plot edges, and the true-width 1590–1610 MHz context marker. On standby it has a dark backing below the headline so the test pattern cannot obscure the traces. Video is a fixed composition: very small embedded phone playback still benefits from full-screen viewing for detailed scales.
