#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
PYTHON=${PYTHON:-python3}
export PYTHONPATH="$PWD/uap-lab:$PWD/uap-lab/recognition:$PWD/capture-station:$PWD/field-archive"
"$PYTHON" -m unittest discover -s uap-lab/recognition -p 'test_*.py'
"$PYTHON" -m unittest discover -s field-archive -p 'test_*.py'
"$PYTHON" -m unittest discover -s uap-lab -p 'test_review_alignment.py'

"$PYTHON" -m unittest discover -s notifications -p 'test_*.py'
"$PYTHON" -m unittest discover -s uap-lab -p 'test_native_journal.py'

"$PYTHON" -m unittest discover -s uap-lab -p 'test_email_annotations.py'

"$PYTHON" -m unittest discover -s uap-lab -p 'test_spool.py'
PYTHONPATH="$PWD/capture-station:$PYTHONPATH" "$PYTHON" -m unittest discover -s capture-station -p 'test_storage.py'
PYTHONPATH="$PWD/capture-station:$PYTHONPATH" "$PYTHON" -m unittest discover -s capture-station -p 'test_session_status.py'

"$PYTHON" -m unittest discover -s uap-lab/auto_training -p 'test_*.py'

"$PYTHON" -m unittest discover -s uap-lab -p 'test_labeled_frames.py'

"$PYTHON" -m unittest discover -s uap-lab -p 'test_web_frontend.py'

"$PYTHON" -m unittest discover -s uap-lab -p 'test_label_queue.py'
"$PYTHON" -m unittest discover -s uap-lab -p 'test_backlog_control.py'

"$PYTHON" -m unittest discover -s uap-lab -p 'test_direct_label_save.py'
node scripts/test-queue-refresh.cjs
node scripts/test-live-requests.cjs

"$PYTHON" -m unittest discover -s uap-lab -p 'test_no_signal.py'
node uap-lab/test_live_controls.js
node uap-lab/test_metrics_state.js
node uap-lab/test_backlog_status.js

"$PYTHON" -m unittest test_live.ManualSessionTests test_live.PreviewStorageIsolationTests

"$PYTHON" -m unittest discover -s uap-lab -p 'test_detection_library.py'

"$PYTHON" -m unittest discover -s uap-lab -p 'test_retired_data.py'

PYTHONPATH=uap-lab:capture-station "$PYTHON" -m unittest test_review_retention test_daytime_retention

"$PYTHON" -m unittest test_service_runner

PYTHONPATH=capture-station "$PYTHON" -m unittest test_capture_headroom test_internet_archive

"$PYTHON" -m unittest discover -s uap-lab -p test_model_tests.py

"$PYTHON" -m unittest discover -s uap-lab -p test_detection_refresh.py

"$PYTHON" -m unittest discover -s uap-lab -p test_review_archive_invalidation.py

PYTHONPATH="$PWD/capture-station:$PYTHONPATH" "$PYTHON" -m unittest discover -s capture-station -p 'test_capture_pause.py'

node uap-lab/test_models_data.cjs

"$PYTHON" -m unittest discover -s uap-lab -p 'test_object_omission.py'

"$PYTHON" -m unittest discover -s public-access -p "test_*.py"

"$PYTHON" -m unittest discover -s uap-lab -p "test_review_playback.py"

"$PYTHON" -m unittest discover -s uap-lab -p "test_live.py"
PYTHONPATH=uap-lab:capture-station:shared "$PYTHON" -m unittest test_archive_links test_archive_restore

"$PYTHON" -m unittest test_system_temperature

"$PYTHON" -m unittest discover -s uap-lab -p 'test_review_color.py'

"$PYTHON" -m unittest discover -s uap-lab -p 'test_detection_counts.py'

"$PYTHON" -m unittest discover -s shared -p 'test_ce5_history.py'
"$PYTHON" -m unittest discover -s uap-lab -p 'test_ce5_audio.py'

"$PYTHON" -m unittest discover -s uap-lab -p 'test_observation_metrics.py'

"$PYTHON" -m unittest discover -s uap-lab -p 'test_review_filters.py'

"$PYTHON" -m unittest test_rf_transmit test_rf_experiment

"$PYTHON" -m unittest discover -s uap-lab -p "test_native_motion.py"

"$PYTHON" -m unittest discover -s capture-station -p test_youtube_broadcast.py

"$PYTHON" -m unittest discover -s uap-lab -p 'test_manual_recordings.py'

PYTHONPATH="$PWD/capture-station:$PYTHONPATH" "$PYTHON" -m unittest discover -s capture-station -p 'test_manual_archive.py'

PYTHONPATH="$PWD/field-archive:$PYTHONPATH" "$PYTHON" -m unittest discover -s field-archive -p 'test_field_replica.py'

"$PYTHON" -m unittest discover -s uap-lab -p 'test_empty_segment.py'

PYTHONPATH="field-archive:uap-lab:capture-station:${PYTHONPATH:-}" "$PYTHON" -m unittest discover -s field-archive -p 'test_archive_handoff.py'
PYTHONPATH="capture-station:${PYTHONPATH:-}" "$PYTHON" -m unittest discover -s capture-station -p 'test_spool_volume.py'

"$PYTHON" -m unittest discover -s hq-review -p "test_*.py"
"$PYTHON" -m unittest discover -s uap-lab -p test_hq_sync.py
"$PYTHON" -m unittest discover -s hybrid-training -p 'test_*.py'
"$PYTHON" -m unittest discover -s training-backup -p 'test_*.py'

PYTHONPATH="capture-station:${PYTHONPATH:-}" "$PYTHON" -m unittest test_youtube_sessions
