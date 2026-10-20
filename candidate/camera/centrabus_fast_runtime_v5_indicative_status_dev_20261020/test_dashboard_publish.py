"""No camera/network/DB. Payload and optional-hook regression tests."""
import sys
sys.dont_write_bytecode = True
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import dashboard_publish as publish


def readings():
    return {key: dict(status='DETECTED', value=40, angle=90, reference_points=[(140, 0), (40, 100)],
                     condition='NORMAL (PROVISIONAL)', confidence=1) for key in publish.MAPPING}


class PublisherTests(unittest.TestCase):
    def test_six_keys_original_capture_and_no_invented_confidence_or_condition(self):
        stamp = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        payload = publish.make_payload(dict(device_id='GPS-002', camera_id='camera-test'), 'test-session', 1, b'jpeg', stamp, readings())
        self.assertEqual(payload['capture_id'], 'test-session:1')
        self.assertEqual(payload['captured_at'], '2026-10-20T12:00:00.000Z')
        self.assertEqual(len(payload['readings']), 6)
        self.assertEqual(payload['interpretation'], 'unverified')
        self.assertFalse(payload['calibration_verified'])
        self.assertNotIn('confidence', json.dumps(payload))
        self.assertNotIn('PROVISIONAL', json.dumps(payload))

    def test_unreliable_or_missing_results_are_not_zero_or_carried_forward(self):
        source = readings(); source['fuel']['status'] = 'UNCERTAIN'; del source['oil']
        values = publish.observations(source)
        self.assertEqual(values[0]['quality'], 'uncertain')
        self.assertIsNone(values[0]['value'])
        self.assertEqual(values[1]['quality'], 'undetected')
        self.assertIsNone(values[1]['value'])
        source = readings(); source['battery']['value'] = float('nan')
        self.assertIsNone(publish.observations(source)[4]['value'])

    def test_signature_is_domain_separated_and_reproducible(self):
        body, signature = publish.encode_signed({'test': 1}, 'a'*64)
        self.assertEqual(body, b'{"test":1}')
        self.assertEqual(len(signature), 64)
        self.assertEqual(signature, publish.encode_signed({'test': 1}, 'a'*64)[1])
        self.assertNotEqual(signature, publish.encode_signed({'test': 2}, 'a'*64)[1])

    def test_config_refuses_nonapproved_http_and_never_uses_gps_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'camera-private.json'
            value = dict(device_id='GPS-002', camera_id='camera-test', secret='a'*64,
                         backend_url='http://192.168.50.10:5000', allow_trusted_lan_http=True)
            path.write_text(json.dumps(value)); path.chmod(0o600)
            self.assertEqual(publish.load_config(path)['device_id'], 'GPS-002')
            for url in ('http://8.8.8.8:5000','http://127.0.0.1:5000','http://user:password@192.168.1.1:5000','http://192.168.1.1:5000/other'):
                value['backend_url'] = url; path.write_text(json.dumps(value))
                with self.assertRaises(ValueError): publish.load_config(path)

    def test_nonblocking_one_pending_frame_drops_backlog_and_closes(self):
        import numpy as np
        started, release = threading.Event(), threading.Event(); sent = []
        def send(config, item):
            sent.append(item['sequence']); started.set(); release.wait(2)
        publisher = publish.Publisher(dict(device_id='GPS-002', camera_id='camera-test'), transport=send)
        try:
            frame = np.zeros((8,8,3), np.uint8)
            publisher.offer(frame, datetime.now(timezone.utc), readings(), 'SensorTimestamp/CLOCK_BOOTTIME')
            self.assertTrue(started.wait(2))
            for _ in range(3): publisher.offer(frame, datetime.now(timezone.utc), readings(), 'SensorTimestamp/CLOCK_BOOTTIME')
            self.assertEqual(publisher.pending.qsize(), 1)
            self.assertEqual(publisher.pending.queue[0]['sequence'], 4)
            release.set()
            deadline = time.monotonic()+2
            while len(sent)<2 and time.monotonic()<deadline: time.sleep(.01)
            self.assertEqual(sent, [1,4])
        finally:
            release.set(); publisher.close()
        self.assertFalse(publisher.thread.is_alive())

    def test_transport_failure_does_not_retry_old_frames_or_open_any_camera(self):
        import numpy as np
        calls = []
        def fail(_config, item): calls.append(item['capture_id']); raise RuntimeError('synthetic-private-detail')
        publisher = publish.Publisher(dict(device_id='GPS-002', camera_id='camera-test'), transport=fail)
        try:
            publisher.offer(np.zeros((8,8,3), np.uint8), datetime.now(timezone.utc), readings(), 'SensorTimestamp/CLOCK_BOOTTIME')
            deadline = time.monotonic()+2
            while publisher.last_result == 'waiting' and time.monotonic()<deadline: time.sleep(.01)
            self.assertEqual(publisher.last_result, 'unavailable'); self.assertEqual(len(calls), 1)
            with self.assertRaises(ValueError): publisher.offer(None, datetime.now(timezone.utc), readings(), 'receipt-time')
        finally: publisher.close()

    def test_existing_monitor_passes_the_identical_frame_results_and_timestamp_without_recapture(self):
        import numpy as np
        import fast_reader as runtime
        frame = np.zeros((1080,1920,3),np.uint8); stamp = datetime.now(timezone.utc)
        class Camera:
            last_metadata = {'timestamp_source': 'SensorTimestamp/CLOCK_BOOTTIME'}
            count = 0
            def capture(self): self.count+=1; return frame,stamp
            def close(self): pass
        camera = Camera(); received=[]
        class Sink:
            def offer(self,*args): received.append(args)
        detection = runtime.unavailable('synthetic no needles')
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime,'annotate',side_effect=RuntimeError('test-no-file')):
            runtime.monitor(camera,Path(directory),detector=lambda _: detection,max_cycles=1,interval=0,
                            output=io.StringIO(),errors=io.StringIO(),publisher=Sink())
        self.assertEqual(camera.count,1); self.assertIs(received[0][0],frame)
        self.assertEqual(received[0][1],stamp); self.assertEqual(set(received[0][2]),set(publish.MAPPING))
        self.assertEqual(received[0][3],'SensorTimestamp/CLOCK_BOOTTIME')


if __name__=='__main__': unittest.main()
