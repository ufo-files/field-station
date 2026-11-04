# Anomalous evidence and capture priority

Human-reviewed anomalous uploads retain a second, checksum-verified copy on the main Mac's external UFO-Archive SSD, under `anomalous-captures/<IA identifier>/<bundle revision>/`. The mirror copies the precise uploaded file set, including original and annotated videos, reviewed original/annotated stills, and annotation metadata. SHA-256 and byte counts must match before publishing `archive-copy.json` back to the field session.

With `local_anomalous_copy_required` enabled in the field retention policy, both IA upload cleanup and reviewed-media cleanup wait for the matching copy receipt. Private overflow copies of uploaded evidence are retained until that separate copy is verified. Training crops and human labels remain available locally. Negative and explicitly cleared data retain their existing deletion policy.

`field-archive/anomalous_mirror.py --config <config>` runs every 120 seconds through the main Mac's `app.ufo-files.anomalous-mirror` LaunchAgent. Configuration provides an archive volume, its UUID, Python executable, and field SSH helper. It backfills verified uploads and retries failures. Status lives on the archive drive at `anomalous-captures/status.json`. Missing/unverified uploads are not counted as backed up.

Field recording reserve is 80 GiB, with resumption at 90 GiB. Background video preparation requires an additional 20 GiB above the recording reserve. Retired sessions are not requeued by preparation recovery. The camera preview continues if recording must pause.

Temporary capacity offloading to UFO-Media is enabled while legacy retention catches up. This is not permanent retention of all recordings.
