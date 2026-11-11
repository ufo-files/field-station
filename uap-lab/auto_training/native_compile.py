"""Compile generated Core ML artifacts safely across interrupted training retries."""
import shutil,subprocess,tempfile
from pathlib import Path

def compile_model(compiler,package,destination):
 destination=Path(destination)
 with tempfile.TemporaryDirectory(prefix='.compile-',dir=destination.parent) as temporary:
  staged=Path(temporary)/destination.name
  try:subprocess.run([str(compiler),str(package),str(staged)],check=True,capture_output=True,timeout=300)
  except subprocess.CalledProcessError as exc:
   detail=(exc.stderr or exc.stdout or b'').decode(errors='replace')[-4000:]
   raise RuntimeError('Core ML compilation failed: '+detail) from exc
  if not staged.is_dir():raise RuntimeError('Compiler did not produce a model directory')
  if destination.exists():shutil.rmtree(destination)
  staged.replace(destination)
