# Anomalous evidence and capture priority

Human-reviewed anomalous uploads retain a second, checksum-verified copy on the main Mac's external UFO-Archive SSD, under `anomalous-captures/<IA identifier>/<bundle revision>/`. The mirror copies the precise uploaded file set, including original and annotated videos, reviewed original/annotated stills, and annotation metadata. SHA-256 and byte counts must match before publishing `archive-copy.json` back to the field session.

With `local_anomalous_copy_required` enabled in the field retention policy, both IA upload cleanup and reviewed-media cleanup wait for the matching copy receipt. Private overflow copies of uploaded evidence are retained until that separate copy is verified. Training crops and human labels remain available locally. Negative and explicitly cleared data retain their existing deletion policy.

`field-archive/anomalous_mirror.py --config <config>` runs every 120 seconds through the main Mac's `app.ufo-files.anomalous-mirror` LaunchAgent. Configuration provides an archive volume, its UUID, Python executable, and field SSH helper. It backfills verified uploads and retries failures. Status lives on the archive drive at `anomalous-captures/status.json`. Missing/unverified uploads are not counted as backed up.

Recording headroom follows the configured capture policy; there is no fixed 100 GB reservation. Retired sessions are not requeued by preparation recovery. The camera preview continues when recording is paused.

The obsolete capacity-offload LaunchAgents on both Macs are disabled. Unreviewed recordings must not be copied indefinitely into private overflow archives. The separate Internet Archive upload and verified anomalous mirror remain enabled.


## Interactive storage

The field deployment keeps reviewed crops, labels, and review history on the external UFO-SWR SSD at `/Volumes/UFO-SWR/review-training`. The existing `uap-lab/email-reviews` path links to this store so training and review consumers share the same authoritative data. The November 4 cutover retained the original directory as a backup and recorded verification receipts under `/Volumes/UFO-SWR/review-migration`.

`XDG_RUNTIME_DIR` points to `/Volumes/UFO-SWR/station-runtime`: preview frames and the disposable review-library cache no longer compete with recording storage. Cache persistence does not hold the interactive library lock. Review responses still reconcile current human labels and clear-backlog cutoffs against the authoritative records.

Set `FAST_STORAGE_VOLUME` and `FAST_STORAGE_VOLUME_ID` to the mounted fast SSD and the contents of its `.field-station-fast-volume` identity marker. The lab, capture, and native service runners wait for this verified volume before starting. Do not replace unavailable external storage with a directory on the internal drive.

`CAPTURE_SESSION_INDEX` points to a SQLite index on the fast SSD. Recording manifest writes maintain the generation-to-session mapping before publication. Review saves inspect only matching recording sessions; archive decisions still use authoritative manifests. Missing, uninitialized, or invalid indexes fall back to discovery. Build the initial index with `session_catalog.rebuild(capture_volume)` while recordings are paused. External restoration or editing of recording manifests must mark `session-catalog-invalid` in the capture volume and rebuild the index before removing that marker.
