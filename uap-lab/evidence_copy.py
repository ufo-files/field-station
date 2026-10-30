"""Independent evidence copies, sharing storage blocks only where supported."""
import ctypes
import errno
import os
import shutil
import sys


def _clone(source, destination):
    if sys.platform != 'darwin':
        raise OSError(errno.ENOTSUP, 'Cloning unavailable')
    libc = ctypes.CDLL(None, use_errno=True)
    clone = libc.clonefile
    clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    clone.restype = ctypes.c_int
    if clone(os.fsencode(source), os.fsencode(destination), 0):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def copy_evidence(source, destination):
    """Create a new independent file; never overwrite an existing destination."""
    try:
        _clone(source, destination)
        method = 'clone'
    except OSError as exc:
        if exc.errno not in (errno.EXDEV, errno.ENOTSUP, errno.ENOSYS):
            raise
        with open(source, 'rb') as src, open(destination, 'xb') as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        method = 'copy'
    if method == 'clone':
        with open(destination, 'rb') as dst:
            os.fsync(dst.fileno())
    return method
