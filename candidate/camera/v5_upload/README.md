# Original V5 camera adapters: local preparation, NOT physical deployment

## New RAM-only live pipeline (supersedes the file-writing preview trial)

### Current V3: original full-shaft pressure routing correction

Processor is now `centrabus-fast-v5-3754055-routing-v3`. In a private AST copy
of the pinned gauge_readers.py, ONE mode predicate is corrected: _v5_pressure
also handles short strict fits, not just live_radial fits. This reuses the
EXISTING V5 hub/arc alignment, pressure_ray checker, pressure calibration and
all original numerical quality/publication thresholds. No extra pressure
algorithm or numerical threshold is introduced. Original source files and all
eight baseline hashes remain unchanged. Private front/rear readers are bound
only in this RAM analysis process; neither the installed runtime nor imports
in other processes are overwritten.

The original reference now passes all six per-gauge checks. Front/Rear full
shafts pass original span/continuity/p90/hub gates. Blank images, short red ticks
and unaligned strict fits remain rejected; small-scale review is NOT bypassed.
This is offline evidence, not a guarantee of physical Pi detection/accuracy.
The earlier V2 mode remains available for comparison but is not the current
live session's processor. Match the reviewed V3 enrollment before a new run.

The dashboard now clears all six displayed readings and pauses browser polling
when Preview is off. Turning it on starts new reads; stale values are withheld.
This display switch does not remotely shut down the physical Pi camera/process.
Fresh/Stale source timestamps identify the analysis age. Capture freezes the
same fresh analysis image/readings, or live pixels with no old numeric values.
Status captions reuse original 25/75 dial bands (Empty/Half/Full, Cold/Hot and
Low/High). They remain dial estimates, not new physical/safety classifications.

### Current: user-approved per-gauge quality publication

The operator explicitly approved showing passing gauges while rejected gauges
remain Uncertain with NO numeric value. The new RAM session uses processor
`centrabus-fast-v5-3754055-partial-v2`. This is NOT the withdrawn pressure-extent
experiment. No detector/calibration file, threshold, shaft-recovery algorithm
or image-saving behavior has changed. The original eight numerical pins remain.

`MemoryReader(..., partial_quality=True)` runs the original detector and
`quality_warnings`/`geometry_warnings`. Gauge-specific failures invalidate that
gauge only. Global registration/unknown-scale failures invalidate all six.
Native review/unknown quality still fails the original normalization check.
Uncertain value/angle/dial are null; no old values are carried into a new frame.
There is no relaxed consensus promotion: only individually passing, good-quality
current-capture results can be detected. The historical default/all-six path and
file-based wrappers remain unchanged for comparison, not for the new session.

Five-second progress now includes analysis started/completed/rejected/stale,
last/in-flight duration, original rejection reasons, registration metrics and
per-gauge qualities/count. It never prints pixels, private config or raw errors.
An observation ACK confirms delivery, NOT six successful detections; check the
per-gauge qualities and actual original capture ID/time on the dashboard.

Temporary observation-delivery timeouts/connection failures and HTTP
408/429/500/502/503/504 no longer permanently disable analysis. The uncertain
packet is discarded (it might already have committed if its ACK was lost).
Only a NEW current camera capture is analyzed/sent next; no replay or epoch
rewrite. Auth, validation and acknowledgement-proof failures still disable
analysis; unexpected detector errors also stop analysis, not preview. Progress
reports the failure phase (detector/delivery), never raw private exception text.
The original transport's 3s bound and all source-age/authentication checks remain.

Local tests: the original calibration reference publishes four good gauges and
keeps both short pressure shafts uncertain. The operator's portrait sample,
explicitly letterboxed in RAM for an offline simulation, publishes Fuel/Coolant
and keeps Front/Rear/Battery/Oil uncertain. These are not physical-camera tests
or validated physical measurements. No image files were created by these checks.

Before any later physical run: stop only the existing camera session, verify
MEDIA_RESTORE/GPS-state PASS, review the new public bundle and separate one-row
processor-only enrollment script. Do NOT run V2 against an enrolled V1 source.
The SQL preserves key/hash, expiry, mapping, history and last capture timestamp;
it must update exactly one matching enabled/unexpired Pi2 source or roll back.
No source renewal, automatic install, GPS operation or production SQL was run
by local preparation. The next section describes historical V1 behavior.

