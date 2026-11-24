# Local MVP acceptance

This is the historical **v0.3** acceptance record. The current comparison
workbench has a separate [v0.4 acceptance record](MVP_V04_ACCEPTANCE.md).

This acceptance contract covers the local saved-results application and its
paid-query simulator. The recorded benchmark, source pin, family split,
historical evaluation, and v0.2 scientific files remain frozen. A working
interface does not establish a new scientific result.

## Current acceptance status

The local implementation is complete enough to exercise the launch, replay,
results, and saved-run workflows. The available automated/browser checks,
private repository publication, and today's clean ZIP extraction checks have
completed. Native-device acceptance remains separate; this record identifies
the actual scope of each gate.

| Gate | Status at this handoff | Evidence or next required action |
|---|---|---|
| Recovered scientific baseline | Restored from the exact durable v0.2 ZIP; existing scientific records retained. | `verification/v03/restored-baseline-tests.log`; archive identity in `MVP_HANDOFF.md`. |
| Launchers and standard-library app runtime | Component and independent real HTTP checks executed on Linux. | Commands and observed behavior below; native Windows/macOS acceptance remains pending. |
| Server reference boundary | Real request and worker checks passed in the full suite and in a separate standard-library run. | `verification/v03/python-tests.log`; the 23 tests rerun with `-S` are already included in the unique full-suite count. |
| Frontend behavior and portable run files | 18 frontend checks, viewer smoke checks, and real-API export/import round trips passed; actual browser download and valid/invalid imports were exercised. | `verification/v03/frontend-tests.log`, `viewer-tests.log`, and the browser observations below. |
| Ledger transport | Eight bounded pieces restored byte for byte; transport tests passed. | `verification/v03/transport-compatibility.json` and `transport-tests.log`. |
| Available desktop/responsive browser acceptance | **Completed for the observed remote Chrome/Linux paths.** Desktop and narrow-iframe replay, manual acquisition, Canvas 3D controls, results/filtering, reset, saving, actual desktop JSON/CSV downloads, and valid/invalid imports passed. | `verification/v03/browser-acceptance.json`; iframe download-event capture and physical-device limits are explicit below. |
| Native Windows/macOS and physical mobile acceptance | **Pending; devices unavailable in this workspace.** | Execute the device cases below on those platforms. |
| Hardware WebGL | **Pending.** The browser exercised the labeled Canvas fallback. | Native graphics acceptance needs its own evidence. |
| Clean distribution ZIP extraction | **Passed today.** All 226 manifest-listed file hashes matched; a path containing spaces supported standard-library diagnostics, actual server startup, and full reranking with zero regret. | `verification/v03/package-receipt.json`, `clean-package-doctor.json`, and `clean-package-server.log`. The 227th bundled file is `DISTRIBUTION.json` itself. |
| Consolidated automated test gate | **216 Python tests run: 215 passed, one native Windows test skipped.** | `verification/v03/python-tests.log`; no failures. Frontend and viewer checks are reported separately. |
| Private repository publication | **Passed.** Remote `main` and `mvp/v0.3.0` were read back at delivered implementation commit `ef85e831e3d10230182f14a4ded382afcea51d41`. | `verification/v03/publication.json`; exact tested tree `053128a37c90675be99383c8a48662bfbc7979c9` contains 224 files. Later documentation-only commits may follow. |

No hosted public deployment has been performed. The scheduled follow-up passes
are around 02:00 and 05:00 America/New_York on November 24, 2026, with flexible
scheduler timing. Their priorities and evidence requirements are in
`MVP_HANDOFF.md`; a scheduled pass is not an executed check.

## Launch contract

The distribution runs directly from its extracted folder. It requires an
**already installed Python 3.10 or newer** and a browser; it does not require
RDKit, NumPy, Matplotlib, Node, a virtual environment, or a package install to
open the app. The optional scientific replay environment remains pinned in
`requirements.txt` and uses the recorded Python 3.12 environment.

