"""Fail closed when the configured external capture spool is unavailable."""
import os
from pathlib import Path

def require_spool_volume(root):
 name=os.environ.get('CAPTURE_SPOOL_VOLUME')
 if not name:return None
 volume=Path(name);identity=os.environ.get('CAPTURE_SPOOL_VOLUME_ID')
 if not identity or not volume.is_mount() or (volume/'.field-spool-volume').read_text().strip()!=identity:
  raise OSError('Capture spool drive is unavailable')
 if not Path(root).resolve().is_relative_to(volume.resolve()):raise OSError('Capture spool is outside its configured drive')
 return volume