### Preview continuity update: original detector retained

The operator requested preview/latency fixes without adding detection rules.
The pressure-recovery experiment and its SQL were withdrawn before deployment.
`memory_reader.py` again uses ONLY the original pinned detector/gates, with its
image IO adapted to memory. No new pressure threshold, recovery algorithm,
calibration or processor identity is enabled. Processor remains
`centrabus-fast-v5-3754055-upload-v1`; do NOT run the withdrawn V2 processor SQL.

The older preview trial stopped automatically after 60 seconds and serialized
capture/upload/detection. The new live pipeline has independent latest-only
preview and analysis workers. A detector/observation error disables analysis
and reports it; preview continues. A brief HTTP timeout or temporary service
failure drops the old frame and reconnects for a NEW frame. Authentication,
proof/identity errors still stop. No stale packet is replayed or retimestamped.
Live HTTP requests have a 1-second socket timeout. Numeric progress counters
print every five seconds; images never appear in logs or output files.

For a foreground session that continues until Ctrl+C, use the NEW
`run_memory_session.sh` with the same explicit approvals as the guarded trial.
It verifies camera ownership/readiness first, restores desktop media on exit
and stops only its own child on interruption/disconnect. The original
`run_memory_trial.sh` still defaults to a bounded 60-second test.

For START FULL, after approved staging/hash verification:

```bash
# First isolate preview performance (no detector loaded):
bash ./run_memory_session.sh --approve-memory-preview --approve-gps-camera-mode --preview-only
# Stop with Ctrl+C, verify MEDIA_RESTORE=PASS, then, when ready:
bash ./run_memory_session.sh --approve-memory-preview --approve-gps-camera-mode
```

For START CAMERA omit `--approve-gps-camera-mode`. This does not install a boot
service, start GPS or remotely start a Pi from the Windows launcher.

The memory bundle has NINE public files, including SHA256SUMS and the new
session launcher. It EXCLUDES the withdrawn pressure helper. Previous V2
bundles must not be used for this original-detector preview workflow.

The operator physically verified the previous preview on Pi2: 29 snapshots in
about 60 seconds, zero accepted observations, media restored, GPS service state
unchanged. That version serializes capture/upload/detection and writes trial JPGs.
**Do not run `preview_v5.py`, `publish_v5.py` or the older trial guard for the
new no-image-saving workflow.** They are retained unchanged as historical code,
not silently deleted. Previously generated trial pictures are not removed.

New `live_memory.py` owns exactly one Picamera2 pipeline. It copies a 640x360
preview and, at most once a second, the 1920x1080 analysis image from the SAME
camera request and original SensorTimestamp. Encoding and current/pending images
exist in process memory only. It calls no capture_file, imwrite, image.save,
temporary-image API, state writer or recording API. No annotated image is saved.
One capacity-one slot per worker replaces pending work: slow network/detection
drops old pending frames instead of building a delay/backlog. Core dumps are
disabled by the guard; bytecode output is disabled. No image data is logged.
OS memory management/swap is not reconfigured by this update.

Preview target is 8 FPS, not a measured/guaranteed Pi2 result or 30 FPS video.
Analysis is independent, target at most 1 request/second. Native OpenCV and BLAS
threads are bounded in THIS process only. Actual capture FPS, upload mean time,
maximum original-frame age and drops are printed as NUMERIC counters, not images.
The bounded trial remains available, and the explicit foreground session above
removes that trial cutoff. No permanent camera or GPS service is installed.

`memory_reader.py` verifies the original eight hashes, then loads a private AST
copy of the exact detector. Its IO adaptations replace live input imread with
in-memory JPEG decode and remove two output mkdir calls and one annotation
imwrite. It fails closed if the expected IO layout differs. Original
ORB/calibration/geometry/quality/consensus gates are used unchanged. Source files
are not rewritten, and no cv2 global IO monkeypatch is used in the runtime.
The original strict adapter still normalizes readings and signs its processor
provenance. Units and safety interpretation remain UNVERIFIED.

