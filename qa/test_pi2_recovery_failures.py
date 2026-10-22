"""Offline regressions for the operator's Oct22 startup logs. NO hardware/network.

Media tests run ONLY extracted function definitions with fake Bash systemctl and
timeout builtins. The camera entrypoint, sudo, fuser and real units never run.
"""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import types
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
CAMERA = ROOT / 'candidate/camera/v5_upload'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


live = load('recovery_camera', CAMERA / 'live_memory.py')
runner = load('recovery_supervisor', ROOT / 'candidate/setup/system_run.py')
CONFIG = {'backend_url': 'http://192.168.254.107:5000'}
READY = dict(ready=True, cameraLiveMemoryEnabled=True, cameraFramesEnabled=True,
             gpsPersistenceEnabled=True, localFullSystem=True, simulation=False)


def reply(data=None, raw=None):
    response = Mock(status=200)
    response.read.return_value = raw if raw is not None else json.dumps(data or READY).encode()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    return response


class BackendTests(unittest.TestCase):
    def test_new_origin_is_used_even_when_old_private_config_origin_was_different(self):
        opener = Mock()
        opener.open.return_value = reply()
        updated = live.session_config(dict(CONFIG, allow_trusted_lan_http=True), 'http://192.168.0.174:5000')
        live.camera_backend_ready(updated, True, opener)
        opener.open.assert_called_once_with('http://192.168.0.174:5000/readyz', timeout=3)
        self.assertEqual(CONFIG['backend_url'], 'http://192.168.254.107:5000')

    def test_short_readiness_outage_recovers_instead_of_requesting_backend_restart(self):
        opener, output, sleep = Mock(), [], Mock()
        opener.open.side_effect = [URLError('fixture'), TimeoutError(), reply()]
        live.wait_camera_backend(CONFIG, True, opener=opener, sleep=sleep, emit=output.append)
        self.assertEqual(opener.open.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertIn('RAM_CAMERA_BACKEND_READY=PASS', output[-1])

    def test_bounded_network_failure_is_retryable_but_no_response_details_leak(self):
        opener = Mock()
        opener.open.side_effect = URLError('fixture-private-body-must-never-appear')
        with self.assertRaises(live.BackendReadinessError) as caught:
            live.wait_camera_backend(CONFIG, True, opener=opener, sleep=lambda _: None, emit=lambda _: None)
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(str(caught.exception), 'NETWORK_UNREACHABLE')
        self.assertEqual(opener.open.call_count, 4)

    def test_disabled_wrong_mode_invalid_report_and_unauthorized_are_not_retried(self):
        cases = [reply(dict(READY, gpsPersistenceEnabled=False)), reply(dict(READY, cameraFramesEnabled=False)),
                 reply(dict(READY, ready=1)), reply(raw=b'[]'), reply(raw=b'not JSON'), reply(raw=b' ' * 8193),
                 HTTPError('http://fixture', 401, 'private-fixture', None, None),
                 HTTPError('http://fixture', 302, 'fixture redirect', None, None)]
        for response in cases:
            with self.subTest(response=type(response).__name__):
                opener = Mock()
                opener.open.side_effect = [response]
                with self.assertRaises(live.BackendReadinessError) as caught:
                    live.wait_camera_backend(CONFIG, True, opener=opener, sleep=lambda _: self.fail('unexpected retry'))
                self.assertFalse(caught.exception.retryable)
                self.assertEqual(opener.open.call_count, 1)

    def test_503_is_retried_but_full_and_camera_only_contracts_still_differ(self):
        opener = Mock()
        opener.open.side_effect = [HTTPError('http://fixture', 503, 'fixture', None, None), reply()]
        live.wait_camera_backend(CONFIG, True, opener=opener, sleep=lambda _: None, emit=lambda _: None)
        opener.open.return_value = reply(dict(READY, gpsPersistenceEnabled=False))
        opener.open.side_effect = None
        live.camera_backend_ready(CONFIG, False, opener)
        with self.assertRaises(live.BackendReadinessError):
            live.camera_backend_ready(CONFIG, True, opener)

    def test_initial_gps_network_failure_requests_rediscovery_but_bad_mode_does_not(self):
        for failure in (URLError('fixture'), OSError('fixture'), HTTPError('fixture', 503, '', None, None)):
            with self.assertRaises(runner.NetworkLost):
                runner.check_initial_backend(types.SimpleNamespace(check_backend=Mock(side_effect=failure)), CONFIG['backend_url'])
        with self.assertRaises(runner.SessionError) as caught:
            runner.check_initial_backend(types.SimpleNamespace(check_backend=Mock(side_effect=HTTPError('fixture', 401, '', None, None))), CONFIG['backend_url'])
        self.assertNotIsInstance(caught.exception, runner.NetworkLost)


class Child:
    def __init__(self, code=None, output=''):
        self.code, self.signals = code, []
        self.stdout = io.StringIO(output)

    def poll(self):
        return self.code

    def send_signal(self, value):
        self.signals.append(value)
        self.code = 0

    def wait(self, timeout):
        return self.code


class TickStop:
    def __init__(self, limit=12):
        self.tick, self.limit = 0, limit

    def wait(self, seconds):
        self.tick += 1
        return self.is_set()

    def is_set(self):
        return self.tick >= self.limit


class SupervisorTests(unittest.TestCase):
    def run_session(self, camera_factory=None, blocked=None, limit=12):
        stopped, gps, calls = TickStop(limit), Child(), []
        helper = types.SimpleNamespace(GPS=Path('/fixture/gps'), check_services=lambda: None,
                                       check_queue=lambda _: None, check_backend=lambda _: None)
        def spawn(command, **options):
            calls.append((command, options, stopped.tick))
            return camera_factory() if command[0] == 'bash' else gps
        output = io.StringIO()
        with patch.object(runner.subprocess, 'Popen', side_effect=spawn), patch.object(runner, 'watch_backend'), \
                patch.object(runner.time, 'monotonic', side_effect=lambda: stopped.tick * 2), redirect_stdout(output):
            result = runner.run_children(helper, {'python': '/usr/bin/python3', 'queue': '/existing/queue.sqlite3'},
                                         {}, CAMERA, CONFIG['backend_url'], stopped, 17, camera_blocked=blocked)
        return result, gps, calls, output.getvalue(), stopped

    def test_media_baseline_stop_no_longer_closes_working_gps_and_is_not_blindly_retried(self):
        result, gps, calls, output, stopped = self.run_session(lambda: Child(20, 'CAMERA_STOP=MEDIA_STATE_UNSAFE\n'))
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(stopped.tick, stopped.limit)
        self.assertEqual(gps.signals, [signal.SIGINT])  # Only final operator stop.
        self.assertIn('PI2_CAMERA=BLOCKED;', output)
        self.assertNotIn('PI2_SYSTEM_STOP=', output)

    def test_temporary_camera_backend_failure_retries_without_duplicate_gps_or_camera(self):
        cameras = [Child(75, 'CAMERA_STOP=NETWORK_UNREACHABLE\n'), Child(None, 'RAM_CAMERA=OPEN; FIXTURE\n')]
        result, gps, calls, output, _ = self.run_session(lambda: cameras.pop(0))
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sum(command[0] != 'bash' for command, _, _ in calls), 1)
        self.assertGreater(calls[2][2], calls[1][2])
        self.assertIn('PI2_CAMERA=RETRYING;', output)
        for command, _, _ in calls[1:]:
            self.assertIn(CONFIG['backend_url'], command)
        self.assertEqual(gps.signals, [signal.SIGINT])

    def test_camera_preflight_block_starts_only_the_single_gps_sender(self):
        result, _, calls, output, _ = self.run_session(blocked='CAMERA_PREFLIGHT_REJECTED')
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn('PI2_CAMERA=BLOCKED; REASON=CAMERA_PREFLIGHT_REJECTED;', output)

    def test_camera_spawn_failure_does_not_end_the_working_gps_session(self):
        def fail_camera():
            raise OSError('private fixture detail must not leak')
        result, _, calls, output, stopped = self.run_session(fail_camera)
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(stopped.tick, stopped.limit)
        self.assertIn('REASON=CAMERA_START_UNAVAILABLE', output)
        self.assertNotIn('private fixture', output)

    def test_restore_failure_is_never_auto_retried(self):
        with self.assertRaisesRegex(runner.SessionError, 'restoration needs review'):
            self.run_session(lambda: Child(75, 'MEDIA_RESTORE=STOP_REVIEW\n'))


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
        if not cls.bash or not Path(cls.bash).is_file():
            raise unittest.SkipTest('Bash unavailable; no system service command is run')
        source = (CAMERA / 'run_memory_trial.sh').read_text()
        cls.functions = source.split('# BEGIN MEDIA STATE FUNCTIONS', 1)[1].split('# END MEDIA STATE FUNCTIONS', 1)[0]
        cls.functions = cls.functions.split('\n', 1)[1]
        cls.prefix = '''
media=(wireplumber.service pipewire.service pipewire.socket pipewire-pulse.service pipewire-pulse.socket)
declare -A states loads
for unit in "${media[@]}"; do states[$unit]=inactive; loads[$unit]=loaded; done
changes=()
timeout() { shift 2; "$@"; }
systemctl() {
  [[ $1 == --user ]] || return 90
  local action=$2 unit=$3
  if [[ $action == show ]]; then
    if [[ $* == *--value ]]; then
      [[ $5 != LoadState ]] || { printf '%s\\n' "${loads[$unit]}"; return; }
      [[ $5 != ActiveState ]] || { printf '%s\\n' "${states[$unit]}"; return; }
      return 91
    fi
    printf 'LoadState=%s\\nActiveState=%s\\n' "${loads[$unit]}" "${states[$unit]}"
    [[ ${loads[$unit]} != not-found ]] || return 1
  elif [[ $action == start ]]; then
    shift 2
    for unit in "$@"; do changes+=("$unit"); states[$unit]=active; done
  else return 92; fi
}
'''

    def media(self, script):
        env = dict(os.environ, BASH_ENV='', ENV='')
        command = self.prefix + self.functions + '\n' + script
        result = subprocess.run([self.bash, '--noprofile', '--norc', '-s'], input=command,
                                text=True, capture_output=True, env=env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_headless_inactive_media_passes_without_starting_anything(self):
        self.media('snapshot_media || exit 11\nrestore_media_units || exit 12\n((${#changes[@]} == 0)) || exit 13\n')

    def test_mixed_state_restores_only_original_active_units(self):
        self.media('''
states[wireplumber.service]=active
states[pipewire.socket]=active
snapshot_media || exit 11
for unit in "${media_active[@]}"; do states[$unit]=inactive; done
restore_media_units || exit 12
[[ ${changes[*]} == 'wireplumber.service pipewire.socket' ]] || exit 13
[[ ${states[pipewire.service]} == inactive ]] || exit 14
''')

    def test_missing_inactive_unit_is_not_enabled_or_started(self):
        self.media('loads[pipewire-pulse.socket]=not-found\nsnapshot_media || exit 11\nrestore_media_units || exit 12\n')

    def test_failed_masked_transitional_and_missing_report_still_fail_closed(self):
        for setup in ('states[pipewire.service]=failed', 'states[pipewire.service]=activating',
                      'loads[pipewire.service]=masked', 'loads[pipewire.service]=',
                      'loads[pipewire.service]=not-found; states[pipewire.service]=active'):
            with self.subTest(setup=setup):
                output = self.media(setup + '\nif snapshot_media; then exit 11; fi\n((${#changes[@]} == 0)) || exit 12\n')
                reason = 'MEDIA_INSPECTION_FAILED' if setup.endswith('states[pipewire.service]=active') else 'MEDIA_STATE_UNSAFE'
                self.assertIn('CAMERA_STOP=' + reason + '; UNIT=pipewire.service', output)

    def test_external_change_after_password_prompt_is_rejected_before_media_stop(self):
        self.media('snapshot_media || exit 11\nstates[pipewire.service]=active\nif media_unchanged; then exit 12; fi\n')


if __name__ == '__main__':
    unittest.main()
