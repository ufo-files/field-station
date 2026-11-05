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

"$PYTHON" -m unittest test_live.ManualSessionTests test_live.PreviewStorageIsolationTests

"$PYTHON" -m unittest discover -s uap-lab -p 'test_detection_library.py'

"$PYTHON" -m unittest discover -s uap-lab -p 'test_retired_data.py'

PYTHONPATH=uap-lab:capture-station "$PYTHON" -m unittest test_review_retention

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
