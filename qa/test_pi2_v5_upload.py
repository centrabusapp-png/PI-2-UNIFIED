"""Synthetic original-V5 adapter tests; no camera/network/private credentials."""
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
CAMERA = ROOT/'candidate/camera'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wrapper = load('v5_wrapper_test', CAMERA/'v5_upload/publish_v5.py')
transport = wrapper.load_transport(CAMERA/'centrabus_fast_runtime_v5_indicative_status_dev_20261020/dashboard_publish.py')
with patch.dict(sys.modules, {'fcntl': types.ModuleType('fcntl')}):
    baseline = load('v5_original_test', CAMERA/'fast_reader.py')


def observations():
    return {key: dict(status='ok', value=5.5 if key in ('front', 'rear') else 50,
        unit=None if key in ('front', 'rear') else '%', angle=90,
        quality_status='detected', detection_quality='good', check_image=False)
        for key in baseline.GAUGES}


class V5UploadTests(unittest.TestCase):
    def setUp(self):
        temporary = ROOT/'qa/.results/temp'
        temporary.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temporary)
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)/'new-trial'
        self.config = dict(device_id='GPS-002',camera_id='CAM-002',secret='a'*64)

    def test_all_baseline_hashes_and_transport_match_without_modifying_detector(self):
        self.assertEqual(wrapper.verify_baseline(CAMERA), CAMERA.resolve())
        self.assertEqual(hashlib.sha256((CAMERA/'fast_reader.py').read_bytes()).hexdigest(),
                         '3754055ca2bb61b90cd93d416914f022ab95c790e13a81f72011be95d1ce79a2')

    def test_changed_or_missing_runtime_fails_closed_before_camera_import(self):
        with self.assertRaises(ValueError): wrapper.verify_baseline(Path(self.temp.name))
        with self.assertRaises(ValueError): wrapper.load_transport(CAMERA/'fast_reader.py')

    def test_dependency_preflight_locates_modules_without_importing_camera_drivers(self):
        with patch.object(wrapper.importlib.util,'find_spec',return_value=object()) as lookup:
            wrapper.verify_dependencies()
            self.assertEqual([c.args[0] for c in lookup.call_args_list],list(wrapper.DEPENDENCIES))
        with patch.object(wrapper.importlib.util,'find_spec',return_value=None):
            with self.assertRaisesRegex(ValueError,'Missing approved camera dependency: cv2'):
                wrapper.verify_dependencies()

    def test_original_sensor_timestamp_is_retained_not_current_time(self):
        wall = 1_800_000_000_000_000_000
        ticks = iter([20_000_000_000,20_000_000_200])
        stamp = wrapper.sensor_timestamp({'SensorTimestamp':'19'+'0'*9},
            boot_clock=lambda:next(ticks),wall_clock=lambda:wall)
        self.assertAlmostEqual(stamp.timestamp(),wall/1e9-1,places=5)
        for metadata in ({}, {'SensorTimestamp':None}, {'SensorTimestamp':True},
                         {'SensorTimestamp':'0'}, {'SensorTimestamp':'not-a-time'},
                         {'SensorTimestamp':'999999999999'}):
            with self.assertRaises(ValueError):
                wrapper.sensor_timestamp(metadata,boot_clock=lambda:20_000_000_000,wall_clock=lambda:wall)

    def test_only_good_detector_quality_is_forwarded_as_detected(self):
        gauges=observations()
        gauges['fuel']['quality_status']='review'
        gauges['oil']['detection_quality']='unknown'
        gauges['battery']['unit']='V'
        payload=wrapper.make_snapshot(transport,self.config,'qa-session',1,b'jpeg',datetime.now(timezone.utc),gauges)
        self.assertEqual(payload['processor_version'],wrapper.PROCESSOR)
        self.assertEqual(len(payload['readings']),6)
        for reading in payload['readings']:
            if reading['gauge_key'] in ('fuel','oilPressure','battery'):
                self.assertEqual(reading['quality'],'uncertain')
                self.assertIsNone(reading['value'])
                self.assertIsNone(reading['angle_deg'])
        self.assertNotIn('confidence',json.dumps(payload))
        self.assertEqual(payload['interpretation'],'unverified')
        self.assertFalse(payload['calibration_verified'])

    def test_pressure_display_uses_original_printed_scale_only(self):
        payload=wrapper.make_snapshot(transport,self.config,'qa-session',1,b'jpeg',datetime.now(timezone.utc),observations())
        reading=next(r for r in payload['readings'] if r['gauge_key']=='frontAir')
        self.assertEqual(reading['value'],5.5)
        self.assertEqual(reading['unit'],'kg/cm2')
        self.assertAlmostEqual(reading['dial_percent'],5.5/15*100,places=5)

    def test_missing_gauge_does_not_create_a_fake_six_key_set(self):
        gauges=observations(); del gauges['oil']
        with self.assertRaises(ValueError): wrapper.normalized_readings(gauges)

    def exercise(self, *, reject=False, stale=False, send_fail=False, accepted_from_wrong_path=False):
        captures=[]; sent=[]; messages=[]
        class FakeCamera:
            closed=False
            def __enter__(self):return self
            def __exit__(self,*args):self.closed=True
            def capture(self,path,log):
                captures.append(path)
                path.write_bytes(b'same-captured-jpeg')
                return {'SensorTimestamp':'123'}
        camera=FakeCamera()
        class FakeTransport:
            make_payload=staticmethod(transport.make_payload)
            def send(self,config,payload):
                sent.append(payload)
                if send_fail:raise ValueError('synthetic-private-detail-must-not-log')
        def detect(image,annotated,log):
            if reject:raise RuntimeError('synthetic detector rejected')
            raw={key:dict(angle=90,base=(0,0),tip=(120,0),line_span=120,
                mask_mode='strict',quality_status='detected',detection_quality='good',
                **({'pressure':5.5} if key in ('front','rear') else {'percent':50}))
                for key in baseline.GAUGES}
            return raw,dict(quality='good',inliers=30,inlier_ratio=.8,scale=1.0),{}
        def cycle(*args):
            result=baseline.run_cycle(*args,detect_fn=detect)
            if accepted_from_wrong_path and result['status']=='accepted':
                state=baseline.load_state(args[0]);state['capture_path']='old-frame.jpg';write(args[0],state)
            return result
        # Mock only POSIX directory fsync in atomic_json; actual unchanged V5
        # capture/detector/quality/accepted-selection control flow executes.
        original_cycle=baseline.run_cycle
        def cycle_with_actual_baseline(*args):
            with patch.object(baseline,'run_cycle',original_cycle):return cycle(*args)
        def write(path,data):path.write_text(json.dumps(data),encoding='utf-8')
        stamp=datetime.fromtimestamp(__import__('time').time()-(30 if stale else 1),timezone.utc)
        with patch.object(baseline,'atomic_json',side_effect=write), \
             patch.object(baseline,'run_cycle',side_effect=cycle_with_actual_baseline), \
             patch.object(wrapper,'sensor_timestamp',return_value=stamp), \
             contextlib.redirect_stdout(io.StringIO()):
            if accepted_from_wrong_path:
                with self.assertRaises(ValueError):
                    wrapper.run_session(baseline,FakeTransport(),self.config,self.output,
                        camera_factory=lambda:camera,preview_encoder=lambda path:path.read_bytes(),output_fn=messages.append)
                count=0
            else:
                count=wrapper.run_session(baseline,FakeTransport(),self.config,self.output,
                    camera_factory=lambda:camera,preview_encoder=lambda path:path.read_bytes(),output_fn=messages.append)
        self.assertTrue(camera.closed)
        return count,captures,sent,messages,stamp

    def test_real_baseline_acceptance_uploads_exactly_one_selected_capture(self):
        count,captures,sent,messages,stamp=self.exercise()
        self.assertEqual(count,1);self.assertEqual(len(captures),1);self.assertEqual(len(sent),1)
        self.assertEqual(sent[0]['image']['sha256'],hashlib.sha256(b'same-captured-jpeg').hexdigest())
        self.assertEqual(sent[0]['captured_at'],stamp.isoformat(timespec='milliseconds').replace('+00:00','Z'))
        self.assertTrue(messages[0].startswith('CAMERA_UPLOAD=ACKNOWLEDGED'))

    def test_rejected_three_attempt_cycle_is_never_uploaded_or_replayed(self):
        count,captures,sent,messages,_=self.exercise(reject=True)
        self.assertEqual(count,0);self.assertEqual(len(captures),3);self.assertEqual(sent,[])
        self.assertEqual(messages,['CAMERA_UPLOAD=NOT_SENT_DETECTION_REJECTED'])

    def test_stale_original_capture_is_not_retimestamped_or_uploaded(self):
        count,_,sent,messages,_=self.exercise(stale=True)
        self.assertEqual(count,0);self.assertEqual(sent,[])
        self.assertEqual(messages,['CAMERA_UPLOAD=NOT_SENT_SOURCE_AGE'])

    def test_saved_path_must_belong_to_this_cycle(self):self.exercise(accepted_from_wrong_path=True)

    def test_network_failure_is_single_bounded_attempt_and_redacted(self):
        count,_,sent,messages,_=self.exercise(send_fail=True)
        self.assertEqual(count,0);self.assertEqual(len(sent),1)
        self.assertEqual(messages,['CAMERA_UPLOAD=UNCONFIRMED_STOP'])

    def test_existing_trial_directory_is_never_overwritten(self):
        self.output.mkdir()
        with self.assertRaises(FileExistsError):wrapper.run_session(None,None,None,self.output)

    def test_preview_is_encoded_from_same_file_not_a_second_camera(self):
        import cv2
        import numpy as np
        image=Path(self.temp.name)/'image.jpg'
        cv2.imwrite(str(image),np.zeros((1080,1920,3),np.uint8))
        preview=wrapper.encode_preview(image)
        self.assertEqual(cv2.imdecode(np.frombuffer(preview,np.uint8),cv2.IMREAD_COLOR).shape,(720,1280,3))


if __name__=='__main__':unittest.main()
