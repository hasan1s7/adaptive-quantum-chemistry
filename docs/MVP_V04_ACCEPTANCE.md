# v0.4 acceptance and handoff

The v0.4 local workbench adds independent policy comparisons, a retrospective
failure explorer, and explicit recovery from unavailable sessions. The
scientific engine and recorded experiments remain unchanged. The application
starts with `python -m aqc_app`; an existing Python installation is required.

## Executed checks

The recorded environment is Linux, Python **3.12.14**, Node **24.22.3**, and
remote Chrome. Scientific dependencies match the exact pins in
`requirements.txt`. The application and its real HTTP checks also run with
Python site-packages disabled.

| Gate | Executed outcome | Evidence |
|---|---|---|
| Full Python suite | **232 tests run: 231 passed, one native Windows execution test skipped.** | `verification/v04/python-tests.log` |
| Existing frontend contracts | **19 checks passed.** | `verification/v04/frontend-tests.log` |
| Independent comparison controller | **20 checks passed**, including unknown outcomes, stale responses, independent charges, retained histories, expiry, and archive limits. | `verification/v04/comparison-tests.log` |
| Comparison/explorer view contracts | **8 checks passed**, including all 478 real pairs and recovery controls. | `verification/v04/workbench-ui-tests.log` |
| Actual comparison HTTP replay | **20 policy–molecule replays**, **96 offline charges**, exact parity with the sealed per-molecule calls, regret, fallback and stop reasons. | `verification/v04/comparison-replays.json`, `comparison-http.log` |
| Actual expiry HTTP regression | One paid query followed by real one-second server expiry; explicit archival and a fresh zero-call comparison pass without erasing incomplete accounting. | `verification/v04/expiry-recovery.json`, `expiry-recovery.log` |
| Original coordinate renderer | Viewer smoke checks pass; original renderer source unchanged. | `verification/v04/viewer-tests.log` |
| Standard-library diagnostics | App data, geometry, source seals, and restored full evidence pass. | `verification/v04/doctor.json` |
| Browser interaction | Independent reveal, per-lane stopping, cross-lane privacy, exact comparator fallback, retained accounting, filters, family selection, existing results, 3D controls, JSON and CSV downloads exercised. | `verification/v04/browser-acceptance.json` and downloaded browser reports |
| Narrow layout | Compare and diagnostics views checked at iframe widths **320, 360, 430 px**, without page-level horizontal overflow. | `verification/v04/browser-acceptance.json`, `browser-narrow.jpg` |
| Frozen scientific preservation | **179 protected tracked files** match the v0.3 baseline. Restored ledger SHA-256 remains `845a2c1846f8a1b5887134775c80c3f77f9efe4df3ef3fd18fd34fde4e8ccb07`. | `verification/v04/preservation.json`, `protected-baseline.json` |
| Clean downloadable package | **261 file hashes verified** after extraction into a fresh folder containing spaces; doctor passes and all **20 HTTP replays / 96 charges** reproduce with Python site-packages disabled. | `verification/v04/package-receipt.json`, `clean-package-doctor.json`, `clean-package-replays.json` |

The 16 diagnostic Python tests are already included in the full-suite total.
The 19 + 20 + 8 JavaScript suites comprise **47 checks**. The actual expiry
HTTP regression and coordinate-renderer smoke suite are reported separately.
Repeated verification runs are not additional independent tests or scientific
replications. Commands actually executed are in `verification/v04/commands.txt`.

## What a comparison guarantees

Each lane has a distinct server session and the same ordered candidate pool.
Creating a lane is free; the first reference query is charged. Revealing a
candidate in one lane does not reveal it in another. A lane's completed
selection is its best successfully queried reference, with the evaluator
regret supplied only after its own stop. The real HTTP runner checks this
against the original per-molecule result for five selected cases.

The matched simple role uses the exact frozen fold choice. In the
`omegapdb_1yc4` case it uses ten calls with a full-rerank fallback, while fixed
top-2 uses two. No comparator identity is replaced to make a result look better.

