# Read-only onion access to the existing Field Station

The public entry point serves the deployed app on **8091**, including its existing camera, navigation, labeled training-data gallery, detected-frame queue, metrics, and training reports. It does not contain a replacement interface and never connects to the legacy capture UI on 8090.

Public visitors can inspect current JPEG snapshots and already-saved images. They cannot review, stream, or download recordings, generate video thumbnails, extract frames from videos, run models/training, change labels, or operate the station. Video, byte-range video, original-frame extraction, timeline, recognition-proposal generation, result-file, and review-video routes are absent. All non-GET/HEAD methods return 405 before contacting the app. Unknown routes return 404.

The proxy only forwards an explicit list of read routes to the fixed loopback upstream. Query names and sizes are bounded. JSON responses strip credentials and internal paths, suppress review-video links, and mark original videos unavailable so gallery inspection uses saved crops. Camera initialization uses a minimal read-only state snapshot rather than the administrative video-library function, which can reconcile and write review history. The credential endpoint returns no token.

The small public CSS/JS additions mark access as read-only and hide editing/video affordances while preserving the current app's layout. Server enforcement remains authoritative even if a visitor disables or modifies JavaScript. Browsing the camera, labeled objects, detected frames, metrics, and training pages produces no video requests.

## Deployment

Place this directory at `/Volumes/UFO-Field/station-runtime/public-access` and run its `install.py` using `/Users/ufo-field/ufo-field/venv/bin/python`. The installer uses the already-provisioned Tor service and identity in `~/Library/Application Support/ufo-field-onion`, replaces only the public HTTP entry point, and retires the rejected standalone dashboard's exporter/LaunchAgent. The private 8091 app and capture/analysis services are unchanged.

The public worker binds loopback 8093. The existing Tor v3 service maps port 80 to that listener and uses Snowflake because direct relay connections time out. Preserve the private onion keys to retain the address; never commit them. The Tor setup follows https://community.torproject.org/onion-services/setup/ and https://support.torproject.org/little-t-tor/circumvention/using-bridges/.

`app.ufo-files.field.public-web` and `app.ufo-files.field.public-tor` restart at field-user login and after process failure. Logs are in `~/Library/Logs/field-station/public-{web,tor}.{log,error.log}`. The expected SSD UUID is checked on startup and the mounted device is checked on every request. Stop public access with `launchctl bootout gui/$(id -u)/app.ufo-files.field.public-tor`; this does not stop capture or the private app.

## Load bounds

At most 16 public handlers and 3 upstream requests run concurrently. Requests have socket timeouts; public inputs cannot select another upstream. JSON catalog responses are shared for 30 seconds, status for 2 seconds, and camera JPEGs for 1 second. Cached responses have a 16 MiB aggregate budget and a 64-entry limit. No public video processing is possible through this entry point. This is application-level separation under the field user, not an OS sandbox.

## Validation

```
python3 -m unittest discover -s public-access -p 'test_*.py' -v
node --check public-access/public-readonly.js
```

Tests verify original HTML preservation, credential/path removal, mutation rejection before upstream access, forbidden video/range/HEAD and decoding routes, query validation, and non-mutating camera initialization. Browser checks cover the real deployed pages, saved-image inspection, desktop/mobile layout, hidden write controls, and absence of video requests. Tor verification checks that the app responds 200 and a real video URL with a Range header responds 404.