The backend `/live?preview=1` channel holds only one latest JPEG per device in
RAM, has a 350KB upload limit and a stricter 2-second image age gate. It has a
separate bounded rate limit and HMAC purpose. It performs NO database commit.
For high-rate preview ONLY, server-authoritative source/admin checks have a
maximum ONE-SECOND authorization lease, counted from lookup start, never extended
by traffic. Revocation/expiry can take at most that lease to affect live preview.
Expired/slow/failed authority lookups withhold images; there is no stale fallback.
Cache admission is bounded, and only admin token digests are retained. Numerical
observation writes and matching analysis reads still revalidate on every request.

The dashboard polls latest-only at up to 8 FPS without overlapping requests or
browser persistent storage. Preview-off/page leave cancels polling and releases
references. Hiding the tab pauses requests and releases its image; returning
resumes with a fresh request when the preview switch is still on.
The newer LIVE image is labeled separately from the matching
analysis thumbnail/UTC and six gauges. Old readings are never asserted to belong
to a different live image. On an explicit **Capture** click only, the browser
freezes a matching analysis image + six gauges in memory and requests a PNG
download. Before any accepted detection, it can instead save the live image with
six null/Not detected gauges. No automatic download, upload, image history,
recording, localStorage or IndexedDB. The OS/browser chooses the download folder;
a download request is not proof of a completed save.

Accepted NUMERICAL gauge records, hashes and source times continue through the
existing Supabase observation API. These records do NOT contain image bytes.
No new schema, key or processor update is required for an existing unexpired
original-V5 enrollment. No production database change was made locally.

Prepare a NEW public RAM-only bundle on Windows:

```powershell
node qa/prepare-pi2-v5-camera-trial.cjs --prepare --memory
```

Transfer only its explicit public file list after operator authorization. Use a
NEW Pi2 staging directory, verify SHA256SUMS, and reuse the existing private
configuration path. Never copy configuration/secrets into the source bundle.
Restart the updated Windows launcher in START CAMERA or START FULL; readiness
must include `cameraLiveMemoryEnabled:true`. Existing GPS behavior stays separate.
After separately approving the physical trial, run in that NEW Pi2 directory:

```bash
# START CAMERA (GPS writes off):
bash ./run_memory_trial.sh --approve-memory-preview
# OR START FULL (explicit GPS-write approval, but starts no GPS services):
bash ./run_memory_trial.sh --approve-memory-preview --approve-gps-camera-mode
```

The guard verifies files/config/baseline, NTP, memory, updated backend readiness
and exclusive camera ownership before opening hardware. It restores the same
five originally active desktop media units and compares GPSD/monitor/sender
state/PIDs/restarts after all exit paths. Audio/microphone apps can pause. It
does not start the inactive GPS monitor or its failed GNSS-tuner dependency.
Do not restart that dependency as a side effect of camera testing.

Local tests/builds do not prove physical Pi2 throughput, focus, exposure, gauge
acceptance or GPS coexistence. First verify no image files appear during a new
bounded trial, actual counters, source age, matching Capture PNG and resource
usage, then separately approve any longer run. Stop on errors; do not retry
blindly or relax capture/freshness gates.

## Preview-first trial (October 20 update)

`preview_v5.py` adds authenticated raw snapshots BEFORE gauge detection. Even
an unrelated/unreadable scene can appear in Live Camera View with all six gauges
**Not detected**, never zero or a previous capture's readings. This is a bounded
snapshot preview, not a continuous high-frame-rate video stream. Its actual rate
and detector latency still require physical Pi2 measurement.

The raw preview uses a separate HMAC purpose/endpoint and is held in backend RAM
only. It makes no observation database insert. Only an accepted original V5
cycle can store readings, and it must enrich the IDENTICAL capture ID, original
SensorTimestamp-derived UTC and JPEG hash. A newer raw capture clears previous
live values. Expired, reassigned or revoked sources fail closed on every read;
stale images are withheld. Existing source age limits remain unchanged.

No schema migration, new secret, enrollment change or processor change is needed
for an existing unexpired enrollment of `centrabus-fast-v5-3754055-upload-v1`.
The original wrapper, transport, detector and its eight pinned inputs remain
unchanged. `publish_v5.py` below remains the older strict accepted-only rollback.
Native detector imports happen before camera capture, not within its freshness
budget. A detector rejection continues preview; delivery/proof failure stops the
trial without replay or a disk upload queue.

Prepare only public files on Windows:

```powershell
node qa/prepare-pi2-v5-camera-trial.cjs --prepare --preview
```

