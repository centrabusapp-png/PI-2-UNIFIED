"""Preview-first synthetic tests. No Pi, camera, production key or network."""
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixtures = load('preview_v5_fixtures', ROOT / 'qa/test_pi2_v5_upload.py')
agent = load('preview_v5_test', fixtures.CAMERA / 'v5_upload/preview_v5.py')
wrapper, baseline, transport = fixtures.wrapper, fixtures.baseline, fixtures.transport


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'qa/.results/temp')
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'new-session'
        self.config = dict(device_id='GPS-002', camera_id='CAM-002', secret='a' * 64,
                           backend_url='https://synthetic.invalid')

    def test_hash_pinned_original_wrapper_and_detector_are_unchanged(self):
        self.assertEqual(agent.load_wrapper(fixtures.CAMERA / 'v5_upload/publish_v5.py').PROCESSOR, wrapper.PROCESSOR)
        self.assertEqual(wrapper.verify_baseline(fixtures.CAMERA), fixtures.CAMERA.resolve())
        with self.assertRaises(ValueError): agent.load_wrapper(fixtures.CAMERA / 'fast_reader.py')

    def exercise(self, modes=('accepted',), *, preview_fail=False, observation_fail=False, stale=False, late=False, wrong_path=False):
        events, previews, observations, messages, captures, sleeps = [], [], [], [], [], []
        stamp = datetime.fromtimestamp(time.time() - (12 if stale else .5), timezone.utc)
        class Camera:
            closed = False
            def __enter__(self): return self
            def __exit__(self, *args): self.closed = True
            def capture(self, path, log):
                captures.append(path); path.write_bytes(('snapshot-' + str(len(captures))).encode())
                return {'SensorTimestamp': '123'}
        camera = Camera()
        class Transport:
            make_payload = staticmethod(transport.make_payload)
            def send(self, config, frame):
                events.append(('observation', frame['capture_id'])); observations.append(frame)
                if observation_fail: raise ValueError('SENSITIVE_TEST_DETAIL')
        def send_preview(config, frame):
            events.append(('preview', frame['capture_id'])); previews.append(frame)
            if preview_fail: raise ValueError('SENSITIVE_TEST_DETAIL')
        original_cycle = baseline.run_cycle
        pending = iter(modes)
        def cycle(*args):
            mode = next(pending)
            def detect(image, annotated, log):
                events.append(('detect', str(image)))
                if mode == 'rejected': raise RuntimeError('Not enough good ORB matches. Found 8, need at least 12.')
                raw = {key: dict(angle=90, base=(0,0), tip=(120,0), line_span=120,
                    mask_mode='strict', quality_status='detected', detection_quality='good',
                    **({'pressure': 5.5} if key in ('front','rear') else {'percent': 50})) for key in baseline.GAUGES}
                return raw, dict(quality='good', inliers=30, inlier_ratio=.8, scale=1.), {}
            result = original_cycle(*args, detect_fn=detect)
            if wrong_path and result['status'] == 'accepted':
                saved = baseline.load_state(args[0]); saved['capture_path'] = 'older-unrelated.jpg'; write(args[0], saved)
            return result
        def write(path, value): path.write_text(json.dumps(value), encoding='utf-8')
        wall = iter([stamp.timestamp()+.5, stamp.timestamp()+11]).__next__ if late else time.time
        with patch.object(baseline, 'atomic_json', side_effect=write), patch.object(baseline, 'run_cycle', side_effect=cycle), \
             patch.object(wrapper, 'sensor_timestamp', return_value=stamp), contextlib.redirect_stdout(io.StringIO()):
            try:
                stats = agent.run_session(wrapper, baseline, Transport(), self.config, self.output,
                    cycles=len(modes), camera_factory=lambda: camera, preview_encoder=lambda p: p.read_bytes(),
                    preview_send=send_preview, sleeper=sleeps.append, output_fn=messages.append, wall=wall)
            finally:
                self.assertTrue(camera.closed)
        return stats, events, previews, observations, messages, captures

    def test_preview_precedes_detection_and_matches_the_committed_image_and_epoch(self):
        stats, events, previews, observations, _, _ = self.exercise()
        self.assertEqual(stats, dict(previews=1, observations=1, stopped=False))
        self.assertEqual([e[0] for e in events], ['preview', 'detect', 'observation'])
        raw, detected = previews[0], observations[0]
        for key in ('capture_id', 'captured_at', 'image', 'processor_version', 'session_id', 'sequence'):
            self.assertEqual(raw[key], detected[key])
        self.assertTrue(all(r['quality']=='undetected' and r['value'] is None for r in raw['readings']))
        self.assertTrue(all(r['quality']=='detected' for r in detected['readings']))

    def test_failed_orb_still_publishes_real_previews_and_never_fabricates_values(self):
        stats, events, previews, observations, messages, captures = self.exercise(('rejected',))
        self.assertEqual(stats['previews'], 3); self.assertEqual(observations, [])
        self.assertEqual(len(captures), 3); self.assertFalse(stats['stopped'])
        self.assertTrue(all(r['value'] is None and r['angle_deg'] is None for f in previews for r in f['readings']))
        self.assertTrue(any('NOT_DETECTED' in m for m in messages))

    def test_aiming_at_a_valid_scene_later_automatically_produces_its_own_readings(self):
        stats, _, previews, observations, _, _ = self.exercise(('rejected', 'accepted', 'rejected'))
        self.assertEqual(stats['previews'], 7); self.assertEqual(stats['observations'], 1)
        self.assertEqual(observations[0]['capture_id'], previews[3]['capture_id'])
        self.assertNotEqual(previews[-1]['capture_id'], observations[0]['capture_id'])
        self.assertTrue(all(r['value'] is None for r in previews[-1]['readings']))

    def test_preview_failure_stops_and_redacts_without_repeated_physical_captures(self):
        stats, _, previews, observations, messages, captures = self.exercise(preview_fail=True)
        self.assertTrue(stats['stopped']); self.assertEqual(len(previews), 1)
        self.assertEqual(len(captures), 1); self.assertEqual(observations, [])
        self.assertNotIn('SENSITIVE_TEST_DETAIL', ''.join(messages))
        self.assertTrue(all('SENSITIVE_TEST_DETAIL' not in p.read_text() for p in self.output.rglob('*.log')))

    def test_stale_sensor_timestamp_never_creates_a_new_preview(self):
        stats, _, previews, observations, _, _ = self.exercise(stale=True)
        self.assertTrue(stats['stopped']); self.assertEqual(previews, []); self.assertEqual(observations, [])

    def test_slow_detection_does_not_retimestamp_or_publish_expired_gauge_values(self):
        stats, _, previews, observations, messages, _ = self.exercise(late=True)
        self.assertEqual(len(previews), 1); self.assertEqual(observations, [])
        self.assertTrue(any('NOT_SENT_SOURCE_AGE' in m for m in messages))

    def test_unrelated_retained_state_cannot_be_joined_to_the_new_preview(self):
        with self.assertRaises(ValueError): self.exercise(wrong_path=True)

    def test_observation_failure_does_not_claim_persistence_or_retry_old_images(self):
        stats, _, _, observations, messages, _ = self.exercise(observation_fail=True)
        self.assertTrue(stats['stopped']); self.assertEqual(len(observations), 1)
        self.assertTrue(any('UNCONFIRMED_STOP' in m for m in messages))
        self.assertNotIn('SENSITIVE_TEST_DETAIL', ''.join(messages))

    def test_preview_signature_has_a_separate_purpose_and_refuses_any_numeric_reading(self):
        frame = transport.make_payload(self.config, 'synthetic', 1, b'jpeg', datetime.now(timezone.utc), {})
        body, signature = agent.encode_preview_signed(frame, self.config['secret'])
        self.assertNotEqual(signature, transport.encode_signed(frame, self.config['secret'])[1])
        frame['readings'][0].update(quality='detected', value=50, angle_deg=90, dial_percent=50)
        with self.assertRaises(ValueError): agent.encode_preview_signed(frame, self.config['secret'])

    def test_ephemeral_ack_is_proof_checked_and_never_claimed_as_database_persistence(self):
        frame = transport.make_payload(self.config, 'synthetic', 1, b'jpeg', datetime.now(timezone.utc), {})
        proof = agent.preview_signature(self.config['secret'], f"preview-ack\n{frame['capture_id']}\n{frame['image']['sha256']}".encode())
        reply = dict(ok=True, previewAccepted=True, persisted=False, captureId=frame['capture_id'], proof=proof)
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return json.dumps(reply).encode()
        class Opener:
            def open(inner, request, timeout):
                self.assertEqual(timeout, 3)
                self.assertTrue(request.full_url.endswith('/GPS-002/preview'))
                self.assertNotIn(self.config['secret'], str(request.headers))
                return Response()
        agent.send_preview(self.config, frame, opener=Opener())
        for changed in ({'proof': '0'*64}, {'persisted': True}, {'captureId': 'other:1'}, {'previewAccepted': False}):
            original = dict(reply); reply.update(changed)
            with self.assertRaises(ValueError): agent.send_preview(self.config, frame, opener=Opener())
            reply.clear(); reply.update(original)

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        with self.assertRaises(FileExistsError): agent.run_session(wrapper, None, None, None, self.output)


if __name__ == '__main__':
    unittest.main()
