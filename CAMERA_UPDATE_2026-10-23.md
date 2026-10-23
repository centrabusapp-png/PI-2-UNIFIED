# V6 camera-calibration publication

The reviewed V6 candidate is available at
`candidate/camera/centrabus_live_runtime_v6_dev_20261023/`.
The runtime modules, frozen V5 support files, formal condition configuration and
actual reference JPG are copied byte-for-byte from the October 23 local V6
candidate. `source_provenance.json` records every copied hash. Calibration
constants and detector algorithms were not changed for publication.

One `pipeline.process(frame)` handles all six gauges. It retains V5 registration,
needle readers, numerical support checks and indicative status boundaries,
plus the already reviewed FRONT full-shaft proposal and failure-only dark REAR
recovery. The selected registration hypothesis is reused during the same-frame
model audit. Numerical REVIEW estimates remain separate from `published_value`.
Unsupported conversion values stay null. No historical reading substitutes for
a failed current capture, and there is one camera request per monitoring cycle.

## Existing development evidence

The prior exact 130-image regression covers 780 gauge cases: 324 AUTO, 456 REVIEW,
600 supported unverified numerical estimates and 180 retained N/A numbers. It
matches the previous 80-image and latest-50 annotations. The verified V5 caches
were reused, with 16 stratified full-pipeline replays. Publication did not rerun
the 130-image test or alter any dataset. The aggregate result is in
`evidence/development_130_summary.json` within the V6 folder.

Relative to raw V5, 17 FRONT lines change and one dark REAR line is recovered;
all remain REVIEW. Existing registration checks downgrade 36 raw-V5 published
readings to REVIEW. These are explicitly retained limitations, not measured
accuracy gains. Calibration-plane consistency and independent angle/physical
reference measurements remain unresolved. The independent testing dataset was
not consumed by this publication.

## Existing 60-cycle camera test

The October 23 log has 60 successful captures and 360 selected gauge lines,
320 AUTO and 40 REVIEW results, with zero unavailable estimates or stage errors.
Processing median is 0.804 s, mean 0.897 s, p95 1.537 s, maximum 1.794 s. Capture
cadence is approximately two seconds. Operator-reported Pi temperature is 52.1°C
and throttled=0x0. These describe that bounded run only.

| Gauge | AUTO | REVIEW |
| --- | ---: | ---: |
| FUEL | 56 | 4 |
| COOLANT | 57 | 3 |
| FRONT | 57 | 3 |
| REAR | 36 | 24 |
| BATTERY | 57 | 3 |
| OIL | 57 | 3 |

REAR has 23 short-shaft cases (about 42–72 px versus the inherited scale-adjusted
minimum of about 88–94 px). Registration-only cycle 28 accounts for its remaining
REVIEW; cycles 16 and 48 overlap both causes. All six gauges enter REVIEW at
16/28/48 because registration has 18 inliers / a 20.9% ratio / a 23.2% ratio,
respectively. The inherited minimums are 20 inliers and 25% for good registration.

REAR 7.52 and 7.84 kg/cm² at cycles 14/15 come from 44.8/42.0 px fits. FUEL 26.6%
at cycle 37 comes from a 43.7 px fit. Formulas match the existing conversions;
these suspicious fragment estimates are correctly REVIEW with null publication
values. No corresponding saved frames exist for visual adjudication. Only
cycles 1–10 were saved: REAR follows the blade in 1–9 and only its lower segment
in 10. Cycle 10 shows video-player controls, glare and an exposure increase.
This is a camera viewing a display/video, not independent physical-dial accuracy
validation. Lighting/display effects and registration instability are plausible;
physical camera movement is not established.

The sanitized aggregate and relevant cycle numbers are in
`evidence/live_60_summary.json`. New live captures and the raw log stay on the
operator's device and are not included in this commit.

## Verification and integration boundary

From the repository root, camera-free:

```bash
python3 -B -m unittest discover -s tests -p 'test*.py'
python3 -B -m unittest discover -s qa -p 'test_pi2_v6.py'
python3 -B -c 'import verify_package; from pathlib import Path; r=verify_package.verify(Path("CANDIDATE_SHA256.csv")); print(r); raise SystemExit(bool(r["failures"]))'
```

The V6 QA uses the bundled reference and a blank image only, with physical camera
imports blocked and image/network writes prohibited. It validates package
provenance, reference portability, unchanged conversion support, REVIEW/null
semantics, blank-frame abstention, explicit camera opt-in and the existing
aggregate evidence. It does not repeat the development archive regression.
Full `python3 verify_package.py` also verifies historical sources in a full
checkout; this publication used a sparse checkout and checked that the Git
`sources/` tree and its manifest were unchanged.

Publication checks passed: all 184 existing package tests, five new V6 checks,
163 candidate-manifest entries and 64 in-memory Python syntax checks. The existing
HTTP tests used their temporary localhost test server; production services and
hardware were not accessed. The unchanged frontend suite was not rerun because
Node.js is unavailable in this environment. The new V6 smoke check processes
only the bundled reference and a blank frame, with image output disabled.

V6 is ready for separately reviewed, quality-aware integration work. It is not
approved for unrestricted numerical reporting or automatic alarms. Future
consumers must retain original capture time, outcome, warnings, verification
flags and the distinction between `value` and `published_value`. Do not copy a
REVIEW estimate into an accepted backend measurement, invent confidence, or drop
the original quality flags. REAR fragment selection still needs targeted evidence.

The existing V5 upload adapters and latest system-session recovery changes remain
intact. No service, camera owner, GPS path, route, queue, device identity, private
configuration, production API, enrollment or database was changed. A Git push
publishes source only; it does not deploy or start the camera.
