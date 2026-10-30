# UFO Files Field Station

Station software for camera capture, RF spectrum collection, native-frame analysis, review, and evidence replication. Imported from the working Apple Silicon station, including the `latency-policy-vectorized-v2` analysis changes.

## Components

| Directory | Responsibility |
| --- | --- |
| `capture-station/` | Camera capture, durable recording spool, review, archive policy |
| `uap-lab/` | Native motion analysis, labeling, temporal models, model publication |
| `uap-lab/recognition/` | Tracking, Core ML crop classification, checkpointing, event ownership |
| `signals/` | HackRF sweep collection, aggregation, spectrum display |
| `field-archive/` | Verified evidence replication and receiving |
| `config/` | Example configuration without credentials or station identifiers |

Published model artifacts and inference examples live in [uap-observation-model](https://github.com/ufo-files/uap-observation-model). Published RF data lives in [signals](https://github.com/ufo-files/signals).

## Apple Silicon setup

Use macOS, Python 3.13, Xcode command-line tools, FFmpeg/FFprobe with AVFoundation and VideoToolbox, and HackRF tools for RF collection. Install these system dependencies before creating the Python environment:

```sh
python3.13 -m venv venv
venv/bin/python -m pip install -r requirements.txt
swiftc uap-lab/recognition/crop_worker.swift -o uap-lab/recognition/crop_worker
swiftc uap-lab/recognition/compile_model.swift -o uap-lab/recognition/compile_model
cp config/environment.example.json environment.json
cp config/services.example.json services.json
cp config/recognition.example.json uap-lab/recognition/config.json
```

Edit the copied configuration: replace all example paths, select the camera device and receiver serials, and set the external volume marker. `CAPTURE_VOLUME_ID` must match the contents of `.field-station-volume` on the mounted capture disk. The runner waits for that exact mounted volume before starting a service. Give the process camera and removable-volume access in macOS.

Recognition needs a separately provisioned compatible Core ML model, its classification policy, and optionally the active temporal model. The example paths deliberately do not point to bundled models. A template-matching model from the publication repo is not interchangeable with the Core ML crop classifier. Compile an available `.mlmodel` with `uap-lab/recognition/compile_model INPUT OUTPUT.mlmodelc`, then set the model, policy, and worker paths in the recognition configuration.

Run a configured role from the repository root:

```sh
venv/bin/python service_runner.py capture
# In separate processes: lab, native, recognition, rf, rf-wide,
# rf-aggregate, spectrum. Configure only the services your station supports.
```

For unattended operation, configure a per-user LaunchAgent for each role with absolute paths to `venv/bin/python`, `service_runner.py`, and the role argument, a repository working directory, `RunAtLoad`, and `KeepAlive`. Keep LaunchAgent files and machine configuration outside Git. Capture UI defaults to port 8090 and lab to 8091; use a trusted private network.

Archive sync additionally requires the station-specific SSH transport helpers in `private/` and a configured receiver. Those credentials and helpers are not bundled; do not enable `archive-sync` until that transport is provisioned. The receiver implementation is `field-archive/archive_receiver.py`. Existing Linux/Pi instructions in component READMEs describe the earlier deployment and are not the Apple Silicon installation procedure.

## Tests

```sh
PYTHON="$PWD/venv/bin/python" sh scripts/test.sh
```

CI runs recognition, evidence-transfer, and review-alignment regression tests and builds the Swift crop worker on macOS. The native decoder parity test is opt-in: set `FIELD_TEST_NATIVE_SEGMENTS` to colon-separated paths of 1080p native recordings (more than 175 total frames). It requires VideoToolbox hardware decoding. Other component tests are included alongside their modules; some need FFmpeg or device-specific fixtures.

## Analysis and data policy

All native frames and motion observations enter tracking. Proposals below the model's minimum native size retain observations but receive no fabricated classifier scores. Vectorized association, batched temporal features, and faster checkpoint serialization reduce latency. Classification suggestions do not establish an anomalous event or scientific qualification.

A two-minute validation on the original station after the startup reset measured 0.6–1.2 seconds of latency, a queue of 0–42 frames, and 14,387 consecutive committed frames. These are deployment measurements, not a throughput guarantee for other cameras or workloads.

Credentials, recordings, databases, runtime logs, training datasets, and machine configuration are excluded from Git. The one-time user-authorized startup backlog deletion is not an automatic deployment step. Preserve analyzed data and reviewed evidence when updating software.

## Source provenance

`docs/imported-source-sha256.json` records the imported source hashes before repository portability and test-fixture changes. The running station remains on its deployed files; this initial publication does not restart services or change capture. Future deployment should record the Git commit alongside the station configuration.

## Email alerts through Apple Mail and Proton Bridge

Add the sender address to Apple Mail through Proton Bridge on the logged-in station user. Run the sender as a user LaunchAgent in that desktop session and allow its macOS Mail automation prompt. Launching Mail from an SSH session can open a read-only instance; the sender needs the configured desktop instance.

Copy `config/email-alerts.example.json` to `notifications/config.json` and set sender, recipient, and outbox. In the private recognition configuration, set `alert_outbox` to the same directory and `alert_not_before_epoch` to the activation Unix timestamp to avoid alerts for old backlog. Add a service role for `venv/bin/python notifications/mail_alerts.py --config notifications/config.json` using absolute paths; the volume-checking `service_runner.py` can run this role like other station services.

The existing classifier threshold determines anomalous candidates (no lowering of the threshold). Each proposed track produces at most one queued alert per capture generation, even after a restart. The message identifies the candidate as model-flagged and unconfirmed, includes detection time, source frame, track, model score, and native object bounds, and attaches exactly one PNG: the native crop used for classification. Unknown and ordinary-object labels do not trigger email. Human review is not required for these candidate alerts; they are separate from the confirmed-anomaly public archive policy.

The outbox is durable. Mail runs in a separate process, so delivery delays do not wait on analysis. Sender configuration failures retry before submission. A timeout or restart during submission leaves an uncertain receipt that requires checking Mail Sent/Outbox before a retry, preventing blind duplicate sends. `accepted_by_mail` means Mail accepted the outgoing message, not independently verified inbox delivery. Health is recorded in `sender-status.json`; per-event results are in `delivery.json`. Keep the outbox outside Git.

## Recovery after abrupt capture shutdown

Before advancing to the next capture generation, the journal verifies the checksum and decodes the final indexed segment to confirm every finalized frame was analyzed. If a reboot left additional delivered frames outside that finalized index, it records the exact unavailable tail in `capture-tail-unavailable.json`, marks the old generation's integrity false, retains partial files, and resumes the next generation. It never counts that tail as analyzed.
