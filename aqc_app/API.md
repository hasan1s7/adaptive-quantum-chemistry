# Local MVP runtime contract

Run from the repository root:

```bash
python -m aqc_app
python -m aqc_app --port 8766 --no-open
```

The server binds only `127.0.0.1`; there is no remote bind or alternate dataset
flag. The normal command opens a browser. `--no-open` prints the URL without
opening one. Viewing the saved experiment and running development replay
sessions use only Python's standard library. No quantum executable, job,
network request, or dependency installation occurs.

The separate historical HTML simulator remains inspectable client-side. This
runtime serves a new application whose unqueried reference labels remain in
the Python process. The old HTML, reference files, scientific source, and raw
per-molecule evaluator tables are outside the HTTP file allowlist. A validated
projection of already recorded per-molecule metrics is available separately.

## Data and scope

Startup verifies the original development features and reference file against
recorded hashes; original split membership; the unchanged oracle and worker;
all displayed candidate coordinates against the geometry asset and original
identity audit; and each served summary file against the complete v0.2 seal.
It also verifies the per-molecule evaluator table against that seal before
projecting its metrics, checks its exact pool/family/fold/configuration coverage,
and requires the projected rows to reproduce the saved aggregate accounting.
It loads 478 development molecules, 287 families, 4,761 conformers and 186,905
atom coordinate records. It never opens historical evaluation reference rows.

This startup check does not rerun the exhaustive scientific ledger audit. The
existing benchmark verification commands provide that separate check. Session
queries replay the existing development labels; they do not create fresh
validation data or modify the registered experiment.

## Endpoints

All POST bodies are JSON objects. IDs returned by the catalog and sessions are
opaque values to the client. The API version is 1.

| Request | Result |
|---|---|
| `GET /api/health` | Status, version, verified counts, scope and runtime limits |
| `GET /api/catalog` | Development molecule metadata and usable policy presets |
| `GET /api/molecules/{molecule_id}` | Cheap candidates, verified geometry, provenance and fold-selected policy presets; no reference energies |
| `GET /api/results` | Saved development aggregate, configuration summaries, paired comparisons, decision and fold choices |
| `GET /api/results/{name}` | Only `aggregate.csv`, `experiments.csv`, `paired_comparisons.csv` or `risk_vs_calls.png` |
| `GET /api/diagnostics` | Validated retrospective development metrics, scope, counts, roles, illustrative cases and provenance; no candidate truth identifiers or reference labels |
| `GET /api/diagnostics.csv` | The same sanitized metric rows as an attachment with exactly the documented columns |
| `POST /api/sessions` | Create a zero-charge session from `{molecule_id, config}` |
| `GET /api/sessions/{session_id}` | Current disclosed state |
| `POST /api/sessions/{session_id}/step` | One policy-requested query; body `{}` |
| `POST /api/sessions/{session_id}/run` | Complete the policy through its bounded fixed pool; body `{}` |
| `POST /api/sessions/{session_id}/query` | Manual session query; body `{candidate_id}` |
| `POST /api/sessions/{session_id}/finish` | Finish a manual session after a successful paid query; body `{}` |
| `POST /api/sessions/{session_id}/reset` | New run with the same molecule/config, retaining previous charged runs; body `{}` |
| `GET /api/sessions/{session_id}/export.json` | Current and previous runs, queried-only references and cumulative accounting |
| `GET /api/sessions/{session_id}/export.csv` | Charged/cached/rejected query ledger across those runs |
| `DELETE /api/sessions/{session_id}` | Close and release an in-memory session |

Policy config schemas are exactly those accepted by the unchanged
`aqc.oracle.policy_payload` for `full`, `fixed`, `adaptive` and `sequential`.
Manual sessions use exactly `{"kind":"manual"}`. Geometry and family metadata
are never passed to the policy worker. The molecule response's `policy_configs`
map uses keys `sequential`, `fixed`, `adaptive`, `full`, `manual`, and
`matched_simple`; its paid presets were selected using the training families
that exclude that molecule's validation fold. `matched_simple` is the exact
saved `choices["matched_simple"]["config"]` for that fold. It can be an adaptive
cheap-window policy and must not be replaced by fixed top-2. The catalog retains
the five original preset entries; the comparison workbench takes this exact
additional preset from the molecule response.

### Retrospective diagnostic contract

`GET /api/diagnostics` returns a JSON object with these top-level fields:

- `scope`: exactly `"development_family_cv_retrospective"`.
- `fresh_external_holdout`: always `false`.
- `counts`: integer `molecules`, `families`, `candidates`, `folds`, `rows`, and
  `roles`; the sealed source currently has 478, 287, 4,761, 5, 2,868, and 6.
- `roles`: `sequential`, `matched_simple`, `fixed_top_k`, `adaptive`,
  `full_rerank`, and `cheap_only`, in that order.
- `rows`: one row for every development molecule and role, sorted by molecule
  ID and the role order above.
- `cases`: retrospectively selected illustrations with `id`, `molecule_id`,
  `title`, and `description` only. The IDs are `rescue`, `waste`, `early_stop`,
  `shared_failure`, and `comparator_fallback`.
- `provenance`: source revision and hashes, including the evaluator table's
  SHA-256, scope, and explicit retrospective-selection/inference qualifications.

Each metric row has exactly these columns, also used by the CSV endpoint:

```text
molecule_id,family_id,fold_id,n_candidates,policy,config_id,expensive_calls,regret_kcal,success_1kcal,fallback,stop_reason
```

