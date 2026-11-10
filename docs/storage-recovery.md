# Offline-first field storage and recovery

Capture writes to local external storage first. Main-station replication and Internet Archive publication are independent retryable operations; neither is a prerequisite for recording offline.

## Protected data

Manual recordings are excluded from capacity eviction, negative-review cleanup, and backlog cleanup. Their original media and annotations remain accessible. Manual review reads the protected original directly, so moving its annotation workspace across drives does not require a hard link. Reviewed training frames and labels remain protected.

## Verified main-station handoff

`field_replica.py` runs on the main station. It prioritizes completed manual/reviewed sessions, then published models and automatic overflow archives. Transfers retain partial files and retry interrupted or changed files. Per-file SHA-256 receipts are written only after source and destination verification. There is no rsync deletion propagation.

After an automatic overflow archive is verified on main storage, `archive_handoff.py` verifies the private retrieval endpoint and the cached TAR checksum before releasing that field cache. Manual or unknown-origin sessions are refused. The original source data is not silently converted into a successful transfer after an error.

`archive_bridge.py` is a read-only authenticated server bound to main-station loopback. `archive_tunnel.py` establishes a loopback-only reverse SSH forward from the main station to the field station; run it under launchd with KeepAlive and a reconnect throttle. Credentials remain in private configuration outside Git. The field restore client downloads the indexed original and verifies its exact byte count and SHA-256 before publishing it locally. These endpoints are not exposed through the public/onion app.

## External spool relocation

Set `CAPTURE_SPOOL_VOLUME` and `CAPTURE_SPOOL_VOLUME_ID` only after a verified move. The volume must be mounted, its `.field-spool-volume` marker must match, and the resolved capture root must remain inside it. Missing storage prevents recording writes; constructing the preview buffer remains possible.

If preserving a canonical capture path through a symlink, register that exact relative path in `retention-policy.json` under `storage_aliases`, with `volume`, `target`, and `identity`. Completed capture generations may also be relocated individually and registered as `capture-spool/run-<id>`; the parent spool stays on the original volume. Symlinks below a registered alias and unregistered aliases remain rejected. Verify the entire copy and quiesce writers for final synchronization before changing paths. Never release the old copy based solely on rsync exit status.

## Interrupted capture recovery

A closed, checksum-verified final segment can contain encoded frames after its timestamp journal ended during disk exhaustion. Recognition records these as unavailable timestamps, preserves the original, and continues; it never invents timestamps or counts them as analyzed. Interior gaps and live recordings remain errors. Generation summaries report incomplete integrity and count missing frames once.
