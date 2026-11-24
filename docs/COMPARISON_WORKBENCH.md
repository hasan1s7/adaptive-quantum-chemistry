# Comparison workbench · v0.4

The workbench makes a measured acquisition decision inspectable: compare the
same conformer pool under four independently charged policies, then connect
the decisions to the frozen family-CV evidence. Launch it with
`python -m aqc_app` from the complete repository. Python's standard library
is sufficient; JavaScript runs locally in the browser with no external CDN.

## Compare the same pool

Open **Compare policies**, select a development molecule, and load the
comparison. The four lanes start with zero calls. Each lane has a separate
server session and hidden-label oracle, and receives the same cheap energies
and candidate IDs. Geometry identities are recorded for inspection and
export; geometry never enters the acquisition policy.

The lanes are fixed top-2, matched simple, sequential reference feedback,
and full reference rerank. Their configurations come from the saved choices
for the molecule's validation fold. In particular, **matched simple is a
policy role, not a synonym for fixed top-2**. The selected comparator is fixed
top-2 in four folds and the cheap-window rule with k=2, gap=0, cap=2 for
`fold_id = 3`. Saved fold IDs run from 0 to 4; the interface displays them
as folds 1 to 5, so that comparator appears in displayed fold 4.

Stepping one lane reveals one paid observation in that lane. Stepping all
lanes may charge one query in each active lane. Running to stop lets each
policy finish its own rule. A finished lane selects its best successfully
queried reference; the evaluator then supplies regret against the same full
pool. Other lanes do not inherit its observations, stop decision, or score.

The displayed total sums independent offline policy evaluations. Repeating
the same candidate in a different lane costs another unit. These are replay
accounting units, not new quantum jobs or measured wall-clock savings.

The shared geometry inspector displays the chosen lane's observations only.
Its reference-progress display uses references already bought by that lane;
it cannot normalize against an unseen full-pool reference minimum. Viewing,
rotating, zooming, or changing the rendering style adds no reference calls.

## Understand a failure

**Failure explorer** reads the sealed per-molecule development-CV table. It
contains 2,868 procedure–molecule rows: six saved procedure roles for each of
478 molecules in 287 chemical families. The same molecule is paired across
roles before differences are computed. Family filters keep the family IDs
visible; they do not create a new validation split.

Switch between fixed top-2 and the matched simple role as the comparator.
The distinction matters: their total costs are 956 and 964, respectively.
Positive sequential-minus-comparator call differences mean more queries;
positive regret differences mean a worse final reference decision.

The API exposes a strict metric whitelist. It does not publish the full-pool
best candidate, selected candidate, query order, raw reference energies, or
trace annotations from this table. The raw result CSV remains in the
reproducible repository; it is not a file route on the app server.

The explorer is a retrospective analysis view for a human. Policies never
receive its metrics. Reading these cases cannot constitute a fresh blinded
evaluation or evidence of a new policy's generalization.

### Five concrete development cases

These cases were deliberately selected after inspecting the existing
outcomes. They illustrate behavior; their frequency is not estimated by this
small, selected set. Regrets are kcal/mol in the fixed molecular pool.

| Molecule | Fixed top-2 calls / regret | Sequential calls / regret | What to inspect |
|---|---:|---:|---|
| `omegacsd_GIHTUM` | 2 / 2.008453 | 3 / 0.000000 | A third query rescues a missed reference minimum. |
| `astex_1xoq` | 2 / 0.000000 | 10 / 0.000000 | Escalation buys eight extra references without improving regret. |
| `omegapdb_2f4j` | 2 / 0.299097 | 1 / 3.165477 | The first cheap-energy separation triggers an unsuccessful early stop. |
| `omegapdb_2byi` | 2 / 5.146528 | 2 / 5.146528 | Both simple decisions miss the same pool's low reference region. |
| `omegapdb_1yc4` | 2 / 0.000000 | 2 / 0.000000 | The exact matched-simple lane instead spends 10 calls, with a crowding fallback. |

The full reference lane takes ten queries and reaches zero regret in all
five cases. The four lanes across these five cases account for 20 repeated
policy–molecule evaluations and 96 offline charged queries. The reproducible
integration command checks that parity against the sealed table:

```bash
node scripts/verify_workbench.js --out comparison-replays.json
```

This command starts and stops a temporary loopback server with Python
site-packages disabled. It requires Node 18 or newer for built-in `fetch`
and an existing Python executable. Set `AQC_TEST_PYTHON` to a Python executable
path if `python3` is unavailable. It does not install packages or use network
services. The application itself does not need Node.

## Failure handling and export

Charged mutations receive an idempotency key. The client does not
automatically repeat a charged request when the response is lost. It reads
the existing session to reconcile accounting; if that read also fails, the
lane remains visibly uncertain and cannot make another paid mutation until
reconciled. A successfully read failure retains its paid ledger and error.

If the server definitively reports an expired or missing session, choose
**Archive unavailable comparison**. The app retains the whole comparison
before releasing remaining workers, then enables an explicit fresh start.
That action cannot resolve a lost response: archived uncertainties remain in
JSON/CSV and cumulative charges are labeled a **last-confirmed lower bound**.
Temporary connectivity failures cannot use this archive path. The archive
retains at most 12 previous comparisons; it refuses to overwrite paid history.

The actual expiry path is reproducible with a one-second test-server TTL:

```bash
node tests/test_comparison_expiry_http.js expiry-recovery.json
```

This product check makes one paid replay query, lets the server expire the
session, verifies explicit archive recovery, and starts a zero-call replacement
without erasing the older incomplete ledger.

Creating the comparison is free. Partial setup failures clean up only the
newly created, uncharged sessions. Starting a different comparison retains
the previous paid run in the current page's comparison history and cumulative
accounting. Export before closing the page: live sessions and comparison
history are not a persistent database. The server expires idle sessions after
15 minutes; browser reload and server shutdown end live continuity.

JSON and CSV reports preserve the lane configuration, fixed pool identity,
charges, purchased observations, stop reason, and final score when available.
They are user-generated replay reports, not new sealed benchmark artifacts.
Comparison JSON is an export format; it is not accepted by the existing
single-run import control.

## What the evidence still says

The frozen primary comparison remains sequential feedback versus the
training-selected matched simple role. Sequential succeeded on 455/478
molecules using 973 calls. Matched simple succeeded on 457/478 using 964.
The observed call saving is −0.934%, with the recorded family-bootstrap 95%
interval [−5.824%, +3.444%]. This does not meet the target of at least 95%
success with at least 30% fewer calls at matched risk.

These results support investigating why the misses and unnecessary queries
occur. They do not demonstrate that a shape probe will fix them. A future
shape-aware acquisition experiment must have a frozen design and an
evaluation population appropriate to its claims. This release adds no
shape features and runs no new quantum calculations.