This produces six public files including `run_preview_trial.sh` and a manifest.
Do not add private configuration, detector files, images, queues or `.env`.
Transfer those public files into a NEW private staging directory on Pi2 after
operator authorization; never overwrite the original package. Reuse, by absolute
path, the already verified private configuration in
`/home/centrabus/centrabus-camera-v5-trial-20261020-945b22/camera-private.json`.
If that file is missing/changed, STOP for review; do not recreate/print secrets.

Restart the laptop's reviewed local launcher in **START CAMERA** (not START
SYSTEM). Its `/readyz` must now include `cameraPreviewEnabled:true`,
`cameraFramesEnabled:true`, `gpsPersistenceEnabled:false`, `simulation:false`.
Open `http://127.0.0.1:3000/live-camera`, select Pi2 / GPS-002, turn Preview on.
The browser preview switch does not start camera hardware by itself.

For a separately approved GPS + camera session, choose **START FULL** instead.
Readiness must also include `localFullSystem:true` and
`gpsPersistenceEnabled:true`. This enables the existing authenticated GPS
ingestion route alongside camera observations, but starts NO Pi sender, monitor
or GNSS tuner. Each sender must use its own existing identity and the same
launcher-printed API origin. The original GPS freshness/queue rules still apply.
In that mode the explicit camera trial command is:

```bash
bash ./run_preview_trial.sh --approve-preview-trial --approve-gps-camera-mode
```

The extra flag acknowledges that real GPS packets can write to the configured
database; it does not start or reconfigure GPS. Without that flag the trial guard
still requires GPS writes OFF. Never start the inactive GPS monitor without
reviewing its GNSS-tuner dependency separately.

The separately approved physical command in the NEW staging directory is:

```bash
bash ./run_preview_trial.sh --approve-preview-trial
```

The guard first verifies public hashes, unchanged runtime/config ownership,
synchronized clock, available memory and the existing configured backend's
camera-only readiness. No secrets/images/GPS are sent by that readiness check.
It verifies all five desktop media units are active before temporarily stopping
them, checks no other camera owner remains, and runs a 60s camera session inside
an external 90s timeout. It restores those media units and compares GPSD,
monitor and sender state/PIDs/restart counts afterward, including failure paths.
Audio/microphone applications can pause during the trial. No unit is enabled,
disabled or installed. No GPS service is started or restarted.

Keep the Pi desktop browser/Codex closed to avoid the earlier memory/swap
exhaustion. Use the laptop UI and an operator SSH terminal. The new Pi2 GPS
monitor boot dependency on a GNSS tuner is a SEPARATE unresolved issue: an
unchanged inactive monitor after this trial is not proof of GPS operation.

Expected trial evidence: `CAMERA_PREVIEW=ACKNOWLEDGED` and a real matching image
in the Pi2 dashboard panel. Before detection, all six gauges must say Not
detected. After framing the correct six-gauge reference, an accepted cycle may
print `CAMERA_OBSERVATIONS=ACKNOWLEDGED`; verify its capture ID/UTC/image and
the six displayed readings, then visually compare the original needles.
Filming a laptop-screen photo is a preliminary alignment test only: glare,
focus, display scaling and moire can prevent registration. Do not lower the
original 12-match gate. Units/Low/Normal/High interpretation remain unverified.

At the end expect `MEDIA_RESTORE=PASS` and
`GPS_SERVICE_STATE_UNCHANGED=PASS`. A timeout, mismatched state or missing ACK
requires inspection, not an automatic retry or a claim of successful upload.

## Older strict accepted-only wrapper

The operator reported `candidate/camera/fast_reader.py` SHA256
`3754055ca2bb61b90cd93d416914f022ab95c790e13a81f72011be95d1ce79a2`
on Pi2. This is the original V5 baseline, NOT the separate indicative development
variant used by the first October20 uploader. Do not replace the working detector
with that variant merely to obtain an uploader. Neither its successful tests nor
this wrapper's synthetic tests establish physical Pi2 detection or upload success.

`publish_v5.py` verifies eight original runtime/helper/reference file hashes,
then wraps the existing `PersistentCamera.capture` and `run_cycle`. Original
detector, retries/geometry gates, calibration, state timestamps and source files
remain unchanged. It publishes only the accepted capture from THIS cycle, never
last-known state. Every preview and six-gauge packet uses that same accepted
image and same-request SensorTimestamp mapped via CLOCK_BOOTTIME. Missing/bad
sensor metadata, source age outside -2..10s, quality or image mismatch stops the
trial. No UTC replacement or enlarged freshness thresholds.

