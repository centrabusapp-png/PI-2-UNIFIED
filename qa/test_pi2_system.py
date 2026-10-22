"""Offline one-window lifecycle/config tests. No Pi, GPS, camera or HTTP access."""
import base64
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import tempfile
import threading
import types
import unittest
from unittest.mock import patch, Mock
import zlib

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / ''


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load('system_test_runner', PACKAGE / 'candidate/setup/system_run.py')
bootstrap = load('system_test_bootstrap', PACKAGE / 'candidate/setup/system_bootstrap.py')
helper = load('system_test_guide', PACKAGE / 'candidate/setup/local_run.py')
live = load('system_test_camera', PACKAGE / 'candidate/camera/v5_upload/live_memory.py')


class SystemTests(unittest.TestCase):
    def test_camera_current_lan_override_preserves_original_config_and_secret(self):
        original = dict(backend_url='http://192.168.254.105:5000', allow_trusted_lan_http=True, secret='synthetic-fixture')
        updated = live.session_config(original, 'http://192.168.0.174:5000/')
        self.assertEqual(updated['backend_url'], 'http://192.168.0.174:5000')
        self.assertEqual(updated['secret'], original['secret'])
        self.assertEqual(original['backend_url'], 'http://192.168.254.105:5000')
        for url in ('http://127.0.0.1:5000', 'http://8.8.8.8:5000', 'http://192.168.0.174:5000/api',
                    'http://user:pass@192.168.0.174:5000', 'http://192.168.0.174:5000?key=fixture'):
            with self.assertRaises(ValueError):
                live.session_config(original, url)
        with self.assertRaises(ValueError):
            live.session_config(dict(original, allow_trusted_lan_http=False), 'http://192.168.0.174:5000')

    def make_settings(self, directory, age=10):
        account = Path(directory)
        root = account / 'repo'
        (root / 'candidate/setup').mkdir(parents=True)
        device = account / 'centrabus-device'
        device.mkdir()
        source = account / 'latest_gps.json'
        source.write_text('{}')
        queue = device / 'gps_offline_queue.sqlite3'
        queue.write_bytes(b'existing queue fixture -- never migrate')
        runtime = device / 'runtime.env'
        runtime.write_text(f'CENTRABUS_GPS_MAX_AGE_SECONDS={age}\nCENTRABUS_GPS_JSON_PATH=/fixture/latest_gps.json\nCENTRABUS_GPS_QUEUE_PATH=/fixture/gps_offline_queue.sqlite3\n')
        credential = device / 'GPS-002.env'
        credential.write_text('CENTRABUS_DEVICE_ID=GPS-002\nCENTRABUS_DEVICE_SECRET=synthetic-secret-fixture\n')
        for file in (runtime, credential):
            file.chmod(0o600)
        metadata = {'reference_gps_json_path': '/fixture/latest_gps.json', 'reference_queue_path': '/fixture/gps_offline_queue.sqlite3'}
        (root / 'candidate/setup/device_settings.json').write_text(json.dumps(metadata))
        return account, root, runtime, credential, source, queue

    def test_system_python_fallback_uses_existing_queue_and_overrides_only_process_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            account, root, runtime, credential, source, queue = self.make_settings(directory)
            before = {p: p.read_bytes() for p in (runtime, credential, queue)}
            # POSIX path guards are tested with their own tests; use metadata guards here on Windows.
            with patch.object(helper, 'own_file', side_effect=lambda name, *_a, **_k: Path(name)), \
                    patch.object(runner, 'check_source_file'), \
                    patch.object(runner.subprocess, 'run', side_effect=lambda command, **_k: types.SimpleNamespace(returncode=0 if command[0].replace('\\', '/') == '/usr/bin/python3' else 1)) as validate, \
                    patch.object(runner.os, 'access', return_value=True), \
                    patch.object(Path, 'is_absolute', return_value=True), \
                    patch.object(Path, 'is_file', return_value=True):
                settings, environment = runner.settings_for_session(helper, root, 'http://192.168.0.174:5000', account, 0)
            self.assertEqual(settings['python'].replace('\\', '/'), '/usr/bin/python3')
            self.assertEqual(settings['queue'], '/fixture/gps_offline_queue.sqlite3')
            self.assertEqual(settings['gps_json'], '/fixture/latest_gps.json')
            self.assertEqual(environment['CENTRABUS_API_URL'], 'http://192.168.0.174:5000')
            self.assertEqual(environment['CENTRABUS_GPS_MAX_AGE_SECONDS'], '10.0')
            self.assertEqual(environment['CENTRABUS_DEVICE_SECRET'], 'synthetic-secret-fixture')
            self.assertTrue(validate.called)
            self.assertEqual({p: p.read_bytes() for p in before}, before)
            self.assertFalse((root / '.local-run/settings.json').exists())

    def test_unsafe_freshness_stops_before_import_or_sender_start(self):
        with tempfile.TemporaryDirectory() as directory:
            account, root, *_ = self.make_settings(directory, age=60)
            with patch.object(helper, 'own_file', side_effect=lambda name, *_a, **_k: Path(name)), \
                    patch.object(runner.subprocess, 'run') as execute:
                with self.assertRaisesRegex(helper.SetupError, '10-second limit'):
                    runner.settings_for_session(helper, root, 'http://192.168.0.174:5000', account, 0)
            execute.assert_not_called()

    def test_source_link_can_resolve_within_account_home_and_keeps_sender_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            account = Path(directory)
            alias = account / 'latest_gps.json'
            target = account / 'monitor/latest_gps.json'
            target.parent.mkdir()
            target.write_text('{"fixture":true}')
            real_resolve = Path.resolve

            def resolve(item, strict=False):
                return target if item == alias else real_resolve(item, strict=strict)

            with patch.object(Path, 'resolve', autospec=True, side_effect=resolve):
                runner.check_source_file(helper, str(alias), account, target.stat().st_uid)
            self.assertEqual(target.read_text(), '{"fixture":true}')
            self.assertFalse(alias.exists())  # Validator never rewrites/creates the configured source.

    def test_source_link_escaping_home_is_rejected_and_queue_error_names_role(self):
        with tempfile.TemporaryDirectory() as directory:
            account = Path(directory) / 'account'
            account.mkdir()
            alias = account / 'latest_gps.json'
            outside = Path(directory) / 'outside.json'
            outside.write_text('{}')
            real_resolve = Path.resolve

            def resolve(item, strict=False):
                return outside if item == alias else real_resolve(item, strict=strict)

            with patch.object(Path, 'resolve', autospec=True, side_effect=resolve):
                with self.assertRaisesRegex(runner.SessionError, 'GPS monitor JSON:'):
                    runner.check_source_file(helper, str(alias), account, outside.stat().st_uid)
            with self.assertRaisesRegex(runner.SessionError, 'Existing GPS SQLite queue:'):
                runner.checked_file(helper, account / 'missing.sqlite3', account, outside.stat().st_uid, 'Existing GPS SQLite queue')

    def packed(self, files=None):
        content = files or {name: 'public fixture' for name in bootstrap.NAMES}
        packed = zlib.compress(json.dumps(content).encode())
        return base64.b64encode(packed).decode(), hashlib.sha256(packed).hexdigest()

    def test_bootstrap_rejects_tampering_extra_paths_and_decompression_bomb(self):
        encoded, digest = self.packed()
        files = bootstrap.unpack(encoded, digest)
        self.assertEqual(set(files), bootstrap.NAMES)
        with self.assertRaises(ValueError):
            bootstrap.unpack(encoded, '0' * 64)
        data = {name: 'fixture' for name in bootstrap.NAMES}
        data['../runtime.env'] = 'unsafe fixture'
        encoded, digest = self.packed(data)
        with self.assertRaises(ValueError):
            bootstrap.unpack(encoded, digest)
        bomb = zlib.compress(b' ' * 400000)
        with self.assertRaises(ValueError):
            bootstrap.unpack(base64.b64encode(bomb).decode(), hashlib.sha256(bomb).hexdigest())

    def test_staging_is_idempotent_and_refuses_to_overwrite_modified_existing_files(self):
        encoded, digest = self.packed()
        files = bootstrap.unpack(encoded, digest)
        with tempfile.TemporaryDirectory() as directory, patch.object(bootstrap.os, 'getuid', return_value=Path(directory).stat().st_uid, create=True):
            stage = bootstrap.stage_bundle(files, digest, Path(directory))
            self.assertEqual(bootstrap.stage_bundle(files, digest, Path(directory)), stage)
            target = stage / 'system_run.py'
            target.write_text('changed public fixture')
            with self.assertRaises(ValueError):
                bootstrap.stage_bundle(files, digest, Path(directory))
            self.assertEqual(target.read_text(), 'changed public fixture')

    def test_gps_only_stage_has_no_camera_files_and_still_rejects_extra_paths(self):
        encoded, digest = self.packed({'system_run.py': 'public GPS fixture'})
        files = bootstrap.unpack(encoded, digest)
        self.assertEqual(set(files), bootstrap.GPS_NAMES)
        with tempfile.TemporaryDirectory() as directory, patch.object(bootstrap.os, 'getuid', return_value=Path(directory).stat().st_uid, create=True):
            stage = bootstrap.stage_bundle(files, digest, Path(directory))
            self.assertFalse((stage / 'camera').exists())
            self.assertEqual(bootstrap.stage_bundle(files, digest, Path(directory)), stage)
        for extra in ('camera/README.md', '../runtime.env'):
            encoded, digest = self.packed({'system_run.py': 'fixture', extra: 'fixture'})
            with self.assertRaises(ValueError):
                bootstrap.unpack(encoded, digest)

    def test_gps_only_preflight_never_checks_camera_config_enrollment_or_sudo(self):
        fake_helper = types.SimpleNamespace(check_backend=Mock(), source_status=Mock(return_value={'state': 'WAITING_FOR_FRESH_GPS'}))
        settings = {'backend': 'http://192.168.0.174:5000', 'gps_json': '/existing/latest_gps.json', 'queue': '/existing/queue.sqlite3'}
        lock = Mock()
        with patch.object(runner.sys, 'platform', 'linux'), \
                patch.object(runner.getpass, 'getuser', return_value='centrabus'), \
                patch.object(runner.socket, 'gethostname', return_value='centrabus-pi'), \
                patch.object(runner.os, 'getuid', return_value=1000, create=True), \
                patch.object(runner.signal, 'SIGHUP', 1, create=True), \
                patch.object(runner.signal, 'signal'), \
                patch.object(runner, 'take_session_lock', return_value=lock), \
                patch.object(runner, 'load_helper', return_value=fake_helper), \
                patch.object(runner, 'settings_for_session', return_value=(settings, {})), \
                patch.object(runner, 'services_ready'), \
                patch.object(runner, 'lock_queue', return_value=17), \
                patch.object(runner.os, 'close') as close, \
                patch.object(runner, 'verify_camera') as camera, \
                patch.object(runner.subprocess, 'run') as execute, \
                patch.object(runner, 'run_children', return_value=0) as children, redirect_stdout(io.StringIO()):
            result = runner.main(['--start', '--backend-url', settings['backend'], '--gps-only'])
        self.assertEqual(result, 0)
        camera.assert_not_called()
        execute.assert_not_called()
        self.assertIsNone(children.call_args.args[3])
        self.assertEqual(children.call_args.kwargs, {'gps_only': True})
        fake_helper.check_backend.assert_called_once_with(settings['backend'])
        close.assert_called_once_with(17)
        lock.close.assert_called_once()

    def test_gps_only_child_is_single_locked_sender_with_no_camera_and_clean_stop(self):
        class Stopped:
            checks = 0

            def wait(self, _seconds):
                self.checks += 1
                return self.checks >= 3

            def is_set(self):
                return self.checks >= 3

        child = Mock()
        child.poll.return_value = None
        child.wait.return_value = 0
        fake_helper = types.SimpleNamespace(GPS=Path('/fixture/gps'), check_services=lambda: None, check_queue=Mock())
        settings = {'python': '/usr/bin/python3', 'queue': '/existing/queue.sqlite3'}
        output = io.StringIO()
        with patch.object(runner.subprocess, 'Popen', return_value=child) as spawn, \
                patch.object(runner, 'watch_backend'), redirect_stdout(output):
            result = runner.run_children(fake_helper, settings, {}, None, 'http://192.168.0.174:5000', Stopped(), 17, gps_only=True)
        self.assertEqual(result, 0)
        spawn.assert_called_once()
        self.assertEqual(spawn.call_args.args[0][0], '/usr/bin/python3')
        self.assertEqual(spawn.call_args.kwargs['pass_fds'], (17,))
        fake_helper.check_queue.assert_called_once_with(settings['queue'])
        child.send_signal.assert_called_once_with(signal.SIGINT)
        self.assertIn('PI2_SYSTEM=RUNNING; GPS_SENDER=RUNNING; CAMERA=OFF', output.getvalue())
        self.assertIn('PI2_OWNED_PROCESSES_STOPPED=PASS', output.getvalue())

    def test_camera_stops_before_gps_and_lock_is_inherited_to_block_orphan_duplicates(self):
        stopped = threading.Event()
        order, calls = [], []

        class Child:
            def __init__(self, role):
                self.role, self.code = role, None
                self.stdout = io.StringIO('RAM_CAMERA=OPEN; PREVIEW_TARGET_FPS=8\n') if role == 'camera' else None

            def poll(self):
                return self.code

            def send_signal(self, value):
                order.append((self.role, value))
                self.code = 0

            def wait(self, timeout):
                return self.code

        def start(command, **options):
            calls.append((command, options))
            role = 'camera' if command[0] == 'bash' else 'gps'
            if role == 'camera':
                threading.Timer(.05, stopped.set).start()
            return Child(role)

        fake_helper = types.SimpleNamespace(GPS=Path('/fixture/gps'), check_services=lambda: None, check_queue=lambda _p: None, check_backend=lambda _p: None)
        settings = {'python': '/usr/bin/python3', 'queue': '/existing/queue.sqlite3'}
        with patch.object(runner.subprocess, 'Popen', side_effect=start), redirect_stdout(io.StringIO()):
            runner.run_children(fake_helper, settings, {}, Path('/fixture/camera'), 'http://192.168.0.174:5000', stopped, 17)
        self.assertEqual([role for role, _ in order], ['camera', 'gps'])
        self.assertEqual(calls[0][1]['pass_fds'], (17,))
        self.assertTrue(calls[0][1]['start_new_session'])
        self.assertIn('--backend-url', calls[1][0])
        self.assertIn('http://192.168.0.174:5000', calls[1][0])

    def test_backend_outage_lease_expires_without_refreshing_gps_capture_time(self):
        lost = threading.Event()
        done = types.SimpleNamespace(wait=lambda _seconds: False)
        clock = iter([0, 7, 14, 21])
        network = types.SimpleNamespace(check_backend=lambda _origin: (_ for _ in ()).throw(OSError('fixture outage')))
        runner.watch_backend(network, 'http://192.168.0.174:5000', done, lost, clock=lambda: next(clock))
        self.assertTrue(lost.is_set())


if __name__ == '__main__':
    unittest.main()
