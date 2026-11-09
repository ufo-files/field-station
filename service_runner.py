"""Keep field services on verified storage and bound their shutdown time."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def supervise(args, env=None, grace=10, capture=False):
    stopping = None
    child = None

    def stop(*_):
        nonlocal stopping
        if stopping is None:
            stopping = time.monotonic()
            if child is not None and child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    awake = None
    try:
        child = subprocess.Popen(args, env=env, start_new_session=True)
        if stopping is not None:
            os.killpg(child.pid, signal.SIGTERM)
        if capture:
            awake = subprocess.Popen(['/usr/bin/caffeinate', '-i', '-m', '-w', str(child.pid)])
        while child.poll() is None:
            if stopping is not None and time.monotonic() - stopping >= grace:
                print('Service shutdown timed out; terminating its process group', flush=True)
                os.killpg(child.pid, signal.SIGKILL)
                return child.wait()
            time.sleep(.1)
        return child.returncode
    finally:
        # Also reap descendants if their parent exits before them.
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
        if awake and awake.poll() is None:
            awake.terminate()
            awake.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def storage_ready(env, role):
    required = [(Path(env['CAPTURE_VOLUME']), '.field-station-volume', env['CAPTURE_VOLUME_ID'])]
    if role in ('lab', 'capture', 'native', 'recognition') and env.get('FAST_STORAGE_VOLUME'):
        required.append((Path(env['FAST_STORAGE_VOLUME']), '.field-station-fast-volume', env['FAST_STORAGE_VOLUME_ID']))
    try:
        return all(volume.is_mount() and (volume / marker).read_text().strip() == identity
                   for volume, marker, identity in required)
    except OSError:
        return False


def main():
    root = Path(__file__).resolve().parent
    role = sys.argv[1]
    print('Starting field service', role, 'loading environment', flush=True)
    env = dict(os.environ, **json.loads((root / 'environment.json').read_text()))
    while not storage_ready(env, role):
        print('Waiting for verified field storage', flush=True)
        time.sleep(5)
    args = json.loads((root / 'services.json').read_text())[role]
    return supervise(args, env, capture=role == 'capture')


if __name__ == '__main__':
    sys.exit(main())