The comparison controller prevents overlapping mutations and applies a
distinct idempotency key to each paid operation. It reconciles lost responses
with GET, never an automatic paid retry. A confirmed expired/missing session
can be explicitly archived. Any unresolved cost remains recorded as a
last-confirmed lower bound, including after a replacement comparison starts.
The real TTL regression and UI DOM check cover this recovery; a 15-minute
real-browser expiry walkthrough is not claimed.

The explorer's JSON/CSV projection is metrics-only: no evaluator-best or
selected-candidate IDs, query order, reference-energy labels, or arbitrary
trace annotations. Its 2,868 rows are checked against the existing seal and
validated for molecule/role coverage, family/fold identities, exact frozen
configs, paid-query accounting, and aggregate totals. Raw evaluator files are
not served by the local app.

## Browser findings and practical limits

The browser reproduced the rescue case with calls **2 / 2 / 3 / 10** and
regrets **2.008453 / 2.008453 / 0 / 0** for fixed, matched, sequential and full.
It also reproduced the comparator-fallback case with calls **2 / 10 / 2 / 10**
and all-zero regret. A narrow-frame early-stop case showed regret only in the
lane that had actually stopped.

JSON and CSV were downloaded through actual browser controls, read back, and
checked against the four lane ledgers. The filtered diagnostic CSV contains
the selected paired row and explicitly declares retrospective scope. The
checked examples are illustrations chosen after seeing the results.

The observed renderer was the labeled **Canvas projected-3D fallback**, using
the actual verified coordinates. Wireframe, hydrogen visibility, keyboard
rotation and zoom worked. Hardware WebGL was unavailable. Narrow iframes
test CSS layout; their desktop scrollbar reduces the usable document width
by 15 px. They do not establish physical-phone acceptance.

Native Windows/macOS, physical mobile devices, hardware WebGL, and hosted
service operation remain untested here. The app binds to loopback, requires
an existing Python runtime, and keeps live sessions/history in memory. Export
before leaving or reloading the page. Comparison reports are portable user
snapshots; the existing single-run import control does not import comparison
reports. No hosting or deployment was performed.

## Overnight record and this delivery

At the start of this work, private `main` still pointed to
`6d81701875b996426c07f383789767ea423a899a`. The overnight automation was disabled
with no next run. Its available record showed one run scheduled for
**02:00 Eastern on November 24, 2026**, started at 02:02:27 and completed at
02:04:38, marked `requires_user_action`, with no usable result text. This is
not evidence that either planned overnight implementation pass succeeded.
The v0.4 changes and checks documented here were completed in the active
session. No new overnight schedule was created.

Repository publication and clean-package identities are recorded separately
in `verification/v04/publication.json` and `package-receipt.json`. The source
cut is `4d035e3e2113d11e740b6498a03bfeb39a7e3c2a`, with verified tree
`ec33dde3bea883e1c1e7dd390cf657969ddaccab`. The complete ZIP contains 260 tracked
files, the restored ledger, and `DISTRIBUTION.json` (262 files total). It is
196,250,304 bytes with SHA-256
`cae22f26cedbe78e571b831a376ca9ca8d226bf3048a43ef3321aa08d40522ad`.

The archive identifies its precise source cut. This updated acceptance record
and the clean-package receipts are published afterward without changing
application code. The clean doctor retains the historical v0.1 ancillary-file
coverage warning: those extra historical artifacts were not covered by that
original evaluation seal. Both the app and the full v0.2 evidence are ready.
Repeated clean-package replays are product verification, not extra scientific
experiments.

## Scientific decision

The frozen primary comparison remains **455/478 successes and 973 calls**
for sequential feedback versus **457/478 and 964 calls** for the matched
simple baseline. Observed call saving is **−0.934%**, with the recorded paired
family-bootstrap interval **[−5.824%, +3.444%]**. The combined target is not met.

The new views make the failures inspectable. They do not measure a shape
probe's value. The release adds no configurations or new independent
validation population; all acquisition demonstrations are offline replay.
