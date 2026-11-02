# Field storage retention

The field SSD uses capacity-based, verified private offload rather than a 48-hour
candidate expiration rule. This policy does not publish recordings or send email.

- Begin offloading at 70% used; continue until usage reaches 60%.
- Keep 100 GiB available for operation. Capture waits or stops at this reserve.
- The central Mac checks every five minutes. It stores full recordings and their
  provenance under `UFO-Media/field-archive`, retaining 200 GiB on that volume.
- Only completed, assembled, acknowledged provisional sessions qualify.
  Manual recordings, human-confirmed events, reviewed videos, email-reviewed
  context, and active analysis jobs stay local.
- Each archive includes a file manifest and SHA-256 checksums. The receiver
  verifies every member and flushes the archive and receipt before requesting
  local eviction. Changed source files or new reviews block eviction.
- Metadata and archive receipts remain local. Expired media is marked in video,
  session, and queue records. Archive restoration is currently an operator task;
  there is no automatic download in the review UI.
- The native recognition writer rotates committed results into approximately
  1 GiB immutable SQLite partitions. Checkpoint state stays in the live database.
  Readers merge local partition history. Recovery handles a crash between
  publishing a partition and removing its live rows, without duplicating frames.
- Recognition partitions can offload only after acknowledgement and when no
  remaining local session or reviewed example needs their time range.
- Existing raw-spool GC still requires analysis acknowledgements and honors
  evidence pins. Its one-hour eligibility interval is not a recording expiration
  policy. The legacy negative-retention job becomes a no-op under this policy.
- If either SSD is absent, the central Mac is offline, checksums fail, or protected
  evidence fills the drive, the system retains data and stops capture at reserve.
  It never spills recording data onto the internal drive.

The scheduled receiver runs in the central user's login session. It requires
that session, the archive volume, and SSH access to the field Mac. An unavailable
receiver cannot cause local deletion. Notification evidence is conservatively
retained; it is not automatically evicted by the session archive worker.

## Deployment and recovery

Field policy: `/Volumes/UFO-Field/retention-policy.json`.
Receiver configuration: `~/field-migration/capacity-receiver.json` on the central Mac.
LaunchAgent: `app.ufo-files.field-capacity-retention` (300-second interval).
Receipts: field SSD `retention/receipts`, central archive directories keyed by
manifest fingerprint. Restore tar archives into a separate staging directory
and verify their manifest before merging any data back into the application.

The November 1, 2026 authorized backlog reset preserved 356 videos, 344 sessions,
3,158 reviewed alerts, models, and human-reviewed training records. The protected
training backup and notification metadata backup are under
`UFO-Media/field-recovery/2026-11-01`, with checksum receipts and deletion plans.
Shared notification evidence and the raw spool remain intact to preserve review
context. Temporary field-side backup archives can be removed after confirming
the central receipts; they are not the only copy.

Validation covers pressure hysteresis, protected recordings, invalid receipts,
archive corruption, newly reviewed evidence, path traversal, complete archive
and eviction flow, recognition rollover, checkpoint recovery, and duplicate
frame rejection. Live camera/HackRF capture has not been enabled or performance
qualified by these tests.