The unchanged baseline may reject an entire six-gauge cycle when one gauge fails;
that means no new preview/set, not fabricated partial or fresh old data. Review
quality observations become null/uncertain. Relative dial percentages and printed
air-pressure estimates remain UNVERIFIED, not Normal/Danger or calibrated units.

The package reuses the unchanged `dashboard_publish.py` transport from the
indicative uploader. The wrapper explicitly sets its own processor identity
`centrabus-fast-v5-3754055-upload-v1` BEFORE that helper signs the packet. The
server's enrolled processor must match; otherwise upload is rejected. The camera
secret and 24h enrollment expiry do not need changing. The public processor-only
SQL is `superbus/sql/2026-10-20-pi2-original-v5-processor-review-before-run.sql`.
It requires operator approval, matching active bus/devices, old expected processor,
unexpired enrollment and no previously accepted capture. Expect exactly one row;
zero/error means STOP, never force the update.

## Preparation and checks

From the Windows workspace root, `node qa/prepare-pi2-v5-camera-trial.cjs --prepare`
creates a new source-only directory under qa/.results with the wrapper, the
hash-pinned transport, this README and SHA256SUMS. No detector, credentials,
images, queues or configuration are included. No SSH, upload or API is executed.

After separate operator authorization for file transfer, copy only these public
files into a NEW Pi2 staging directory, not over the existing package. Transfer
the existing camera-private.json separately using SSH/SCP, never Git/chat. It
must be owned by `centrabus` with mode600. No Supabase server key goes to a Pi.
Verify the staged public SHA256SUMS before loading any staged Python module.

Read-only staged checks (examples; substitute exact reviewed absolute paths):

```bash
sha256sum -c SHA256SUMS
python3 -I -B publish_v5.py --runtime-dir /REVIEWED/ORIGINAL/candidate/camera \
  --private-config /PRIVATE/camera-private.json --check
```

`--check` reads baseline/config only: no camera/module initialization, output
directory or network. It must report V5_BASELINE=PASS and the required processor.
Do not log private configuration or hash material. A baseline mismatch requires
review of the actual changed file, not overwriting it or disabling the check.

## Later camera trial: separate physical approval required

Confirm exactly one camera owner. Existing rpicam/libcamera/other Python camera
processes must not be forcibly stopped or run beside this test. The per-user
wrapper lock prevents duplicate wrappers, not arbitrary camera applications.
Keep original GPSD/monitor PIDs and sender/queue state unchanged. Existing OS
Picamera2/OpenCV environment must work; no automatic dependency installations.

Keep START CAMERA running on the trusted laptop LAN. Use the exact numeric
127.0.0.1:3000 dashboard address if another wildcard server uses port3000.
The launcher does not start this Pi camera. With physical approval, a first
trial may use an external 90s timeout, one cycle and a NEW output directory:

```bash
timeout --signal=INT --kill-after=5s 90s python3 -I -B /STAGE/publish_v5.py \
  --runtime-dir /REVIEWED/ORIGINAL/candidate/camera \
  --private-config /PRIVATE/camera-private.json \
  --output-dir /NEW/EXPLICIT/TRIAL --cycles 1 --approve-camera-upload
```

No command above was run on a Pi during local development. Defaults are bounded:
one cycle; optional cycles1..60 and 120s checked between cycles. Use the external
timeout to bound a stalled native camera/detector call. Each accepted cycle makes
one synchronous, bounded3s upload attempt; failures stop, without disk upload
queues, retries, backlog or GPS changes. ACK is proof-checked by the transport,
but still compare actual Supabase row and dashboard preview/gauges capture ID,
capture UTC and correct bus. Turn Preview on for Pi2 in Live Camera View.

Rollback: stop only this newly authorized wrapper; restore original invocation.
No original detector file was replaced. Keep observation history and trial logs.
Do not alter GPS boot/services, Wi-Fi, sender, KML, SQLite or Pi1.

Timestamp provenance reference: the official Raspberry Pi Picamera2
`capture_file_` saves the image and returns metadata from the same request:
https://github.com/raspberrypi/picamera2/blob/main/picamera2/picamera2.py
