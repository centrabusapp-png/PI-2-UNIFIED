"""RAM-only IO adaptation of the exact hash-pinned original gauge detector.

Numerical code and gate thresholds remain original. Only two mkdir calls,
the input imread, and the annotation imwrite are removed in a private AST copy.
No source file is rewritten; no current image/annotation/state is written.
Optional partial-quality publication scopes existing failures to their gauge;
global registration failures still invalidate every gauge, with no numbers.
"""
from __future__ import annotations
import ast
import builtins
import io
import sys
import types


class MemoryIO(ast.NodeTransformer):
    def __init__(self):
        self.removed = dict(mkdir=0, input=0, annotation=0)

    def visit_Expr(self, node):
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == 'mkdir':
            self.removed['mkdir'] += 1
            return ast.copy_location(ast.Pass(), node)
        return self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'cv2':
            if node.func.attr == 'imwrite':
                self.removed['annotation'] += 1
                return ast.copy_location(ast.Constant(True), node)
            if node.func.attr == 'imread' and len(node.args) == 1:
                argument = node.args[0]
                if isinstance(argument, ast.Call) and isinstance(argument.func, ast.Name) and argument.func.id == 'str' \
                        and len(argument.args) == 1 and isinstance(argument.args[0], ast.Name) and argument.args[0].id == 'image_path':
                    self.removed['input'] += 1
                    return ast.copy_location(ast.Name(id='_ram_dashboard', ctx=ast.Load()), node)
        return self.generic_visit(node)


def detector_tree(source):
    tree = ast.parse(source)
    transform = MemoryIO()
    tree = transform.visit(tree)
    if transform.removed != dict(mkdir=2, input=1, annotation=1):
        raise ValueError('Unexpected detector IO layout; do not run')
    return ast.fix_missing_locations(tree)


def pressure_routing_tree(source):
    """Route short strict fits through the EXISTING V5 full-shaft checker.

    One mode predicate changes; all existing numerical thresholds, calibration,
    mask, hub alignment, continuity and publication gates stay unchanged.
    """
    tree=ast.parse(source)
    changed=0
    for function in tree.body:
        if not isinstance(function,ast.FunctionDef) or function.name!='_v5_pressure':
            continue
        node=function.body[0]
        if (isinstance(node,ast.If) and ast.unparse(node.test)=="old.get('mask_mode') != 'live_radial'"):
            node.test=ast.Compare(left=node.test.left,ops=[ast.NotIn()],
                comparators=[ast.Tuple(elts=[ast.Constant('live_radial'),ast.Constant('strict')],ctx=ast.Load())])
            changed+=1
    if changed!=1:raise ValueError('Unexpected original pressure routing; do not run')
    return ast.fix_missing_locations(tree)


