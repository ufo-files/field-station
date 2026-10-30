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
