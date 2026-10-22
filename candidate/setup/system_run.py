"""Pi2 foreground GPS/camera session, staged by Start Pi2 System.cmd.

Public code only. Protected configuration is read on the Pi, never copied.
The laptop LAN origin is a process override; existing monitor/queue are reused.
"""
from __future__ import annotations

import argparse
import errno
import getpass
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError

REPOSITORY = Path('/home/centrabus/PI-2-UNIFIED-git')
RUNTIME = Path('/home/centrabus/Desktop/PI-2-UNIFIED-main/candidate/camera')
CAMERA_PRIVATE = Path('/home/centrabus/centrabus-camera-v5-trial-20261020-945b22/camera-private.json')
SENDER_CODE = ("import sys,runpy; p=sys.argv[1]; sys.path.insert(0,p); "
               "sys.argv=[p+'/gps_sender.py']; runpy.run_path(sys.argv[0],run_name='__main__')")
VALIDATE_CODE = ("import sys; sys.path.insert(0,sys.argv[1]); from gps_sender import SenderConfig; "
                 "from telemetry_policy import TelemetryRates; SenderConfig.from_environment(); "
                 "TelemetryRates.from_environment()")


class SessionError(Exception):
    pass


class NetworkLost(SessionError):
    pass


def load_helper(root):
    spec = importlib.util.spec_from_file_location('existing_gps_guide', root / 'candidate/setup/local_run.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.verify_sender_files()
    return helper


def checked_file(helper, filename, account_home, uid, role, private=False):
    try:
        return helper.own_file(filename, account_home, uid, private=private)
    except (OSError, ValueError) as error:
        detail = str(error) if type(error).__name__ == 'SetupError' else 'Existing file is unavailable.'
        raise SessionError(role + ': ' + detail) from None


def check_source_file(helper, filename, account_home, uid):
    """Source-only links may resolve to an owned regular file within this home.

    Keep the configured sender path unchanged: the monitor may atomically replace
    its target. Queue and private-file checks still reject their direct symlinks.
    """
    try:
        source = Path(filename).expanduser()
        if not source.is_absolute():
            raise ValueError('Not an absolute source path')
        target = source.resolve(strict=True)
        helper.own_file(target, account_home, uid)
    except (OSError, ValueError):
        raise SessionError('GPS monitor JSON: configured source must resolve to an existing regular file owned by this account inside its home. Source path: ' + str(filename)) from None


def settings_for_session(helper, root, origin, account_home, uid):
    """Only reuse existing private files, source and queue; no settings writes."""
    saved = root / '.local-run/settings.json'
    settings = json.loads(checked_file(helper, saved, account_home, uid, 'Saved GPS launcher settings', private=True).read_text(encoding='utf-8')) if saved.exists() else {}
    if not settings:
        settings = {'env_files': [str(account_home / 'centrabus-device' / name)
                                  for name in ('runtime.env', 'GPS-002.env')]}
    if not 1 <= len(settings.get('env_files', [])) <= 3:
        raise SessionError('GPS: select the existing private env paths once with run-local.py.')
    try:
        private = helper.private_settings(settings, account_home, uid)
    except (OSError, ValueError) as error:
        detail = str(error) if type(error).__name__ == 'SetupError' else 'Existing private file is unavailable.'
        raise SessionError('GPS private env files: ' + detail) from None
    metadata = json.loads((root / 'candidate/setup/device_settings.json').read_text(encoding='utf-8'))
    settings.update(device_id='GPS-002', backend=helper.local_origin(origin))
    settings.setdefault('gps_json', private.get('CENTRABUS_GPS_JSON_PATH', metadata['reference_gps_json_path']))
    settings.setdefault('queue', private.get('CENTRABUS_GPS_QUEUE_PATH', metadata['reference_queue_path']))
    environment = helper.child_environment(settings, private)
    check_source_file(helper, settings['gps_json'], account_home, uid)
    checked_file(helper, settings['queue'], account_home, uid, 'Existing GPS SQLite queue')
    candidates = [settings.get('python'), str(account_home / 'centrabus-device/.venv/bin/python'), '/usr/bin/python3']
    for name in dict.fromkeys(n for n in candidates if n):
        interpreter = Path(name)
        if not interpreter.is_absolute() or not interpreter.is_file() or not os.access(interpreter, os.X_OK):
            continue
        result = subprocess.run([str(interpreter), '-I', '-B', '-c', VALIDATE_CODE, str(helper.GPS)],
                                env=environment, capture_output=True, timeout=15, check=False)
        if result.returncode == 0:
            settings['python'] = str(interpreter)
            return settings, environment
    raise SessionError('GPS: existing Python interpreters failed sender dependency/config validation. No packages installed. Run the GPS guide to review this environment.')


def services_ready(helper):
    try:
        helper.check_services()
    except helper.SetupError:
        # Whitelisted state metadata gives a useful cause without dumping units/env.
        for unit in ('gpsd.service', 'centrabus-gps-monitor.service', 'centrabus-gps-sender.service'):
            _, value = helper.command(['systemctl', 'show', unit, '-p', 'ActiveState', '--value'])
            state = value if value in ('active', 'inactive', 'failed', 'activating', 'deactivating') else 'unknown'
            print(f'GPS_SERVICE={unit}; STATE={state}', flush=True)
        raise


def verify_camera(directory):
    names = {'publish_v5.py', 'dashboard_publish.py', 'README.md', 'preview_v5.py',
             'live_memory.py', 'memory_reader.py', 'run_memory_session.sh', 'run_memory_trial.sh'}
    seen = set()
    for line in (directory / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1)
        if name not in names or name in seen:
            raise SessionError('Camera bundle manifest is invalid.')
        source = directory / name
        if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise SessionError('Camera bundle verification failed.')
        seen.add(name)
    if seen != names:
        raise SessionError('Camera bundle is incomplete.')


def take_session_lock(stopped, wait_seconds=90):
    lock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    deadline = time.monotonic() + wait_seconds
    announced = False
    while not stopped.is_set():
        try:
            lock.bind('\0centrabus-pi2-one-start-v1')
            return lock
        except OSError as error:
            if error.errno != errno.EADDRINUSE or time.monotonic() >= deadline:
                lock.close()
                raise SessionError('Another Pi2 system session is still running. No duplicate was started.') from None
            if not announced:
                print('PI2_SYSTEM=WAITING_FOR_PREVIOUS_SESSION_CLEANUP', flush=True)
                announced = True
            stopped.wait(1)
    lock.close()
    raise SessionError('Session cancelled.')


def lock_queue(queue_path):
    import fcntl
    descriptor = os.open(queue_path + '.local-session.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode):
            raise SessionError('Unexpected GPS session lock ownership/type.')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def stop_child(child, first_signal, grace):
    if child is None or child.poll() is not None:
        return True
    try:
        child.send_signal(first_signal)
        child.wait(timeout=grace)
        return True
    except subprocess.TimeoutExpired:
        child.kill()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return False
    except OSError:
        return child.poll() is not None


def watch_backend(helper, origin, done, lost, clock=time.monotonic):
    last_ok = clock()
    while not done.wait(3):
        try:
            helper.check_backend(origin)
            last_ok = clock()
        except Exception:
            if clock() - last_ok >= 20:
                lost.set()
                return


def check_initial_backend(helper, origin):
    try:
        helper.check_backend(origin)
    except HTTPError as error:
        code = error.code
        error.close()
        if code in (408, 429, 500, 502, 503, 504):
            raise NetworkLost('Backend temporarily unavailable during startup; rediscovering the current LAN.') from None
        raise SessionError('Backend readiness HTTP request rejected; check the approved laptop mode.') from None
    except (URLError, OSError, TimeoutError, http.client.HTTPException):
        raise NetworkLost('Backend network unavailable during startup; rediscovering the current LAN.') from None


def run_children(helper, settings, environment, camera_directory, origin, stopped, queue_descriptor,
                 gps_only=False, camera_blocked=None):
    gps = camera = None
    opened = threading.Event()
    watchdog_done = threading.Event()
    backend_lost = threading.Event()
    watchdog = None
    restoration_failed = threading.Event()
    reader = None
    result = 0
    retry_at = None
    retry_count = 0

    def announce_camera(state, reason='NONE'):
        print(f'PI2_CAMERA={state}; REASON={reason}; GPS_SENDER=RUNNING', flush=True)

    def start_camera():
        nonlocal camera_blocked
        opened.clear()
        try:
            child = subprocess.Popen(['bash', str(camera_directory / 'run_memory_session.sh'),
                                      '--approve-memory-preview', '--approve-gps-camera-mode', '--backend-url', origin],
                                     cwd=camera_directory, stdout=subprocess.PIPE, text=True, bufsize=1)
        except OSError:
            camera_blocked = 'CAMERA_START_UNAVAILABLE'
            announce_camera('BLOCKED', camera_blocked)
            return None, None

        def camera_output():
            # Capture this attempt, not the mutable next camera child.
            for line in iter(lambda: child.stdout.readline(20001), ''):
                if len(line) > 20000:
                    print('Camera diagnostic line omitted (size limit).', flush=True)
                    continue
                print(line, end='', flush=True)
                if line.startswith('RAM_CAMERA=OPEN;'):
                    opened.set()
                    announce_camera('OPEN')
                if line.startswith(('MEDIA_RESTORE=STOP_REVIEW', 'GPS_SERVICE_STATE_UNCHANGED=STOP_REVIEW')):
                    restoration_failed.set()
            child.stdout.close()

        thread = threading.Thread(target=camera_output, daemon=True)
        thread.start()
        return child, thread

    try:
        services_ready(helper)
        helper.check_queue(settings['queue'])  # Read-only schema check, same exact database.
        gps = subprocess.Popen([settings['python'], '-I', '-B', '-u', '-c', SENDER_CODE, str(helper.GPS)],
                               cwd=helper.GPS, env=environment, stdin=subprocess.DEVNULL,
                               start_new_session=True, pass_fds=(queue_descriptor,))
        print('GPS_SENDER=STARTED; source capture time and existing queue preserved', flush=True)
        stopped.wait(1)
        if gps.poll() is not None:
            raise SessionError('GPS sender exited during startup; no camera was opened.')
        if stopped.is_set():
            return 0
        print('PI2_SYSTEM=RUNNING; GPS_SENDER=RUNNING; CAMERA=' +
              ('OFF' if gps_only else 'BLOCKED' if camera_blocked else 'STARTING'), flush=True)
        print('GPS location still requires a fresh satellite fix. Images save only on Capture.', flush=True)
        if camera_blocked:
            announce_camera('BLOCKED', camera_blocked)
        elif not gps_only:
            camera, reader = start_camera()

        # A bounded lease also handles an SSH server missing a Wi-Fi disconnect.
        watchdog = threading.Thread(target=watch_backend, args=(helper, origin, watchdog_done, backend_lost), daemon=True)
        watchdog.start()
        deadline = time.monotonic() + 120
        while not stopped.wait(.25):
            if backend_lost.is_set():
                raise NetworkLost('Laptop backend became unreachable; ending old session for reconnection.')
            if gps.poll() is not None:
                raise SessionError('GPS sender stopped; ending this session.')
            if camera is not None and camera.poll() is not None:
                reader.join(timeout=2)
                code = camera.poll()
                if reader.is_alive():
                    camera_blocked = 'OUTPUT_CLEANUP_INCOMPLETE'
                elif restoration_failed.is_set():
                    camera_blocked = 'RESTORATION_REQUIRES_REVIEW'
                elif code == 75:
                    retry_count += 1
                    retry_at = time.monotonic() + min(5 * retry_count, 30)
                    announce_camera('RETRYING', 'TRANSIENT_STARTUP_FAILURE')
                else:
                    camera_blocked = 'CAMERA_CHECK_FAILED_EXIT_' + str(code)
                if camera_blocked:
                    announce_camera('BLOCKED', camera_blocked)
                camera = None
            if retry_at is not None and time.monotonic() >= retry_at:
                retry_at = None
                if not camera_blocked:
                    announce_camera('STARTING')
                    camera, reader = start_camera()
                    deadline = time.monotonic() + 120
            if camera is not None and not camera_blocked and not opened.is_set() and time.monotonic() > deadline:
                # Camera alone can fail: preserve the working sender and lease.
                clean = stop_child(camera, signal.SIGTERM, 45)
                reader.join(timeout=2)
                if clean:
                    camera = None
                else:
                    restoration_failed.set()  # Retain handle for final cleanup.
                camera_blocked = 'CAMERA_STARTUP_TIMEOUT'
                announce_camera('BLOCKED', camera_blocked)
        return result
    finally:
        watchdog_done.set()
        if watchdog is not None:
            watchdog.join(timeout=6)
        # Camera restores its desktop media while the GPS service baseline stays stable.
        camera_clean = stop_child(camera, signal.SIGTERM, 45)
        gps_clean = stop_child(gps, signal.SIGINT, 15)
        if reader is not None:
            reader.join(timeout=2)
        print('PI2_OWNED_PROCESSES_STOPPED=' + ('PASS' if camera_clean and gps_clean else 'STOP_REVIEW'), flush=True)
        if not camera_clean or not gps_clean or restoration_failed.is_set():
            raise SessionError('Owned process cleanup/restoration needs review before restarting.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', action='store_true', required=True)
    parser.add_argument('--backend-url', required=True)
    parser.add_argument('--gps-only', action='store_true', help='Start only GPS; no camera preflight, enrollment or sudo')
    args = parser.parse_args(argv)
    stopped = threading.Event()
    for name in ('SIGINT', 'SIGTERM', 'SIGHUP'):
        signal.signal(getattr(signal, name), lambda *_: stopped.set())
    descriptor = None
    session_lock = None
    try:
        if sys.platform != 'linux' or getpass.getuser() != 'centrabus' or socket.gethostname().split('.')[0] != 'centrabus-pi':
            raise SessionError('Wrong Pi/account. Expected centrabus on centrabus-pi (GPS-002).')
        print('PI2_SYSTEM_REVISION=20261022-media-state-recovery', flush=True)
        session_lock = take_session_lock(stopped)
        helper = load_helper(REPOSITORY)
        settings, environment = settings_for_session(helper, REPOSITORY, args.backend_url, Path.home(), os.getuid())
        origin = settings['backend']
        services_ready(helper)
        check_initial_backend(helper, origin)
        camera_directory = None
        camera_blocked = None
        if not args.gps_only:
            camera_directory = Path(__file__).resolve().parent / 'camera'
            verify_camera(camera_directory)
            try:
                camera_check = subprocess.run(['/usr/bin/python3', '-I', '-B', str(camera_directory / 'live_memory.py'),
                                               '--runtime-dir', str(RUNTIME), '--private-config', str(CAMERA_PRIVATE),
                                               '--backend-url', origin, '--check'], timeout=30, check=False)
                if camera_check.returncode:
                    camera_blocked = 'CAMERA_PREFLIGHT_REJECTED'
            except (OSError, subprocess.TimeoutExpired):
                camera_blocked = 'CAMERA_PREFLIGHT_UNAVAILABLE'
        print('GPS_SOURCE=' + json.dumps(helper.source_status(settings['gps_json'])), flush=True)
        print('PI2_SYSTEM_BACKEND=' + origin + '; address override is session-only', flush=True)
        # Normal terminal prompt; this program never reads/stores the sudo password.
        if not args.gps_only and not camera_blocked and subprocess.run(['sudo', '-v'], check=False).returncode:
            camera_blocked = 'CAMERA_AUTHORIZATION_REQUIRED'
        descriptor = lock_queue(settings['queue'])
        options = dict(gps_only=args.gps_only)
        if camera_blocked:
            options['camera_blocked'] = camera_blocked
        return run_children(helper, settings, environment, camera_directory, origin, stopped, descriptor, **options)
    except Exception as error:
        # Imported guide SetupError is a ValueError with reviewed public messages.
        safe = isinstance(error, SessionError) or (isinstance(error, ValueError) and type(error).__name__ == 'SetupError')
        print('PI2_SYSTEM_STOP=' + (str(error) if safe else 'Preflight/runtime check failed; private details withheld.'), flush=True)
        return 75 if isinstance(error, NetworkLost) else 20
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if session_lock is not None:
            session_lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