class MemoryReader:
    def __init__(self, wrapper, runtime, *, partial_quality=False, pressure_routing=False):
        runtime = wrapper.verify_baseline(runtime)
        # Imports only the pinned numerical helpers. No baseline run_cycle,
        # PersistentCamera.capture, atomic_json, state/log/image file writer.
        sys.path.insert(0, str(runtime))
        try:
            self.baseline = wrapper.load_module('_centrabus_ram_gates', runtime / 'fast_reader.py')
            path = runtime / 'centrabus_dashboard_reader.py'
            module = types.ModuleType('_centrabus_ram_detector')
            module.__file__ = str(path)
            exec(compile(detector_tree(path.read_bytes()), str(path), 'exec'), module.__dict__)
            if pressure_routing:
                pressure_path=runtime/'gauge_readers.py'
                pressure=types.ModuleType('_centrabus_original_pressure_routing')
                pressure.__file__=str(pressure_path)
                exec(compile(pressure_routing_tree(pressure_path.read_bytes()),str(pressure_path),'exec'),pressure.__dict__)
                module.read_front=pressure.read_front
                module.read_rear=pressure.read_rear
            # A module-local print sink, not redirect_stdout (which would change
            # sys.stdout globally while the independent preview thread runs).
            module._ram_log = None
            def capture_print(*args, **kwargs):
                if module._ram_log is not None:
                    builtins.print(*args, **{**kwargs, 'file': module._ram_log})
            module.print = capture_print
            self.reader = module
        finally:
            sys.path.pop(0)
        self.records = []
        self.attempt = 0
        self.partial_quality = partial_quality
        self.normalize = wrapper.normalized_readings
        self.last_diagnostic = dict(state='waiting', candidates=0, reasons=[])

    def analyze(self, sample):
        import cv2
        # Decode the in-memory JPEG, preserving the original JPEG input contract.
        import numpy as np
        dashboard = cv2.imdecode(np.frombuffer(sample['main_jpeg'], dtype=np.uint8), cv2.IMREAD_COLOR)
        if dashboard is None or dashboard.shape != (1080, 1920, 3):
            raise ValueError('Invalid memory detector input')
        self.attempt += 1
        self.reader._ram_dashboard = dashboard
        capture = io.StringIO()
        self.reader._ram_log = capture
        selected = None
        diagnostic = dict(state='rejected', attempt=self.attempt, candidates=0, reasons=[])
        try:
            raw = self.reader.read_dashboard('ram-input.jpg', output_path='ram-annotation-discarded.jpg')
            baseline = self.baseline
            registration = baseline.registration_from_log(capture.getvalue())
            if set(raw) != set(baseline.GAUGES):
                raise ValueError('Exactly six gauges required')
            gauges = {key: baseline.gauge_payload(raw[key]) for key in baseline.GAUGES}
            warnings = baseline.quality_warnings(registration, raw)
            geometry = baseline.geometry_warnings(raw, registration.get('scale'))
            # Numerical metadata only, never the image, annotation, private
            # configuration or captured detector stdout. These are the SAME
            # original gates used below, not new detection thresholds.
            diagnostic.update(candidates=len(raw), registration={key: registration.get(key)
                for key in ('quality', 'inliers', 'inlier_ratio', 'scale')}, reasons=warnings)
            # Diagnostic-only: native review can withhold a number even when the
            # publication warning list is empty. Preserve its original reason
            # and measured geometry without changing any acceptance decision.
            diagnostic['gauge_checks'] = {}
            for key, gauge in gauges.items():
                reasons = [reason for reason in warnings
                           if reason.startswith(key + ':') or reason.split(':', 1)[0] not in baseline.GAUGES]
                if gauge.get('quality_status') == 'review' or gauge.get('detection_quality') == 'review':
                    reasons.append('native_review:' + str(gauge.get('mask_mode', 'unknown')))
                diagnostic['gauge_checks'][key] = dict(
                    mode=gauge.get('mask_mode'), native_quality=gauge.get('quality_status'),
                    native_detection_quality=gauge.get('detection_quality'),
                    span_px=gauge.get('line_span'), hub_error_px=gauge.get('hub_error'),
                    fit_p90_px=gauge.get('fit_p90'), near_hub_px=gauge.get('endpoint_hub_near'),
                    radial_continuity=gauge.get('radial_continuity'), reasons=reasons)
            record = dict(attempt=self.attempt, gauges=gauges, sample=sample)
            if self.partial_quality:
                # Keep every original quality/geometry threshold. Unlike the
                # historical all-six publisher, a failed pressure shaft no
                # longer hides a different gauge which passed ALL its checks.
                # Registration/unknown-scale failures are global, never scoped
                # away. Native review/unknown quality also stays uncertain.
                global_failure = any(reason.split(':', 1)[0] not in baseline.GAUGES for reason in warnings)
                for key, gauge in gauges.items():
                    if global_failure or any(reason.startswith(key + ':') for reason in warnings):
                        gauge.update(status='uncertain', check_image=True)
                normalized = self.normalize(gauges)
                diagnostic['qualities'] = {key: value['status'].lower() for key, value in normalized.items()}
                diagnostic['detected'] = sum(value['status'] == 'DETECTED' for value in normalized.values())
                for key, value in normalized.items():
                    if value['status'] != 'DETECTED':
                        gauges[key].update(value=None, angle=None, check_image=True)
                selected = record
            elif self.attempt == 1 and not warnings:
                selected = record
            elif not geometry:
                self.records.append(record)
                pair = baseline.newest_consistent_pair(self.records, baseline.ANGLE_TOLERANCE_SIMPLE, baseline.ANGLE_TOLERANCE_PRESSURE)
                if pair:
                    selected = pair[2]
            diagnostic['state'] = ('accepted' if diagnostic['detected'] == 6 else 'partial-quality'
                if diagnostic['detected'] else 'all-uncertain') if self.partial_quality else (
                'accepted' if selected else 'geometry-rejected' if geometry else 'consensus-pending')
        except RuntimeError as error:
            # ORB/needle rejection is not a zero or a last-known fresh reading.
            diagnostic['reasons'] = [self.baseline.classify_detector_error(str(error))]
        finally:
            self.reader._ram_dashboard = None
            self.reader._ram_log = None
            capture.close()
            self.last_diagnostic = diagnostic
        if selected or self.attempt >= self.baseline.MAX_ATTEMPTS:
            self.records = []
            self.attempt = 0
        return selected