| Environment | Start | Expected behavior |
|---|---|---|
| Linux or macOS terminal | `./start-aqc.sh` | Starts the local server and opens the browser. `sh start-aqc.sh` also works if execute permission was lost during extraction. |
| Windows | Double-click `start-aqc.cmd` | Starts the local server, opens the browser, and keeps the console available. Failures remain visible until acknowledged. |
| Any compatible Python | `python -m aqc_app` | The same application without the wrapper. |
| Headless/automated use | `python -m aqc_app --no-open --port 8766` | Starts on the selected loopback port without invoking a browser. |
| Diagnostics | `python scripts/doctor.py` | Checks runtime, required assets, scientific source hashes, data, geometry, evidence seals, and the default loopback port. |
| Optional replay setup inspection | `python scripts/doctor.py --science --json` | Adds installed-version metadata for pinned scientific packages; missing packages do not make them app prerequisites. |

Both launchers work when invoked from another directory and preserve the
server's command-line flags. `AQC_PYTHON` can select one existing executable
path, including a path containing spaces; it is not a shell command or a
place to add arguments. `AQC_NO_PAUSE=1` disables the Windows failure pause
for automation. Neither launcher installs a runtime or a package.

The Windows wrapper disables Python install-manager automatic installation
and clears the legacy launcher's install-on-demand environment variables.
These controls follow the official
[Python Windows launcher documentation](https://docs.python.org/3.14/using/windows.html#python-install-manager)
and its [legacy install-on-demand section](https://docs.python.org/3.14/using/windows.html#install-on-demand).
The wrapper is not a bundled Windows executable: Python must already exist.

The server binds only to `127.0.0.1`. No deployment, LAN exposure, quantum
executable, paid compute, or outside API is part of this acceptance. Keep the
terminal open while using the application; Ctrl+C stops it. A browser window
that fails to open automatically is recoverable using the local address
printed by the server.

## Required acceptance cases

Record actual evidence beside each case when executing acceptance. A test
implemented in the repository is not, by itself, a claim that every device
has passed it.

| Area | Acceptance case | Required evidence |
|---|---|---|
| Start | Start from a folder containing spaces, while the shell is in another directory. | App root loads; local assets and API calls succeed. |
| Start | Start with scientific site-packages unavailable. | Saved results and a paid-query trial work; no dependency-install attempt. |
| Start | Start with an occupied port, missing Python, missing assets, or a corrupt required artifact. | Actionable error and nonzero exit; no silent fallback to invented data. |
| Start | Use `--no-open` and an alternate port. | No browser invocation; only the requested loopback address listens. |
| Session | Open a molecule and policy. | Zero paid calls, no reference observations, and no evaluator regret before acquisition. |
| Session | Step once, then continue the policy. | Each new valid reference costs one job; the ledger reflects exact order. |
| Session | Reveal manually, repeat a query, switch conformer, and stop. | Cached repeats add no charge; geometry browsing adds no charge; final selection is the best successfully queried reference. |
| Session | Reset a trial or change molecule/policy. | Fresh current-run accounting and hidden references; reset retains cumulative charges and previous runs in that server session; existing measured results remain unchanged. |
| Session | Reload an active or saved trial. | Live sessions are ephemeral; reopening a saved run is read-only. Expiry, server shutdown, and the absence of automatic live-session resumption are clear. |
| Results | Inspect all 1,020 recorded configurations and the six CV procedures. | Filtering changes displayed rows only; the negative recorded primary comparison remains visible. |
| Results | Inspect historical evidence. | No historical raw-label acquisition or tuning controls. |
| 3D | Rotate, pan, zoom, change conformer/style, and toggle hydrogens. | Actual verified coordinates respond; Canvas fallback is labeled when WebGL is unavailable. |
| Export | Export a query trace and a saved run, then inspect/import it. | Molecule, policy, charges, queried observations, selection, stop reason, and evaluation scope are preserved. |
| Export | Export before stopping. | Unqueried reference labels and evaluator regret are absent. |
| Export | Import malformed, oversized, internally inconsistent, or schema-incompatible content. | Clear rejection; existing session and evidence are unchanged. A valid imported snapshot remains unverified and cannot become benchmark evidence. |
| Failure | Request an unknown candidate, duplicate action, invalid policy, or expired session. | Charged work is not erased; errors do not expose an unqueried reference. |
| Boundary | Send cross-origin requests, an invalid Host, traversal paths, or mutations with unknown/malformed session IDs. | Rejection with no mutation or unauthorized file response; only allowlisted application assets and measured summaries are served. |
| Mobile | Exercise navigation, viewer gestures, selection, step/run/reset, tables, and exports at 320–430 px widths. | Controls remain reachable without page-level horizontal overflow; changing counters remain readable. |
| Accessibility | Complete a trial with keyboard controls and visible focus. | Native controls have useful labels; updates are announced without continuous animation chatter. |
| Offline | Disconnect external networking after extraction. | App launch, local assets, geometry, saved-result viewing, and replay remain functional. |

## Automated checks and evidence limits

`python -m unittest tests.test_launcher -v` exercises launch argument and path
handling, Python discovery, missing/incompatible runtime errors, preserved
exit codes, standard-library diagnostics, source/hash rejection, optional
scientific dependencies, and port collisions. The Windows execution test
explicitly skips on non-Windows hosts. Static inspection of the batch script
does not count as native Windows acceptance.

The doctor is read-only. It never restores a missing ledger, rewrites a seal,
installs software, downloads a dataset, or reruns quantum calculations. If a
Git clone contains the transport chunks but lacks the original ledger, it
points to the explicit `python scripts/archive_evidence.py restore` command.
The report distinguishes `app_ready` from `full_evidence_ready`. A Git clone
with the verified served summaries and development inputs can open the app
before restoring its large ledger. A missing or corrupted full ledger still
produces a failed complete-evidence check and a nonzero doctor exit; it is not
silently certified. The app's own startup remains based on its served inputs.
Checksums detect differences from the recorded artifacts; they are not an
external audit or a guarantee that the original quantum jobs converged.

The current transport uses seven 10 MiB pieces plus one smaller piece. It
restores the same 75,200,465-byte ledger with SHA256
`845a2c1846f8a1b5887134775c80c3f77f9efe4df3ef3fd18fd34fde4e8ccb07`.
The old four-piece manifest is preserved as a historical record at
`releases/v0.2.0/transport-original.json`. Use the current default restore
command, not that archived manifest. See `TRANSPORT_V03.md` for the bounded
transport rationale and exact verification record.

The app keeps live sessions in server memory. Idle sessions expire after 15
minutes, and stopping the server discards them. The browser can save a read-only
snapshot in its own local storage or export a JSON file containing coordinates
and only disclosed reference observations. Browser storage can be unavailable
or cleared; it is not a durable server database. Imported snapshots have no
cryptographic claim of scientific validity, and their reported regret is not
independently recomputed from unqueried labels. They remain visibly distinct
from verified measured results.

Source and evidence checks must continue passing after all packaging/UI
changes. New app files live outside the frozen scientific module set. No
package-install configuration is required for this launch route, so there is
no new build-backend download or incomplete wheel containing only source but
omitting the required saved evidence.

## Installed-device acceptance remains separate

| Target | What can be established in this workspace | Remaining device acceptance |
|---|---|---|
| Linux / current available browser | Local launch, HTTP/API tests, and browser interaction can be executed here. | Fresh extraction and launch on another user's installation. |
| Windows / Edge or Chrome | Batch-file contract tests and a Windows-only automated test are included. | Actual double-click launch, Python discovery, firewall/browser prompts, shutdown, and export on Windows. |
| macOS / Safari or Chrome | POSIX shell argument/path tests exercise the launcher design. | Native launch, browser handoff, file permissions/quarantine, graphics, and exports on macOS. |
| iPhone / iPad / Android | Responsive viewport and pointer-layout checks can be performed in a desktop browser. | Physical touchscreen, mobile browser graphics, file export/import, and an authorized way to reach a server on that device. |

A loopback-only desktop server is not reachable from a different phone by
typing the desktop's `127.0.0.1` address. Responsive layout support therefore
does not imply an installed mobile application or a remotely hosted service.
Those are separate delivery decisions and have not been silently enabled.

## Execution recorded in this workspace

The following packaging and boundary checks were actually run on Linux with
Python 3.12.14. They do not claim acceptance on the untested devices above.

| Command or check | Observed result |
|---|---|
| `.venv/bin/python -m unittest discover -s tests -v` | 216 tests run: 215 passed, one native Windows execution test skipped; exit 0. Log: `verification/v03/python-tests.log`. |
| `python -S -m unittest discover -s tests -p test_app_server.py -v` | All 23 app-server tests passed with site-packages disabled; exit 0. These repeat tests in the 216-test suite, not 23 additional unique tests. Log: `verification/v03/python-tests.log`. |
| `node tests/test_app_frontend.js` | 18 frontend checks passed. Log: `verification/v03/frontend-tests.log`. |
| `node tests/test_molecule_viewer.js` | Viewer smoke checks passed for geometry/math, Canvas/WebGL resource paths, camera interactions, styles, hydrogens, animation, conformer switching, and cleanup. Log: `verification/v03/viewer-tests.log`. This harness is not physical graphics-device acceptance. |
| `.venv/bin/python -m pip check` | No broken requirements found; exit 0. Log: `verification/v03/dependency-check.log`. |
| `python -m unittest tests.test_launcher -v` | Linux component checks passed; the native Windows execution test was explicitly skipped. This is a component-run result, not the final release suite total. |
| `sh -n start-aqc.sh` | Shell syntax accepted. |
| `python -S scripts/doctor.py --science --no-port-check` | App prerequisites and complete scientific evidence passed with site-packages disabled. Optional scientific distributions were unavailable in this mode; that did not block the app. |
| `./start-aqc.sh --port 8767 --no-open` | Actual server started, served the app and verified development pools, completed the HTTP checks below, and stopped cleanly with SIGINT. |
| `python -S -m aqc_app --port 8767 --no-open` | The same real startup, replay, and boundary checks passed without site-packages. |
| `python -m unittest tests.test_evidence_transport -v` | Current bounded transport, complete reconstruction, idempotence, corruption rejection, and historical boundary checks passed; log in `verification/v03/transport-tests.log`. |

The independent HTTP checks observed zero references and no regret in a new
session; one charged query after a step; no additional charge on an idempotent
retry; ten calls and zero regret for full reranking of `astex_1unl`; and zero
current calls with ten lifetime calls retained after reset. Manual repeat
queries remained cached and the final candidate was reference verified.

Nine rejection paths were exercised against each launched server: direct
reference-file access (404), dot traversal (400), percent-encoded traversal
(400), foreign Host (403), foreign Origin (403), cross-site API metadata (403),
duplicate JSON keys (400), wrong request media type (415), and oversized JSON
(413). These are concrete tested paths, not a claim of exhaustive security
review. The authoritative endpoint test suite is `tests/test_app_server.py`.

## Browser observations recorded during final acceptance

The publisher exercised the current app in remote Chrome on Linux. Responsive
checks used CSS-width iframes, not physical phones. These are observed
interface outcomes, separate from the DOM and HTTP test suites; the structured
record is `verification/v03/browser-acceptance.json`.

| Interaction | Observed result |
|---|---|
| Desktop startup | App loaded with zero paid references in the new session. |
| Sequential step, then complete policy | For molecule `astex_1g9v`, two calls were charged; the selected candidate was `rmsd232-opt`, with evaluator regret 0.4040987970074639 kcal/mol after stopping. |
| Save and download | Saved-run records appeared; an actual desktop run JSON download contained `astex_1g9v`, two charges, exactly two reference observations, no extra labels, and the recorded regret. Snapshot authenticity was explicitly false. |
| Invalid file import | A JSON file with a mismatched molecule ID was rejected, preserving existing saved records. |
| Valid downloaded-file import | The downloaded JSON imported and opened automatically as a read-only, unverified snapshot. Its headings communicated that scope, and query controls were unavailable. |
| 360 px responsive iframe | Step and complete-policy controls worked in the constrained CSS viewport. |
| Narrow measured results | The 360 px frame rendered six CV points and the 1,020-configuration registry. Filtering for sequential policies with risk at most 5% returned 492 configurations. |
| Actual desktop CSV download | The downloaded filtered CSV contained 492 rows, all sequential, with minimum success 0.9518828451882845. Its SHA256 is `00ece925b73d06654500e03e9a98ab4e4fb3c5f9e2b633a5545c53943e299cf0`. |
| 320 px and 430 px responsive iframes | At 320 px, document width and scroll width were both 305 px; at 430 px, both were 415 px. The 15 px difference was the scrollbar. No page-level horizontal overflow was observed. |
| Manual acquisition and conformer selection | In `astex_1g9v`, the 3D conformer chooser selected `rmsd147-opt`. Reference energy stayed hidden until one paid reveal. Finish selected that queried candidate with one call and zero regret. |
| Actual 3D view | Verified coordinates rendered in the visibly labeled Canvas 3D fallback. Keyboard arrow rotation, `+` zoom, and camera reset responded. Hardware WebGL was not tested in this browser. |
| Start over | After the manual run, Start over returned to zero current calls, ready state, and hidden references. |
| Responsive QA navigation fix | Replacing the preview-only `srcdoc` app frame with `/__qa__/app` resolved the observed history/navigation problem; narrow replay and results navigation were then exercised. Production serving remained unchanged. |

Two iframe download-event capture attempts timed out in the automation. No
successful child-frame file capture is claimed. Normal desktop JSON and CSV
downloads were captured and inspected successfully. This limitation does not
establish physical mobile file export support; that gate remains open.

The remaining platform checks are native Windows/macOS, physical mobile, and
hardware WebGL. Today's package extraction and private repository publication
have passed with their own receipts. The overnight follow-up is still scheduled
to independently audit useful incomplete available gates; it is not evidence
that those future checks have already run. None constitutes a hosted public
deployment.

For the optional developer layout harness:

```bash
python scripts/preview.py --port 4173 --responsive-check
```

Open `http://127.0.0.1:4173/__qa__/responsive`. Its same-origin app frame and
width buttons are for browser QA only. The normal `python -m aqc_app` launch
does not enable these QA routes. The harness is bound to loopback and does not
turn the application into a hosted or mobile service.

## Published implementation and clean-package acceptance

The automated totals and available-browser outcomes above are recorded
executed gates. The delivered implementation commit
`ef85e831e3d10230182f14a4ded382afcea51d41` and its exact tested 224-file tree
`053128a37c90675be99383c8a48662bfbc7979c9` were published and read back on remote
`main` and `mvp/v0.3.0`. The publisher fast-forwarded `main` from the expected
`cf43d5c47d520f2e865f6bccdcf6fc85acb8ed59`. The complete v0.2 release branch
commit `63de0477259056decca619e20f66e06cf56d6fc9`, tree
`705386d5e96d131c748a5cd4f1bac07796267aee`, preserves 182 original
nontransport file hashes and all eight exact transport pieces.

`verification/v03/publication.json` is the publication receipt and supersedes
earlier checkpoint records that marked publication pending. It identifies the
tested implementation; a later documentation-only commit may carry this
receipt without changing that identity. No Nabu repository was accessed or
modified.

The complete distribution ZIP was then created from documentation commit
`3824f99607f7f21ca70b621724bca3661622ccce`, tree
`bfa1dabb635d831f30fce181628648c3ef8885cf`, without further app-source edits.
Its 225 Git files, restored scientific ledger, and `DISTRIBUTION.json` comprise
227 bundled files. The archive is `adaptive-quantum-chemistry-v0.3.0.zip`,
196,073,526 bytes, SHA256:

```text
770d9427fd3bd2298d775e55dbd78089b4925aac539640be7a3640157ec2e2c5
```

Fresh extraction into a temporary path containing spaces verified all 226
file hashes listed in `DISTRIBUTION.json`; the manifest does not hash itself.
The following checks then passed against that extracted copy:

| Executed check | Observed result |
|---|---|
| `python3 -S scripts/doctor.py --json --no-port-check` | Exit 0; `app_ready`, `full_evidence_ready`, and overall `ok` were true. No files were modified and no network access occurred. |
| `python3 -S -m aqc_app --no-open --port 53273` | Started on an OS-allocated loopback port with site-packages disabled; all 478 development pools were available. The actual port is recorded in the server log. |
| Create an `astex_1g9v` session with `{"kind":"full"}`, then run it through the HTTP API | Initial session had zero references; full reranking charged ten calls and finished with zero regret. |
| Stop the extracted app with SIGINT | Server and workers shut down; exit 0. |

The original post-creation receipts are copied verbatim to
`verification/v03/package-receipt.json`, `clean-package-doctor.json`, and
`clean-package-server.log`. They were produced after archive creation and are
intentionally outside that ZIP; recording them does not require a rebuild or
a self-referential archive hash. The existing ZIP's size and SHA256 were also
independently rechecked when the receipts were copied.

Today's ZIP extraction gate is closed. Scheduled overnight work should
independently inspect useful incomplete available gates and any concrete
remaining issue, rather than claim a future run or reopen the completed gate
without cause. Native-device and hardware-WebGL gates remain open. No hosted
public deployment or additional scientific experiment is claimed.
