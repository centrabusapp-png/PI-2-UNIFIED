"""Portable V6 publication checks. No camera, archive regression or upload."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
V6 = ROOT / 'candidate/camera/centrabus_live_runtime_v6_dev_20261023'


def isolated(code):
    # V5/V6 use historical top-level module names. A separate interpreter keeps
    # these checks from contaminating other candidate versions in a test suite.
    prelude = '''
import sys, importlib.abc
from pathlib import Path
sys.path.insert(0, sys.argv[1])
class NoCamera(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.split('.')[0] in ('picamera2', 'libcamera'):
            raise AssertionError('Physical camera import prohibited by offline QA')
sys.meta_path.insert(0, NoCamera())
from common import verify_runtime
verify_runtime(check_original=False)
'''
    result = subprocess.run([sys.executable, '-B', '-c', textwrap.dedent(prelude) + textwrap.dedent(code), str(V6)],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise AssertionError(result.stdout[-2000:] + result.stderr[-4000:])
    return result.stdout


class V6PublicationTests(unittest.TestCase):
    def test_packaged_hashes_and_original_candidate_provenance(self):
        provenance = json.loads((V6 / 'source_provenance.json').read_text())
        for relative, expected in provenance['copied_files'].items():
            path = V6 / relative
            self.assertTrue(path.is_file(), relative)
            self.assertFalse(path.is_symlink(), relative)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected, relative)
        expected_paths = set()
        for line in (V6 / 'SHA256SUMS').read_text().splitlines():
            expected, relative = line.split('  ', 1)
            self.assertNotIn('..', Path(relative).parts)
            self.assertEqual(hashlib.sha256((V6 / relative).read_bytes()).hexdigest(), expected)
            expected_paths.add(relative)
        actual = {p.relative_to(V6).as_posix() for p in V6.rglob('*') if p.is_file()
                  and p.name != 'SHA256SUMS' and '__pycache__' not in p.parts
                  and not any(part in ('annotations', 'validation') for part in p.relative_to(V6).parts)}
        self.assertEqual(actual, expected_paths)

    def test_local_reference_import_and_blank_abstention_without_image_output(self):
        isolated('''
import json, cv2, numpy as np
from PIL import Image
def forbidden(*args, **kwargs): raise AssertionError('Offline QA must not save images')
cv2.imwrite = forbidden
Image.Image.save = forbidden
from pipeline import process
import centrabus_dashboard_reader as reader
reference = reader.REFERENCE_IMAGE
assert reference.is_file() and reference.is_relative_to(Path(sys.argv[1]))
assert not reference.is_symlink()
frame = cv2.imread(str(reference))
result = process(frame)
assert len(result['rows']) == 6 and not result['stage_errors']
assert all(row['angle_image_deg'] is not None for row in result['rows'])
assert all(row['published_value'] is None for row in result['rows'] if row['outcome'] != 'SUCCESS')
blank = process(np.zeros((768, 1366, 3), np.uint8))
assert len(blank['rows']) == 6
assert all(row['outcome'] == 'FAILED' and row['value'] is None for row in blank['rows'])
assert 'picamera2' not in sys.modules and 'libcamera' not in sys.modules
''')

    def test_conversion_limits_review_and_json_schema_are_preserved(self):
        isolated('''
import json, copy
from display_estimates import display_estimate
from live_reader import unavailable, reading_text
from gauge_data import payload
from fast_reader import now_manila
from indicative_status import indicative_status
for gauge, low, high, vmax in [('fuel',135.,40.,100.),('battery',135.,40.,100.),
                             ('oil',135.,40.,100.),('front',137.3,43.8,15.),('rear',137.3,43.8,15.)]:
    assert display_estimate({'detector_angle_image':low}, gauge, 'REVIEW')['value'] == 0.
    estimate = display_estimate({'detector_angle_image':high}, gauge, 'REVIEW')
    assert estimate['value'] == vmax and estimate['availability'] == 'REVIEW_UNVERIFIED_ESTIMATE'
    assert display_estimate({'detector_angle_image':low+.001}, gauge, 'REVIEW')['value'] is None
assert display_estimate({'detector_angle_image':145.}, 'coolant', 'REVIEW')['value'] == 0.
assert display_estimate({'detector_angle_image':145.001}, 'coolant', 'REVIEW')['value'] is None
for gauge, expected in [('coolant',['Cold','Normal','Hot']),('battery',['Low','Normal','High']),('oil',['Low','Normal','High'])]:
    assert [indicative_status(gauge, v, 'DETECTED') for v in (24.999,25.,75.)] == expected
result = unavailable('synthetic missing frame')
data = payload(result, now_manila(), 1, capture_available=False)
assert data['captured_at'] is None and len(data['gauges']) == 6
assert all(r['value'] is None and r['published_value'] is None for r in data['gauges'].values())
assert not data['measurement_verified']
json.dumps(data, allow_nan=False)
row = copy.deepcopy(result['rows'][0])
row.update(value=26.6, angle_image_deg=109.77, outcome='REVIEW')
assert 'REVIEW' in reading_text(row) and '26.6%' in reading_text(row)
''')

    def test_camera_mode_requires_explicit_opt_in(self):
        isolated('''
import io
from unittest.mock import patch
import live_reader
with patch('live_reader.v5.PersistentCamera') as camera, patch('sys.stderr', new_callable=io.StringIO):
    try: live_reader.main([])
    except SystemExit as error: assert error.code == 2
    else: raise AssertionError('Missing explicit mode was accepted')
    camera.assert_not_called()
''')

    def test_existing_validation_evidence_retains_review_and_limits(self):
        development = json.loads((V6 / 'evidence/development_130_summary.json').read_text())
        self.assertEqual(development['cases'], 780)
        self.assertEqual(development['supported_estimates'], 600)
        self.assertEqual(development['unavailable_numbers'], 180)
        self.assertEqual(development['quality'], {'SUCCESS': 324, 'REVIEW': 456})
        self.assertFalse(development['independent_accuracy_measured'])
        live = json.loads((V6 / 'evidence/live_60_summary.json').read_text())
        self.assertEqual((live['capture_successes'], live['auto'], live['review'], live['unavailable']), (60,320,40,0))
        self.assertEqual(live['all_gauge_review_cycles'], [16,28,48])
        self.assertEqual(len(live['rear_short_shaft_cycles']), 23)
        self.assertEqual(live['gauges']['fuel']['review_cycles'], [16,28,37,48])
        self.assertFalse(live['review_values_published'])
        self.assertFalse(live['measurement_accuracy_verified'])


if __name__ == '__main__': unittest.main()
