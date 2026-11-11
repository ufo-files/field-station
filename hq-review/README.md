# HQ review role

HQ serves a frame-only review library from the main Mini. Capture and original video remain on the field station. The HQ server stores its SQLite review queue and image cache on an explicitly identified external volume; it refuses to start if that volume is missing.

## Review behavior

- The default view is Machine-only review + Both classifications.
- Review one frame or shift-select a range. The action bar stays fixed in the viewport.
- Saving commits the decision to HQ's durable queue immediately. The frame leaves the machine-only view immediately, and a persistent notice reports decisions awaiting field sync.
- The field station applies decisions through its existing training-review and Archive invalidation paths. Stable request IDs prevent duplicate application after a lost connection.
- Changes made at the field station or by another HQ browser cannot silently overwrite a stale review. Conflicts remain visible under Needs attention until explicitly resolved.
- Cached frames and the HQ web interface work while the field station is offline. A first online sync is required before frames are available.
- If the original object has been deleted at the field station, the queued decision remains at HQ for attention rather than being reported as successfully synced. Its cached images remain protected.

## Storage boundaries

The default cache admits up to 5,000 recent frame objects, prioritizing unreviewed and pending items, with a hard 20 GiB image-file budget. Metadata and the review queue are separate small SQLite records. Only the two frame-image APIs are accepted for background downloads; no video endpoint is allowed. Full-frame context is cached where available.

Images with pending or conflicted decisions cannot be evicted. A full protected cache stops admitting new images rather than exceeding its budget. Other cache images can be reclaimed; this does not delete the authoritative reviewed training frames on the field station. Completed source deletions are reconciled only after a complete snapshot.

## Run

Use Python 3.9 or newer. The service needs no third-party Python packages.

Create a private configuration containing `volume`, `volume_id`, `data`, `field_origin`, `cache_gib`, `max_cached_frames`, `bind`, and `port`. The external volume's `.hq-review-volume` file must match `volume_id`, and `data` must be within that volume. Start with:

```sh
python3 hq-review/server.py --config /path/to/hq-review.json
```

Serve this writable interface on the trusted HQ LAN or tailnet. It is a review role, not a public/onion endpoint. Reviewer names provide attribution, not account authentication.

The field station needs `uap-lab/hq_sync.py` and the `/api/hq/snapshot` and `/api/hq/reviews` routes from the same release. Snapshot metadata supports gzip. Existing mutation-token and same-origin checks protect field writes; HQ has its own token and origin check.

## Validation

```sh
python3 -m unittest discover -s hq-review -p 'test_*.py'
python3 -m unittest discover -s uap-lab -p test_hq_sync.py
```

Tests cover bounded cache eviction, pending-frame protection, offline saves, crash/retry persistence, cross-origin write rejection, stale-browser conflicts, reconnect synchronization, idempotent field application, and video-download exclusion.