`fold_id`, `n_candidates`, and `expensive_calls` are integers; `regret_kcal` is
a finite nonnegative number; `success_1kcal` and `fallback` are JSON booleans.
Success uses the frozen evaluator's 1 kcal/mol threshold and numerical tolerance.
The family and fold identities come from the sealed development assignments.
Every paid role has at least one charged query. `cheap_only` has zero calls and
is an unverified diagnostic. Full rerank has exactly the pool's candidate count
in calls and zero regret. Rows with mismatched identifiers, configurations,
scope, coverage, accounting, or aggregate totals cause startup to fail.

The projection never includes `selected_candidate`, `best_pool_candidate`,
`query_order`, reference energies, or raw trace annotations. It is built from
an explicit field allowlist; unknown source columns are never copied. The raw
`per_molecule.csv` cannot be fetched through `/api/results` or another file route.

These are outcomes already observed during development family cross-validation,
not a fresh external holdout. Cases are selected to illustrate behavior rather
than to estimate its frequency. Filtering molecules, families, or cases does
not tune a policy or produce a new uncertainty estimate. Diagnostic reads do
not alter active paid sessions or disclose their unqueried reference labels.
Each comparison lane creates its own ordinary session and pays its own first
query, including when another lane has already queried the same candidate.

### State and accounting

A state contains:

- `session_id`, `molecule_id`, `config`, `mode`, `status`, `stopped`, `revision`.
- `queries`, `observations`, `best_verified`, `pending_candidate`,
  `pending_reason`, `policy_events`.
- `expensive_calls` for the current run and `session_expensive_calls` across
  all runs, including resets.
- `selected_candidate`, `stop_reason`, `fallback`, `evaluation`, `failure`.
- `reset_count`, `previous_run_count`, `limits`, `expires_in_seconds`, `scope`.

The initial policy may identify its next candidate but has no reference label
and zero charges. A valid first query costs one job even if its output fails.
Duplicate manual requests are logged cache hits and cost no additional job.
Unknown candidate requests are rejected without charge. A completed paid run
must select its best successfully queried reference, with candidate ID as the
deterministic reference-tie break.

`evaluation` is null until successful stopping. It then contains only
`regret_kcal`, `success_within_1_kcal`, and `selected_reference_kcal`. The server
never serializes the complete reference mapping or the evaluator's best
candidate. Exports retain only queried labels; an unfinished run's export
contains no regret. Reset does not erase cumulative charges or previous run
ledgers.

The unchanged `aqc/policy_worker.py` runs in the original isolated subprocess.
The adapter pauses its protocol immediately before each query. Each HTTP step
passes one observation to that worker and reads until its next query or final
decision. There is no duplicate acquisition formula in the application.

### Retries, failures and concurrency

Per-session locks serialize actions. On an action POST, a client can supply a
short ASCII `Idempotency-Key`. Repeating that key with the same action/body
returns its previously recorded state without another query; using it for a
different action is rejected. Keys are retained for the session's lifetime,
with a hard capacity of 128; they are never evicted and silently reused.
Creation does not have an idempotency guarantee. Clients should reconcile an
uncertain action with GET, or retry it with its original action key.

Protocol failure, timeout, EOF, broken pipe or cleanup failure marks the run
failed. HTTP 502 includes `{error, session}`; that session retains its paid
ledger, observed labels, failure stage/cause and available cleanup context.
GET/export can recover the same accounting after a disconnected response.
A failed run does not receive evaluator regret. No automatic retry purchases
an additional reference.

## Limits and retention

The defaults are 32 in-memory sessions, 16 concurrent HTTP request handlers,
32,768-byte JSON request bodies, five-second socket and worker-response
timeouts, and 15-minute idle session expiry. A janitor closes expired workers
even when there are no subsequent requests.

For a pool of `n` candidates, one session permits at most `10*n` charged jobs,
9 resets (10 total runs), `20*n+64` query events and `40*n+128` mutation
operations. These limits include repeated cached requests and old runs as
applicable. A fixed pool bounds each automatic run by its own candidate count;
there is no hard-coded ten-candidate policy assumption.

Sessions disappear when explicitly deleted, expired or the server stops.
Export or save a browser copy to retain a run. Browser-saved runs are read-only
records of labels previously disclosed by the server.

## HTTP boundary

Host must be `127.0.0.1` or `localhost` at the actual server port. Present Origin
headers must match that same HTTP origin. Cross-site API requests, duplicate
security headers, non-JSON mutation bodies, ambiguous/nonfinite JSON,
compressed/chunked bodies, oversized input and traversal paths are rejected.
Only the exact new app assets and summary exports listed in code are served.
Responses use no-store caching, same-origin resource policy and a CSP that
allows same-origin scripts without inline script execution.

This is a trusted local application. A user who already has filesystem access
can read the source data; the server is not a hostile-code operating-system
sandbox. The HTTP boundary still prevents the browser application from
receiving unqueried candidate labels for free.

## Executed test command

```bash
python -S -m unittest discover -s tests -p test_app_server.py -v
python -S -m unittest discover -s tests -p test_app_diagnostics.py -v
```

The tests exercise real HTTP requests and worker processes, including policy
parity, geometry coverage, family scope, charged reveals, full-rerank zero
regret, missing-output fallback, concurrent requests, idempotent retries,
disconnect recovery, reset accounting, expiry and subprocess faults.
The diagnostic suite additionally checks source sealing, exhaustive role and
pool coverage, family partition integrity, exact frozen comparator choices,
sanitized JSON/CSV parity, retrospective case predicates, and independent
query accounting across comparison lanes.
