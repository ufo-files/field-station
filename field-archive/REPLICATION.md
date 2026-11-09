# Offline-first field replication

Capture and review writes remain on the field Mini’s external storage. The main Mini pulls completed manual recordings, retained Internet Archive recording bundles, and published model directories into `UFO-Media/field-replica`. Internet Archive publication is independent: neither destination waits for the other. Active recordings are excluded.

`field_replica.py --config <path>` validates the destination volume UUID, permits one worker, resumes partial transfers with rsync, and verifies changed files with SHA-256 on both machines. A durable per-directory receipt records source signatures and checksums. Disconnects leave field originals untouched and retry on the next scheduled pass. Later annotations and metadata changes are copied on subsequent passes.

The deployed `app.ufo-files.field-replica` LaunchAgent runs at login and every 120 seconds. Status and receipts live on the destination external drive; logs live on UFO-Work. The worker never deletes field files or destination files. Replication receipts are not authorization to delete manual recordings. Capacity eviction is a separate policy and is not enabled by this worker.

Configuration keys: `volume`, `uuid`, `python`, `ssh_helper`, `credentials`, `askpass`, `rsync`, `publication_receipts`. Credentials are read only to construct the SSH connection and are never included in status or receipts.
