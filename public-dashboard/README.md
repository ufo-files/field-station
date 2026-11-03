# Public field observatory

An independent read-only onion dashboard for the field station. The public viewer exposes camera snapshots, capture/analysis telemetry, scientific-qualification status, RF summaries, retained session/library playback, and saved/annotated stills. User authorization on 2026-11-03 includes public imagery and recordings. Credentials, arbitrary metadata, control endpoints, and control tokens are never exported.

## Data boundary

`dashboard.py export` updates an allowlisted JSON snapshot every 15 seconds and rebuilds the recording/frame catalogs every 60 seconds. It reads status files and two fixed, read-only loopback preview endpoints. Public request paths and query parameters never reach these endpoints. The HTTP worker imports no control application code.

`dashboard.py serve` binds **127.0.0.1:8093**, serving only named static assets, public JSON, the snapshot, and opaque media IDs from a private export map. The map is not publicly routable. Video responses support single byte ranges. All mutation methods are rejected; unknown routes, traversal attempts, symlinks, and missing media return errors. Headers prohibit remote resources, embedding, and form submissions. No visitor request logs are written. Concurrency is bounded to 12 connections with socket timeouts.

Media is read in place, without copying or hardlinking recordings; the existing retention policy remains authoritative. This is application-level separation under the field user, not an OS security sandbox. Do not expose this service with administrative privileges or publish the existing control server through Tor.

Both workers verify the expected SSD UUID at startup and stop serving/writing if the mounted device changes. A stale export is visibly marked in the browser. Capture timestamp freshness does **not** establish camera signal: a capture card can emit fresh “No Signal” frames. Model suggestions and provisional detections are not confirmed anomalies.

## Installation on UFO Field

1. Install Homebrew `tor` and `snowflake`.
2. Place this directory at `/Volumes/UFO-Field/station-runtime/public-dashboard`.
3. Run `/Users/ufo-field/ufo-field/venv/bin/python install.py` as the logged-in field user.
4. Inspect `~/Library/Logs/field-station/public-{export,web,tor}.log` and matching `.error.log` files.
5. Wait for Tor `Bootstrapped 100%`, then verify the onion URL through a Tor SOCKS client.

Three LaunchAgents restart the public exporter, viewer, and Tor at user login and after process failure. They do not restart capture, recognition, lab, or the existing gateway. FileVault/login requirements still apply after a reboot.

Tor's identity lives in `~/Library/Application Support/ufo-field-onion/onion` with private directory permissions, independently of application deployments. Back up this directory securely to preserve the onion address; **never commit or publish its keys**. Only `hostname` is public. Tor's verification SOCKS listener is loopback-only on port 19050. No relay/exit service is enabled.

Direct relay TCP connections timed out on this network, so installation uses the Snowflake bridge configuration documented by the Tor Project:
https://support.torproject.org/little-t-tor/circumvention/using-bridges/

The public identity and service mapping follow:
https://community.torproject.org/onion-services/setup/

## Validation

```
python3 -m unittest discover -s public-dashboard -p 'test_*.py' -v
node --check public-dashboard/static/app.js
```

Boundary tests cover private/control routes, traversal, mutation methods, symlinks, removed media, safe metadata export, byte ranges, HEAD, and security headers. Browser verification covers 1440px desktop and 390px mobile, fresh snapshots, pagination, search, and playback selection.

## Stop / rollback

Run `launchctl bootout gui/$(id -u)/app.ufo-files.field.public-tor`, then repeat for `public-web` and `public-export`. Remove their three LaunchAgent plists if they should not restart at login. Preserve the onion identity directory. Station capture/control services and source media are independent.
