"""Stage an exact public bundle under this Pi user's cache.

No credential/env/queue/image content is included in the incoming bundle.
This source is compressed on a short SSH command line. Public files arrive on
stdin; the subsequent foreground SSH session retains normal interactive stdin.
"""
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import zlib

NAMES = {'system_run.py'} | {'camera/' + name for name in (
    'publish_v5.py', 'dashboard_publish.py', 'README.md', 'preview_v5.py', 'live_memory.py',
    'memory_reader.py', 'run_memory_session.sh', 'run_memory_trial.sh', 'SHA256SUMS')}
GPS_NAMES = {'system_run.py'}


def unpack(encoded, digest):
    packed = base64.b64decode(encoded, validate=True)
    if len(packed) > 100000 or hashlib.sha256(packed).hexdigest() != digest:
        raise ValueError('Invalid public bundle digest/size')
    inflater = zlib.decompressobj()
    raw = inflater.decompress(packed, 300001)
    if len(raw) > 300000 or not inflater.eof or inflater.unused_data:
        raise ValueError('Invalid public bundle compression')
    files = json.loads(raw)
    if not isinstance(files, dict) or set(files) not in (NAMES, GPS_NAMES):
        raise ValueError('Invalid public bundle paths')
    if any(not isinstance(value, str) for value in files.values()):
        raise ValueError('Invalid public source content')
    return {name: value.encode('utf-8') for name, value in files.items()}


def private_directory(directory):
    if not directory.exists():
        directory.mkdir(mode=0o700)
    info = directory.lstat()
    if directory.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('Unsafe public staging directory')


def stage_bundle(files, digest, account_home):
    with_camera = set(files) == NAMES
    cache = account_home / '.cache'
    private_directory(cache)
    parent = cache / 'centrabus-one-start'
    private_directory(parent)
    destination = parent / digest
    if destination.exists() or destination.is_symlink():
        private_directory(destination)
        camera = destination / 'camera'
        if with_camera and (camera.is_symlink() or not camera.is_dir()):
            raise ValueError('Unsafe public camera staging directory')
        for name, content in files.items():
            source = destination / name
            info = source.lstat()
            if source.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or source.read_bytes() != content:
                raise ValueError('Existing public stage differs; nothing overwritten')
        return destination
    temporary = Path(tempfile.mkdtemp(prefix='.preparing-', dir=parent))
    try:
        if with_camera:
            (temporary / 'camera').mkdir(mode=0o700)
        for name, content in files.items():
            fd = os.open(temporary / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
        # A per-device foreground session lock prevents duplicate runtime owners.
        temporary.rename(destination)
    finally:
        if temporary.exists():
            # Only our freshly created fixed allowlist, never any existing stage.
            for name in files:
                item = temporary / name
                if item.is_file() and not item.is_symlink():
                    item.unlink()
            if with_camera:
                (temporary / 'camera').rmdir()
            temporary.rmdir()
    return destination


def main():
    try:
        if len(sys.argv) != 2 or getpass.getuser() != 'centrabus' or socket.gethostname().split('.')[0] != 'centrabus-pi':
            raise ValueError('Wrong Pi/account or invocation')
        digest = sys.argv[1]
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Invalid public bundle identity')
        encoded = sys.stdin.buffer.read(100001)
        if len(encoded) > 100000:
            raise ValueError('Public input exceeds size limit')
        files = unpack(encoded, digest)
        destination = stage_bundle(files, digest, Path.home())
        print('PI2_PUBLIC_BUNDLE=VERIFIED; private files not transferred', flush=True)
    except Exception:
        print('PI2_SYSTEM_STOP=Public staging/identity check failed; no existing files replaced.', flush=True)
        raise SystemExit(20)


if __name__ == '__main__':
    main()
