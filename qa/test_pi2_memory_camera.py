"""RAM-only local verification; fake Pi/camera/network, no device access."""
import ast
from datetime import datetime, timezone
import importlib.util
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'candidate/camera/v5_upload'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
live=load('ram_test_live',FOLDER/'live_memory.py')
reader=load('ram_test_reader',FOLDER/'memory_reader.py')
fixtures=load('ram_test_original_fixtures',ROOT/'qa/test_pi2_v5_upload.py')

class MemoryTests(unittest.TestCase):
    def test_original_detector_kept_and_partial_publication_has_distinct_processor(self):
        self.assertEqual(live.PROCESSOR, 'centrabus-fast-v5-3754055-routing-v3')
        self.assertNotEqual(live.PROCESSOR, fixtures.wrapper.PROCESSOR)
        source=(FOLDER/'memory_reader.py').read_text()
        self.assertNotIn('pressure_extent',source)
        self.assertNotIn('recovery.attach',source)

    def test_pressure_routing_changes_only_one_mode_predicate_not_numeric_constants(self):
        source=(FOLDER.parent/'gauge_readers.py').read_bytes()
        original=ast.parse(source);updated=reader.pressure_routing_tree(source)
        numbers=lambda tree:[node.value for node in ast.walk(tree) if isinstance(node,ast.Constant)
                             and type(node.value) in (int,float)]
        self.assertEqual(numbers(original),numbers(updated))
        original_function=next(n for n in original.body if isinstance(n,ast.FunctionDef) and n.name=='_v5_pressure')
        updated_function=next(n for n in updated.body if isinstance(n,ast.FunctionDef) and n.name=='_v5_pressure')
        self.assertEqual(ast.dump(ast.Module(body=original_function.body[1:],type_ignores=[])),
                         ast.dump(ast.Module(body=updated_function.body[1:],type_ignores=[])))
        with self.assertRaises(ValueError):reader.pressure_routing_tree(b'pass')

    def test_routed_pressure_reference_passes_original_geometry_without_image_writes(self):
        import cv2
        with patch.dict(sys.modules,{'fcntl':types.ModuleType('fcntl')}), \
             patch.object(cv2,'imwrite',side_effect=AssertionError('No image files')), \
             patch.object(Path,'mkdir',side_effect=AssertionError('No directories')):
            engine=reader.MemoryReader(fixtures.wrapper,FOLDER.parent,partial_quality=True,pressure_routing=True)
            result=engine.analyze(dict(main_jpeg=engine.reader.REFERENCE_IMAGE.read_bytes(),sequence=1))
        self.assertEqual(engine.last_diagnostic['detected'],6)
        self.assertEqual(engine.last_diagnostic['reasons'],[])
        for key in ['front','rear']:
            gauge=result['gauges'][key]
            self.assertEqual(gauge['mask_mode'],'v5_coherent_ray')
            self.assertGreaterEqual(gauge['line_span'],90)
            self.assertLessEqual(gauge['fit_p90'],8)
            self.assertLessEqual(gauge['hub_error'],16)
            self.assertGreaterEqual(gauge['radial_continuity'],9)
            self.assertEqual(gauge['value'],0) # Actual empty reference needle, not a fabricated missing value.

    def test_routing_does_not_promote_short_ticks_or_unaligned_strict_fit(self):
        import numpy as np
        with patch.dict(sys.modules,{'fcntl':types.ModuleType('fcntl')}):
            engine=reader.MemoryReader(fixtures.wrapper,FOLDER.parent,partial_quality=True,pressure_routing=True)
        scope=engine.reader.read_front.__globals__
        old=dict(mask_mode='strict',line_span=50,base=(100,100),tip=(100,50))
        with patch.dict(scope,{'_v5_aligned_hub':lambda *a:None}):
            self.assertIs(scope['_v5_pressure'](np.zeros((300,400,3),dtype=np.uint8),'front',{},old),old)
        mask=np.zeros((300,400),dtype=np.uint8);mask[80:110,194:201]=255
        self.assertIsNone(scope['_v5_pressure_ray'](mask,(200,190),1.0))

    def partial_case(self, mutate=None, *, registration=None):
        import cv2
        import numpy as np
        with patch.dict(sys.modules,{'fcntl':types.ModuleType('fcntl')}):
            engine=reader.MemoryReader(fixtures.wrapper,FOLDER.parent,partial_quality=True)
        raw={key:dict(angle=90,base=(0,0),tip=(120,0),line_span=120,mask_mode='strict',
             quality_status='detected',detection_quality='good',
             **({'pressure':5.5} if key in ('front','rear') else {'percent':50})) for key in engine.baseline.GAUGES}
        if mutate:mutate(raw)
        log=registration or 'Registration quality: good\nORB good matches: 30\nORB inliers: 30\nInlier ratio: 0.8\nCurrent scale: 1.0\nRotation: 0.0 deg\n'
        def detection(*args,**kwargs):engine.reader.print(log);return raw
        sample=dict(main_jpeg=b'fake',sequence=17,stamp=datetime.now(timezone.utc))
        with patch.object(cv2,'imdecode',return_value=np.zeros((1080,1920,3),dtype=np.uint8)), \
             patch.object(engine.reader,'read_dashboard',side_effect=detection):
            selected=engine.analyze(sample)
        self.assertIs(selected['sample'],sample)
        frame=fixtures.wrapper.make_snapshot(fixtures.transport,dict(device_id='GPS-002',camera_id='CAM-002'),
            'partial-session',17,b'jpeg',sample['stamp'],selected['gauges'])
        return engine,frame

    def test_partial_rejected_pressure_does_not_hide_four_valid_same_capture_gauges(self):
        def mutate(raw):
            raw['front']['line_span']=1
            raw['rear']['quality_status']='review'
        engine,frame=self.partial_case(mutate)
        self.assertEqual(frame['capture_id'],'partial-session:17')
        self.assertEqual(len(frame['readings']),6)
        for reading in frame['readings']:
            rejected=reading['gauge_key'] in ('frontAir','rearAir')
            self.assertEqual(reading['quality'],'uncertain' if rejected else 'detected')
            if rejected:
                self.assertTrue(all(reading[key] is None for key in ('value','angle_deg','dial_percent')))
            else:self.assertEqual(reading['value'],50)
        self.assertEqual(engine.last_diagnostic['detected'],4)
        self.assertEqual(engine.last_diagnostic['state'],'partial-quality')

    def test_partial_global_registration_failure_invalidates_every_value(self):
        log='Registration quality: review\nORB good matches: 30\nORB inliers: 19\nInlier ratio: 0.1\nCurrent scale: 1.0\nRotation: 0.0 deg\n'
        engine,frame=self.partial_case(registration=log)
        self.assertEqual(engine.last_diagnostic['state'],'all-uncertain')
        self.assertIn('registration:poor_or_unknown',engine.last_diagnostic['reasons'])
        self.assertTrue(all(r['quality']=='uncertain' and r['value'] is None and r['angle_deg'] is None for r in frame['readings']))

    def test_partial_unknown_mode_or_native_review_never_becomes_a_detected_number(self):
        def mutate(raw):
            raw['fuel']['mask_mode']='unknown-mode'
            raw['oil']['detection_quality']='review'
        engine,frame=self.partial_case(mutate)
        self.assertEqual(engine.last_diagnostic['detected'],4)
        self.assertTrue(all(r['quality']=='uncertain' and r['value'] is None for r in frame['readings']
                            if r['gauge_key'] in ('fuel','oilPressure')))

    def test_partial_actual_calibration_reference_keeps_pressure_rejection_without_hiding_valid_gauges(self):
        import cv2
        import builtins
        native_open=builtins.open
        def read_only(file,mode='r',*args,**kwargs):
            if isinstance(mode,str) and any(c in mode for c in 'wax+'):
                raise AssertionError('Unexpected filesystem write')
            return native_open(file,mode,*args,**kwargs)
        with patch.dict(sys.modules,{'fcntl':types.ModuleType('fcntl')}), \
             patch('builtins.open',side_effect=read_only), \
             patch.object(cv2,'imwrite',side_effect=AssertionError('No image files')), \
             patch.object(Path,'mkdir',side_effect=AssertionError('No output directories')):
            engine=reader.MemoryReader(fixtures.wrapper,FOLDER.parent,partial_quality=True)
            selected=engine.analyze(dict(main_jpeg=engine.reader.REFERENCE_IMAGE.read_bytes(),sequence=1))
        self.assertIsNotNone(selected)
        self.assertEqual(engine.last_diagnostic['candidates'],6)
        self.assertEqual(engine.last_diagnostic['detected'],4)
        self.assertIn('front:geometry_short_shaft:51.2',engine.last_diagnostic['reasons'])
        self.assertIn('rear:geometry_short_shaft:54.1',engine.last_diagnostic['reasons'])
        self.assertEqual(selected['gauges']['front']['value'],None)
        self.assertEqual(selected['gauges']['rear']['angle'],None)

    def test_slot_is_one_latest_frame_not_backlog(self):
        slot=live.LatestSlot()
        for i in range(1000):slot.put(i)
        self.assertEqual(slot.get(),999);self.assertEqual(slot.dropped,999)
        slot.close();slot.put('late');self.assertIsNone(slot.get(.001))

    def test_io_transform_only_removes_reviewed_image_io_and_keeps_original_gates(self):
        source=(FOLDER.parent/'centrabus_dashboard_reader.py').read_bytes()
        tree=reader.detector_tree(source)
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
        self.assertFalse(any(isinstance(n.func,ast.Attribute) and n.func.attr in ('imwrite','mkdir') for n in calls))
        # Original calibration/reference imread remains; live input is RAM.
        self.assertTrue(any(isinstance(n,ast.Name) and n.id=='_ram_dashboard' for n in ast.walk(tree)))
        self.assertIn('MIN_GOOD_MATCHES',ast.unparse(tree))
        self.assertIn('RANSAC_THRESHOLD',ast.unparse(tree))
        with self.assertRaises(ValueError):reader.detector_tree(b'pass')
        self.assertEqual(fixtures.wrapper.verify_baseline(FOLDER.parent),FOLDER.parent.resolve())

    def exercise(self,*,slow_detector=.14,slow_network=.025,fail=False,stale=False):
        seen=[];stats_messages=[]
        class Camera:
            n=0;closed=False
            def capture(self,need_main):
                self.n+=1
                stamp=datetime.fromtimestamp(time.time()-(4 if stale else 0),timezone.utc)
                return stamp,('jpeg'+str(self.n)).encode(),b'main' if need_main else None
            def close(self):self.closed=True
        camera=Camera()
        class Analyzer:
            def analyze(self,sample):
                time.sleep(slow_detector)
                return None
        class Sender:
            closed=False
            def send(self,frame):
                if fail:raise ValueError('TEST_PRIVATE_KEY_MUST_NOT_LOG')
                time.sleep(slow_network);seen.append(frame)
            def close(self):self.closed=True
        sender=Sender()
        config=dict(device_id='GPS-002',camera_id='CAM-002',secret='a'*64)
        with patch.object(Path,'write_bytes',side_effect=AssertionError('No frames on disk')), \
             patch.object(Path,'write_text',side_effect=AssertionError('No state/logs on disk')), \
             patch.object(Path,'mkdir',side_effect=AssertionError('No output directories')):
            stats=live.run_session(camera,Analyzer(),sender,fixtures.transport,fixtures.wrapper,config,
                seconds=.45,fps=20,emit=stats_messages.append)
        self.assertTrue(camera.closed);self.assertTrue(sender.closed)
        self.assertNotIn('TEST_PRIVATE_KEY_MUST_NOT_LOG',''.join(stats_messages))
        return stats,seen

    def test_slow_detection_does_not_block_camera_preview_and_never_writes(self):
        stats,seen=self.exercise()
        self.assertGreaterEqual(stats['captured'],6);self.assertGreaterEqual(len(seen),5)
        self.assertEqual(stats['observations_ack'],0)
        self.assertTrue(all(r['value'] is None for f in seen for r in f['readings']))
        self.assertFalse(stats['failure'])
        self.assertGreater(stats['analysis_completed'],0)
        self.assertEqual(stats['analysis_completed'],stats['rejected'])
        self.assertGreater(stats['analysis_last_ms'],0)

    def test_slow_network_drops_old_pending_frames_not_backlog(self):
        stats,seen=self.exercise(slow_network=.15)
        self.assertGreater(stats['preview_dropped'],0)
        self.assertGreater(stats['captured'],len(seen))
        self.assertEqual(sorted(f['sequence'] for f in seen),[f['sequence'] for f in seen])

    def test_network_failure_stops_redacted_and_closes_camera(self):
        stats,_=self.exercise(fail=True)
        self.assertTrue(stats['failure'])

    def preview_case(self, *, analyzer=None, send=None, seconds=.4, stop_event=None, clock=time.monotonic, capture=None):
        frames=[]
        class Camera:
            closed=False
            def capture(self,need_main):
                if capture: capture(need_main)
                return datetime.now(timezone.utc),b'jpeg',b'main' if need_main else None
            def close(self):self.closed=True
        camera=Camera()
        class Sender:
            def send(self,frame):
                if send:send(frame)
                frames.append(frame)
            def close(self):pass
        stats=live.run_session(camera,analyzer,Sender(),fixtures.transport,fixtures.wrapper,
            dict(device_id='GPS-002',camera_id='CAM-002',secret='a'*64),seconds=seconds,fps=20,
            clock=clock,stop_event=stop_event,emit=lambda text:None)
        self.assertTrue(camera.closed)
        return stats,frames

    def test_detector_error_does_not_close_the_preview(self):
        class Broken:
            def analyze(self,sample):raise ValueError('analysis unavailable')
        stats,frames=self.preview_case(analyzer=Broken())
        self.assertTrue(stats['analysis_failure'])
        self.assertFalse(stats['failure'])
        self.assertGreaterEqual(len(frames),4)
        self.assertEqual(stats['analysis_error_phase'],'detector')

    def test_temporary_observation_delivery_recovers_without_replaying_an_old_capture(self):
        from urllib.error import URLError
        sent=[]
        class Analyzer:
            def analyze(self,sample):return dict(sample=sample,gauges=fixtures.observations())
        def deliver(config,frame):
            sent.append(frame)
            self.assertEqual(frame['processor_version'],live.PROCESSOR)
            if len(sent)==1:raise URLError('synthetic private network detail')
        with patch.object(fixtures.transport,'send',side_effect=deliver):
            stats,frames=self.preview_case(analyzer=Analyzer(),seconds=1.35)
        self.assertEqual(stats['observation_unavailable'],1)
        self.assertFalse(stats['analysis_failure'])
        self.assertGreaterEqual(stats['observations_ack'],1)
        self.assertGreater(len(frames),5)
        self.assertEqual(len({f['capture_id'] for f in sent}),len(sent))
        self.assertGreater(sent[-1]['sequence'],sent[0]['sequence'])

    def test_observation_auth_or_proof_rejection_stays_closed_without_stopping_preview(self):
        from urllib.error import HTTPError
        class Analyzer:
            def analyze(self,sample):return dict(sample=sample,gauges=fixtures.observations())
        for error in [HTTPError('http://fixture.invalid',403,'denied',{},None),ValueError('bad acknowledgement proof')]:
            with self.subTest(error=type(error).__name__),patch.object(fixtures.transport,'send',side_effect=error):
                stats,frames=self.preview_case(analyzer=Analyzer())
                self.assertTrue(stats['analysis_failure'])
                self.assertEqual(stats['analysis_error_phase'],'delivery')
                self.assertEqual(stats['observations_ack'],0)
                self.assertGreaterEqual(len(frames),3)

    def test_only_network_transients_can_be_recovered_not_auth_validation_or_detector_errors(self):
        from urllib.error import HTTPError
        for status in [408,429,500,502,503,504]:
            self.assertTrue(live.temporary_observation_failure(HTTPError('http://fixture.invalid',status,'test',{},None)))
        for status in [400,401,403,404,409,422]:
            self.assertFalse(live.temporary_observation_failure(HTTPError('http://fixture.invalid',status,'test',{},None)))
        self.assertFalse(live.temporary_observation_failure(ValueError('detector error')))

    def test_preview_only_does_not_capture_analysis_frames(self):
        requested=[]
        stats,frames=self.preview_case(capture=requested.append)
        self.assertGreaterEqual(len(frames),4)
        self.assertTrue(all(value is False for value in requested))
        self.assertEqual(stats['observations_ack'],0)

    def test_continuous_mode_passes_ninety_seconds_and_stops_only_on_explicit_event(self):
        stop=threading.Event();ticks=[0];captures=[]
        def capture(need_main):
            captures.append(need_main);ticks[0]+=61
            if len(captures)==3:stop.set()
        stats,_=self.preview_case(seconds=None,stop_event=stop,clock=lambda:ticks[0],capture=capture)
        self.assertEqual(stats['captured'],3)
        self.assertGreater(stats['elapsed_seconds'],90)

    def test_transient_delivery_outage_recovers_with_newest_frames_without_replay(self):
        attempted=[]
        def send(frame):
            attempted.append(frame['sequence'])
            if len(attempted)<=2:raise live.PreviewUnavailable()
        stats,frames=self.preview_case(send=send,seconds=.9)
        self.assertEqual(stats['preview_unavailable'],2)
        self.assertFalse(stats['failure'])
        self.assertGreaterEqual(len(frames),2)
        self.assertEqual(len(set(attempted)),len(attempted))
        self.assertGreater(stats['preview_dropped'],0)

    def test_discarded_frame_does_not_stop_the_camera_or_get_replayed(self):
        attempted=[]
        def send(frame):
            attempted.append(frame['sequence'])
            if len(attempted)==1:raise live.PreviewFrameDropped()
        stats,frames=self.preview_case(send=send)
        self.assertEqual(stats['preview_discarded'],1)
        self.assertFalse(stats['failure'])
        self.assertGreaterEqual(len(frames),3)
        self.assertEqual(len(set(attempted)),len(attempted))

    def test_live_sender_distinguishes_temporary_delivery_from_authentication_rejection(self):
        signer=load('reconnect_preview_signer',FOLDER/'preview_v5.py')
        frame=fixtures.transport.make_payload(dict(device_id='GPS-002',camera_id='CAM-002',secret='a'*64),
            'session-qa',1,b'jpeg',datetime.now(timezone.utc),{})
        frame['processor_version']=live.PROCESSOR
        for status,body,error in [(503,b'{}',live.PreviewUnavailable),(429,b'{}',live.PreviewUnavailable),
                                  (409,b'{}',live.PreviewFrameDropped),
                                  (422,b'{"error":"camera-live-too-old"}',live.PreviewFrameDropped),
                                  (403,b'{}',ValueError),(401,b'{}',ValueError)]:
            with self.subTest(status=status):
                sender=live.LiveSender(dict(backend_url='http://127.0.0.1:1',device_id='GPS-002',secret='a'*64),signer)
                response=types.SimpleNamespace(status=status,read=lambda limit:body)
                connection=types.SimpleNamespace(request=lambda *a,**kw:None,getresponse=lambda:response,close=lambda:None)
                with patch.object(sender,'factory',return_value=connection) as factory:
                    with self.assertRaises(error):sender.send(frame)
                    self.assertEqual(factory.call_args.kwargs['timeout'],1)
                sender.close()

    def test_stale_sensor_frame_is_not_retimestamped_or_sent(self):
        with self.assertRaises(ValueError):self.exercise(stale=True)

    def test_no_runtime_writers_temp_images_or_file_camera_api(self):
        for file in ['live_memory.py','memory_reader.py']:
            tree=ast.parse((FOLDER/file).read_bytes())
            forbidden={'write_bytes','write_text','imwrite','save','capture_file','NamedTemporaryFile','mkstemp','atomic_json','run_cycle','mkdir'}
            for node in ast.walk(tree):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):self.assertNotIn(node.func.attr,forbidden)
        # Only baseline/calibration references are read. No file-based detector input.
        self.assertNotIn('output-dir',(FOLDER/'live_memory.py').read_text())

    def test_real_detector_rejects_unclear_memory_image_without_writing_any_image_or_state(self):
        import builtins
        import cv2
        import numpy as np
        native_open=builtins.open
        def read_only(file, mode='r', *args, **kwargs):
            if isinstance(mode,str) and any(c in mode for c in 'wax+'):
                raise AssertionError('Unexpected filesystem write')
            return native_open(file,mode,*args,**kwargs)
        ok,encoded=cv2.imencode('.jpg',np.zeros((1080,1920,3),dtype=np.uint8));self.assertTrue(ok)
        with patch.dict(sys.modules,{'fcntl':types.ModuleType('fcntl')}), \
             patch('builtins.open',side_effect=read_only), \
             patch.object(Path,'mkdir',side_effect=AssertionError('Unexpected directory')), \
             patch.object(cv2,'imwrite',side_effect=AssertionError('Unexpected image write')):
            for partial,routing in [(False,False),(True,False),(True,True)]:
                engine=reader.MemoryReader(fixtures.wrapper,FOLDER.parent,partial_quality=partial,pressure_routing=routing)
                selected=engine.analyze({'main_jpeg':encoded.tobytes()})
                self.assertIsNone(selected)
                self.assertEqual(engine.last_diagnostic['candidates'],0)
                self.assertEqual(engine.last_diagnostic['reasons'],['orb_registration'])
                self.assertNotIn('main_jpeg',str(engine.last_diagnostic))

    def test_accepted_memory_reading_is_same_capture_as_preview_and_preserves_existing_gates(self):
        import cv2
        import numpy as np
        with patch.dict(sys.modules,{'fcntl':types.ModuleType('fcntl')}):engine=reader.MemoryReader(fixtures.wrapper,FOLDER.parent)
        raw={key:dict(angle=90,base=(0,0),tip=(120,0),line_span=120,mask_mode='strict',quality_status='detected',detection_quality='good',
             **({'pressure':5.5} if key in ('front','rear') else {'percent':50})) for key in engine.baseline.GAUGES}
        log='Registration quality: good\nORB good matches: 30\nORB inliers: 30\nInlier ratio: 0.8\nCurrent scale: 1.0\nRotation: 0.0 deg\n'
        def detection(*args,**kwargs):engine.reader.print(log);return raw
        with patch.object(cv2,'imdecode',return_value=np.zeros((1080,1920,3),dtype=np.uint8)), \
             patch.object(engine.reader,'read_dashboard',side_effect=detection), \
             patch.object(cv2,'imwrite',side_effect=AssertionError('Unexpected image write')):
            sample={'main_jpeg':b'fake-jpeg','sequence':7,'preview_jpeg':b'exact-preview','epoch':123}
            accepted=engine.analyze(sample);self.assertIs(accepted['sample'],sample)
            self.assertEqual(set(accepted['gauges']),set(engine.baseline.GAUGES))
            self.assertEqual(engine.last_diagnostic['state'],'accepted')
            self.assertEqual(engine.last_diagnostic['candidates'],6)
            raw['fuel']['line_span']=1
            self.assertIsNone(engine.analyze(sample));self.assertIsNone(engine.analyze(sample));self.assertIsNone(engine.analyze(sample))
            self.assertEqual(engine.last_diagnostic['state'],'geometry-rejected')
            self.assertEqual(engine.last_diagnostic['candidates'],6)
            self.assertIn('fuel:geometry_short_shaft:1.0',engine.last_diagnostic['reasons'])
            self.assertEqual(engine.last_diagnostic['registration']['inliers'],30)

    def test_same_camera_request_produces_two_ram_jpegs_and_is_always_released(self):
        import cv2
        import numpy as np
        class Request:
            released=0
            def get_metadata(self):return {'SensorTimestamp':123}
            def make_array(self,stream):
                return np.zeros((540,640),dtype=np.uint8) if stream=='lores' else np.zeros((1080,1920,3),dtype=np.uint8)
            def release(self):self.released+=1
        request=Request();camera=object.__new__(live.MemoryCamera)
        stamp=datetime.now(timezone.utc)
        camera.wrapper=types.SimpleNamespace(sensor_timestamp=lambda metadata:stamp)
        camera.camera=types.SimpleNamespace(capture_request=lambda:request)
        with patch.object(cv2,'imwrite',side_effect=AssertionError('No frame file')):
            actual,preview,main=camera.capture(True)
            self.assertIs(actual,stamp);self.assertTrue(preview.startswith(b'\xff\xd8'));self.assertTrue(main.startswith(b'\xff\xd8'))
        self.assertEqual(request.released,1)
        with patch.object(cv2,'imencode',return_value=(False,None)):
            with self.assertRaises(ValueError):camera.capture(False)
        self.assertEqual(request.released,2)

if __name__=='__main__':unittest.main()
