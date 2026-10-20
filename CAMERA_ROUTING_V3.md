# Pi2 RAM camera update: original V5 routing correction

Current processor: `centrabus-fast-v5-3754055-routing-v3`.
Read `AGENTS.md`, `DEVICE.md` and `candidate/camera/v5_upload/README.md` first.
This source update is not an installer, a calibration certification or a reason
to overwrite a working GPS service, queue, private configuration or Pi1 files.

## Included

- One camera owner; independent latest-only RAM preview/analysis. No automatic
  image/annotation/recording files. Pictures save on the laptop only after Capture.
- Existing V5 pressure checker also handles short strict fits in a private copy.
  All original numerical thresholds, pressure calibration and eight baseline
  files remain unchanged. The calibration-reference test passes all six; small
  or unclear real images may still be uncertain. Do not fabricate missing values.
- Per-gauge quality: passing gauges are sent; rejected/review gauges are null.
  Global registration errors invalidate every gauge, not just one pressure gauge.
- Temporary delivery errors discard an unconfirmed packet and analyze a NEW
  camera capture. No stale replay or timestamp replacement. Auth/proof failures
  remain closed. Camera and GPS service ownership/restoration checks remain.

The companion dashboard update clears six displayed readings with Preview off,
shows original capture time/freshness, descriptive dial statuses and exports
only matching image/readings. Turning Preview off does not stop the physical Pi
process. The backend/dashboard are separate Git repositories; a Pi pull does
not update them, apply SQL, change enrollment or start the camera.

## Layout and checks

`candidate/camera/v5_upload/` includes the pinned transport and SHA256SUMS needed
by the RAM session. Use only the reviewed RAM launcher, not the retained older
file-writing upload/preview experiments. Existing private configuration is never
in Git; the guard reuses its already-reviewed path. It currently targets the
existing Pi2 runtime at `/home/centrabus/Desktop/PI-2-UNIFIED-main/candidate/camera`.
Confirm actual paths/account and the correct V3 enrollment before any run.

Read-only checksum check in the adapter directory: `sha256sum -c SHA256SUMS`.
Offline tests (no camera/network; require compatible installed OpenCV/NumPy):

```text
python3 -I -B qa/test_pi2_memory_camera.py
python3 -I -B qa/test_pi2_v5_upload.py
python3 -I -B qa/test_pi2_v5_preview.py
python3 -I -B qa/check_camera_reference.py --partial-quality --pressure-routing
```

Never recursively execute archived `sources/` tests/installers. Test output is
ignored. Git-cloned repositories can pull updates; a ZIP-extracted folder is not
a Git checkout. Stop only the existing camera session and verify media/GPS
restoration before any separately approved staging/start. No physical operation
or production SQL is performed by this source publication.
