# App source publication checks

This update publishes the prepared Wi-Fi app and the latest indicative-status
camera runtime, with self-contained tests and public usage guides. Existing
source archives, GPS code, identity configuration and previous camera versions
are preserved. Local environment reports and live image sessions are excluded.

Passed software checks:

- 184 package Python tests under the source-only audit guard.
- 20 frontend tests against the actual app with synthetic DOM and transport.
- 61 camera tests and 28 known-geometry checks, with one private-survey test skipped.
- Formal condition CLI validation with zero approved regions.
- SHA256 verification of all candidate manifest entries.

The original camera workspace additionally passed its 80-image/480-candidate
regression and 658-detection/59,475-field numerical preservation comparison.
These are software equality checks, not physical calibration or acceptance.

Detailed test logs and audit records remain local and are excluded from this
public app update. No physical
camera, Wi-Fi trial, real backend check-in, GPS sender, production service or
Supabase operation was performed during publication.

The internal calibration survey is excluded. Runtime detector and formal
configuration source are unchanged; only its survey-specific test is skipped.
