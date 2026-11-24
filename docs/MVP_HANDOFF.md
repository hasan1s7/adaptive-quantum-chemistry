# AQC local MVP handoff

## Status and authorized repository

The local MVP adds a standard-library Python application, a browser interface,
launchers, diagnostics, and portable saved runs around the existing frozen
benchmark. It does not add a scientific experiment, change a policy, buy a live
quantum job, or establish that shape-aware acquisition helps.

The sole authorized publication destination is the private repository
[`hasan1s7/adaptive-quantum-chemistry`](https://github.com/hasan1s7/adaptive-quantum-chemistry).
No Nabu repository was accessed or modified. No hosted public deployment has
been performed or included in this handoff.

The publisher completed publication and verified the remote references and
contents:

| Reference or evidence | Verified identity | Meaning |
|---|---|---|
| Delivered implementation on `main` and `mvp/v0.3.0` | `ef85e831e3d10230182f14a4ded382afcea51d41` | Both remote references were read back at this implementation commit. |
| Exact tested implementation tree | `053128a37c90675be99383c8a48662bfbc7979c9` | 224 files; the delivered implementation tree was verified. |
| Complete v0.2 release branch commit | `63de0477259056decca619e20f66e06cf56d6fc9` | Preserved scientific baseline, including exact nontransport file and bounded transport checks. |
| Complete v0.2 release tree | `705386d5e96d131c748a5cd4f1bac07796267aee` | 182 original nontransport file hashes and all eight transport pieces matched exactly. |

`main` was fast-forwarded from
`cf43d5c47d520f2e865f6bccdcf6fc85acb8ed59` using the expected previous SHA,
then read back successfully. The structured receipt is
`verification/v03/publication.json`. A later documentation-only commit may
carry this receipt; the identities above deliberately name the delivered,
tested implementation rather than attempting to name the receipt's own
future commit. A complete distribution ZIP and its fresh-extraction checks
are separate from the completed repository publication.

## What is implemented

| Area | Implemented behavior | Boundary |
|---|---|---|
| Start | `python -m aqc_app`, POSIX launcher, and Windows double-click launcher; browser opens automatically unless `--no-open` is used. | An existing Python 3.10+ installation is required. App use needs no scientific package installation. |
| Replay | Real development molecules, fold-selected policy presets, manual reveal, step, complete policy, reset, paid-query ledger, final verified selection, and evaluator regret after successful stopping. | The Python process retains unqueried references. The unchanged isolated policy worker receives cheap candidates and oracle observations only. |
| 3D view | Actual verified coordinates, conformer selection, rotation, pan, zoom, display styles, and hydrogen controls. | Display bonds are a distance heuristic. Canvas projection is labeled when WebGL is unavailable; display geometry is not a new policy feature. |
| Measured results | Saved cross-validation results and the registered configuration sweep, filtering, risk/call visualization, uncertainty context, and CSV export. | Filters do not rerun selection or change the frozen measurements. The recorded negative primary comparison remains visible. |
| Saved runs | Browser-local read-only snapshots, JSON export/import, geometry, disclosed labels, and decision accounting. | Imported files are unverified user snapshots. They do not become benchmark evidence and cannot resume buying labels as an authenticated old session. |
| Diagnostics | Read-only runtime, asset, source/data hash, geometry, port, and evidence checks. | `app_ready` and `full_evidence_ready` are separate. Optional scientific dependencies are reported without being required to open the app. |
| Local HTTP boundary | Loopback-only serving, allowlisted files, Host/Origin checks, bounded inputs, per-session serialization, retry keys, expiry, and fault accounting. | Trusted local app; filesystem owners can still inspect repository data. This is not an operating-system sandbox or public multi-user service. |

The new runtime lives in `aqc_app/` and the browser interface in `app/`. The
launchers are `start-aqc.sh` and `start-aqc.cmd`; diagnostics live in
`scripts/doctor.py`. The endpoint and session contract is documented in
[`aqc_app/API.md`](../aqc_app/API.md).

## Open and diagnose the app

From the complete extracted repository:

```bash
python -m aqc_app
```

On Windows, double-click `start-aqc.cmd`. On Linux or macOS,
`sh start-aqc.sh` works even if extraction lost its executable permission.
Keep the terminal open; Ctrl+C stops the server. Its default address is
`http://127.0.0.1:8765/`. If automatic browser opening fails, use the address
printed in the terminal. For a conflicting port:

```bash
python -m aqc_app --port 8766 --no-open
```

For diagnostics without changing files or installing anything:

```bash
python scripts/doctor.py --no-port-check
python scripts/doctor.py --science --no-port-check --json
```

Live sessions reside in server memory, expire after 15 idle minutes, and end
when the server stops. Reset retains prior run accounting within that session.
Save or export disclosed work before closing the server. Browser-local copies
can be cleared by browser settings; exported files provide a separate copy.
Reloading the page does not promise automatic continuation of a live session.

The desktop server is bound to loopback. A phone cannot reach it through the
desktop's `127.0.0.1` address. Responsive layout work therefore does not deliver
a native mobile application or a remotely accessible service.

## Exact v0.2 recovery and unchanged scientific evidence

The starting scientific work was recovered from the previously delivered,
durable `adaptive-quantum-chemistry-v0.2.0.zip`, rather than treating the older
remote branch as the complete source of truth. The recovered archive has:

| Archive field | Verified value |
|---|---|
| Size | 120,792,586 bytes |
| SHA256 | `21e443c871cb9255ef8c30f5f89d130dcb466cd82d12a66b5c9962276181d828` |
| Durable artifact identifier | `libfile_c8b6b886a0388191a48ba5ebf57a7fed` |

The recovered baseline test output is retained at
`verification/v03/restored-baseline-tests.log`. Original v0.2 verification
records, results, seals, source pin, and split evidence remain preserved. The
archive is a recovery source for v0.2; it is not a claim that the new MVP files
are already published in that old archive.

### Transport compatibility

The expanded decision ledger is transported in eight pieces: seven of 10 MiB
and one of 1,800,145 bytes. The default restore command is:

```bash
python scripts/archive_evidence.py restore
```

It reconstructs `results/lab/decision_ledger.jsonl.gz`, exactly 75,200,465 bytes,
with the unchanged sealed SHA256:

```text
845a2c1846f8a1b5887134775c80c3f77f9efe4df3ef3fd18fd34fde4e8ccb07
```

The original four-piece manifest was preserved byte for byte at
`releases/v0.2.0/transport-original.json`. It records historical boundaries;
restore with the current manifest instead. No gzip recompression or scientific
record rewriting occurred. Complete temporary restoration, original-boundary
hash recovery, and corruption rejection were checked. Details and hashes are
in [`TRANSPORT_V03.md`](TRANSPORT_V03.md) and
`verification/v03/transport-compatibility.json`.

The saved-results app can start from its verified served summaries and
development inputs without restoring the entire ledger. Full scientific
evidence verification requires that ledger and must fail honestly if it is
missing or corrupted.

## Acceptance and remaining gates

The consolidated Python gate ran **216 tests: 215 passed and one native Windows
execution test was skipped**, with no failures. The **23 app-server tests**
also passed with site-packages disabled using `python -S`; they are a repeat
subset of the full suite, not additional unique tests. The **18 frontend
checks** and viewer smoke checks passed. Exact commands and outputs are in
`verification/v03/python-tests.log`, `frontend-tests.log`, and
`viewer-tests.log`. Package consistency passed in `dependency-check.log`.
Launchers, independent HTTP accounting/boundary checks, bounded ledger
transport, and real-API export/import round trips were also exercised.

The actual remote Chrome/Linux browser pass verified startup with zero
references and sequential replay on `astex_1g9v`: two paid calls, selected
`rmsd232-opt`, and regret 0.4040987970074639 kcal/mol. Saving and actual desktop
JSON download worked. The downloaded file contained exactly the two disclosed
observations, with no extra reference labels. A mismatched molecule-ID import
was rejected without erasing saved records; the valid downloaded file opened
as a visibly unverified, read-only snapshot with no query controls.

Manual replay on the same molecule selected `rmsd147-opt` through the 3D
conformer chooser. Its reference remained hidden until a paid reveal; Finish
selected it after one call with zero regret. Start over returned to zero
current calls and hidden references. Actual coordinates rendered in the
labeled Canvas fallback, with keyboard rotation, zoom, and camera reset
observed. Hardware WebGL remains untested in this browser.

A 360 px CSS iframe supported acquisition and displayed six CV points plus
the 1,020-configuration registry. Sequential policies at risk at most 5%
filtered to 492 rows. An actual desktop CSV download was inspected: all 492
rows were sequential, with minimum success 0.9518828451882845. At 320 px and
430 px iframe widths, document and scroll widths matched, with no page-level
horizontal overflow. The preview-only `srcdoc` history issue was fixed by
serving the frame at `/__qa__/app`; narrow replay and results navigation then
worked without changing production serving.

Two child-frame download-event captures timed out in browser automation.
Only normal desktop JSON/CSV downloads are claimed as captured and inspected;
physical mobile file export remains untested. The structured evidence and
export digest are in `verification/v03/browser-acceptance.json`, with detailed
scope in [`MVP_ACCEPTANCE.md`](MVP_ACCEPTANCE.md).

For development-only responsive QA, run
`python scripts/preview.py --port 4173 --responsive-check` and open
`http://127.0.0.1:4173/__qa__/responsive`. These optional QA routes are absent
from the normal `python -m aqc_app` runtime and remain loopback-only.

Native Windows double-click execution, native macOS behavior, physical
iPhone/iPad/Android acceptance, and hardware WebGL remain open because those
environments were not available in this acceptance. A shell test, DOM harness,
desktop narrow viewport, or software 3D fallback check does not close those
gates. The scheduled overnight fresh-package check remains outstanding;
private repository publication has passed and is recorded separately.

## Scheduled follow-up passes

`verification/v03/overnight-schedule.json` records two passes on
**November 24, 2026, around 02:00 and 05:00 America/New_York**. The scheduler
uses flexible timing; these are intended windows, not promises of exact start
times or proof that work already ran. The record is marked
`scheduled_not_executed` until execution evidence exists.

| Intended window | Priority | Evidence to leave |
|---|---|---|
| Around 02:00 Eastern | Recheck the exact private repository and published contents; run launch and current acceptance checks; address concrete blockers in startup, reference accounting, session recovery, import/export, and responsive controls. | Actual commands, revision, logs, browser observations, fixes, unresolved gates, and readback of the published implementation. |
| Around 05:00 Eastern | Recheck the delivered package from a clean extraction; verify current seals and transport restoration; finish remaining available-device UI/error paths and publish an honest handoff. | Clean-package results, final hashes, tested platform scope, known issues, and the exact delivered commit. |

Both passes are limited to this MVP and its delivery. Preserve frozen
scientific files and historical evaluation. Do not add shape probes, neural
models, live reference calculations, paid compute, public deployment, outreach,
or Nabu changes. If a platform is unavailable, retain the open acceptance gate
instead of replacing it with a claim from another platform.

## Publication receipt

**Publication passed.** The delivered implementation commit is
[`ef85e831e3d10230182f14a4ded382afcea51d41`](https://github.com/hasan1s7/adaptive-quantum-chemistry/commit/ef85e831e3d10230182f14a4ded382afcea51d41),
with remote `main` and `mvp/v0.3.0` readback confirmed. The complete v0.2 release
baseline and its exact nontransport/transport hashes were also verified. See
`verification/v03/publication.json` for immutable identities and scope.

The remaining delivery work is the distribution ZIP receipt and scheduled
clean-extraction verification. Native-device and hardware-WebGL gates remain
open. Publication of a private source repository does not constitute a hosted
public application, a new scientific result, or proof of those device gates.
