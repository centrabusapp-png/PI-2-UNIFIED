"""Offline image acceptance: no camera, network, image output or recording."""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import types

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "candidate/camera/v5_upload"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, help="Existing 1920x1080 sample; default: calibration reference")
    parser.add_argument("--fit-frame", action="store_true",
                        help="Explicit offline simulation: fit source into 1920x1080, preserving aspect ratio in RAM")
    parser.add_argument("--partial-quality", action="store_true",
                        help="User-approved per-gauge publication; original numerical checks unchanged")
    parser.add_argument("--pressure-routing",action="store_true",help="Existing V5 full-shaft check also handles short strict fits")
    args = parser.parse_args()
    # The original Linux module imports fcntl for its file-based runner.
    # This offline diagnostic never invokes that runner, lock or capture.
    if os.name == "nt":
        sys.modules["fcntl"] = types.ModuleType("fcntl")
    wrapper = load("reference_check_wrapper", ADAPTER / "publish_v5.py")
    memory = load("reference_check_memory", ADAPTER / "memory_reader.py")
    engine = memory.MemoryReader(wrapper, ADAPTER.parent, partial_quality=args.partial_quality,pressure_routing=args.pressure_routing)
    encoded = (args.image or engine.reader.REFERENCE_IMAGE).read_bytes()
    import cv2
    import numpy as np
    decoded = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        raise ValueError("Unreadable sample image")
    source_shape = list(decoded.shape)
    if args.fit_frame:
        height, width = decoded.shape[:2]
        scale = min(1920 / width, 1080 / height)
        resized = cv2.resize(decoded, (round(width * scale), round(height * scale)),
                             interpolation=cv2.INTER_AREA)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        h, w = resized.shape[:2]
        y, x = (1080 - h) // 2, (1920 - w) // 2
        frame[y:y + h, x:x + w] = resized
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            raise ValueError("In-memory encoding failed")
        encoded = jpeg.tobytes()
        decoded = cv2.imdecode(jpeg, cv2.IMREAD_COLOR)
    if decoded.shape != (1080, 1920, 3):
        raise ValueError("Requires a readable 1920x1080 image; no implicit resizing")
    provenance = {"source_shape": source_shape, "simulated_fit_frame": args.fit_frame,
                  "physical_camera_tested": False, "image_files_written": False}
    attempts = []
    for sequence in range(1, 4):
        result = engine.analyze({"main_jpeg": encoded, "sequence": sequence})
        attempts.append({"attempt": sequence, "accepted": result is not None})
        if result:
            print(json.dumps({"attempts": attempts, "gauges": sorted(result["gauges"]),
                              "candidate_readings_unverified": result['gauges'],
                              "diagnostic": engine.last_diagnostic,
                              "partial_quality": args.partial_quality, **provenance}))
            return 0
    log = io.StringIO()
    engine.reader._ram_dashboard = decoded
    engine.reader._ram_log = log
    try:
        raw = engine.reader.read_dashboard("ram-input.jpg", output_path="ram-discard.jpg")
        registration = engine.baseline.registration_from_log(log.getvalue())
        details = {"registration": registration,
                   "rejection_reasons": engine.baseline.quality_warnings(registration, raw),
                   "candidate_angles_degrees_unverified": {
                       key: value.get("angle") for key, value in raw.items()}}
    except RuntimeError as error:
        details = {"rejection_reasons": [str(error)]}
    finally:
        engine.reader._ram_dashboard = None
        engine.reader._ram_log = None
        log.close()
    print(json.dumps({"attempts": attempts, **details, **provenance}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
