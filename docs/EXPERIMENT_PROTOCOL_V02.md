# Adaptive Quantum Chemistry 0.2 — expanded development protocol

## What is being tested

Can cheap-energy-dependent early exits and sequential reference feedback reduce
charged reference queries at the same observed regret risk as strong simple
rules? This is an offline replay on the previously designated **development**
families. It does not provide new untouched external validation. No shape
descriptor, neural network, quantum executable, paid compute, or deployment is
part of this experiment.

The original 124-family evaluation has already been reported and inspected.
It remains historical evidence. Its labels must not select any new operating
point. The original engine is retained under `releases/v0.1.0/`; the original
58 result artifacts retain their recorded checksums.

## Count experiments honestly

The preregistered grid has exactly **1,020 parameter configurations** for the
real ten-candidate maximum: five times the original 204 configurations.

| Configuration family | Count |
|---|---:|
| Original fixed top-k, k=1 through 10 | 10 |
| Original cheap-window configurations | 192 |
| Full reference rerank | 1 |
| Unverified cheap-only diagnostic | 1 |
| New sequential rules | 816 |
| Total | 1,020 |

The sequential grid is the Cartesian product of:

- `one_gap`: 0, .01, .025, .05, .1, .15, .2, .3, .4, .5, .75, 1, 1.5, 2, 3, 4, 8 kcal/mol.
- `one_ratio`: 0, .05, .15, .3.
- `error_scale`: 1, 2, 4.
- `cap`: 2, 4, 6, 10.
- `slack`: fixed at .25 kcal/mol.

Thus 17 × 4 × 3 × 4 = 816. Configurations are not independent datasets or
independent scientific replications. Different parameters can induce identical
decisions. The output reports the number of distinct behavior signatures and
does not count equivalent decisions as new empirical evidence.

Every configuration is run on every one of the 478 development molecules,
giving 487,560 configuration–molecule decisions. A diagnostic has zero paid
queries; every paid policy begins with a paid query. Independent verification
replays are additional executions and are reported separately from this count.

## Sequential policy

Order candidates by cheap energy, with candidate ID breaking ties. Query the
first candidate. For a singleton, return its verified reference. Otherwise,
permit a one-query exit only if the first cheap gap is strictly positive and
meets both the absolute `one_gap` threshold and the `one_ratio` fraction of the
entire cheap-energy span. A tied cheap minimum cannot take that exit.

If the one-query condition does not pass, query the second candidate. After
each successful observation, compare cheap and reference **differences from
the first candidate**, so the rule is invariant to an additive offset in
either energy scale. Let

\[
E = s\max_{j\in Q}|(r_j-r_0)-(c_j-c_0)| + \delta,
\]

where `s=error_scale`, `delta=slack`, and `Q` is the queried set. Let `b` be the
best observed reference difference and `d_next` the next cheap difference.
The rule stops if `b <= d_next - E + 1 kcal/mol`, with the recorded numerical
tolerance. If this empirical condition fails, it buys the next candidate.
If it remains unresolved at `cap`, it queries the entire remaining pool.
Missing or invalid reference outputs also trigger the full fallback.

**E is an empirical heuristic, not a proven bound on unseen reference errors.**
The policy can fail confidently, and the fixture must demonstrate that case.
Its observed feedback only provides information after additional labels have
been purchased; it cannot claim free knowledge of unqueried conformers.

## Family-blocked development validation

Freeze the registry, source hashes, dataset hashes, fold assignments, and
selection rule before executing the expanded sweep. Split the 287 development
families deterministically into five folds. Every family appears in one
validation fold and remains whole.

For each fold, choose operating points using the other four folds only. Require
at least 95% **observed training success**, minimize calls, then use the
predeclared regret/success/configuration tie breaks. Score each selected rule
on the excluded fold. The primary simple comparator is the least costly
qualifying original fixed/window/full rule whose training success also matches
or exceeds the selected sequential rule. This is more demanding than choosing
only a convenient fixed baseline.

The same fixed configuration's pool outcome can be reused across fold
calculations because no model was fitted to generate that outcome. Fold choice
must never read its validation outcomes. Tests deliberately change validation
outcomes and check that the fold's training selection remains unchanged.

All per-fold choices and out-of-fold molecule decisions are retained. A pooled
development frontier is shown separately and labelled apparent development
performance. Changing a filter in the interface does not retroactively change
the registered protocol or promote a point to validated evidence.

## Accounting and uncertainty

Every executed policy–pool run pays independently. A content-addressed trace
catalog removes duplicate stored bytes, not paid jobs. The decision ledger
retains every configuration–pool run, its charges, selected candidate, stop
reason, fallback, and trace key. The verifier resolves those keys and checks
query accounting, best verified selection, reference regret, and all expected
configuration–pool combinations.

Report molecule-weighted success within 1 kcal/mol; median, p95 and worst
regret; calls; fallback; and paired policy differences. Resample whole families
with the same multiplicities on both sides of a paired comparison. Five
thousand draws describe uncertainty conditional on the fixed folds and
selected policies; they do not repeat configuration selection, account for
overlapping training sets, or establish a
distribution-free population guarantee.

Zero-variance or all-success bootstrap samples receive explicit warnings.
Checking multiple marginal 95% intervals is not called a simultaneous 95%
confidence statement. The historical full-rerank ceiling is exact within its
fixed labelled pool, not a claim about chemical truth outside that pool.

The operational target remains at least 95% success and at least 30% fewer
calls than the strongest selected simple comparator at matched risk. If no
point qualifies, report that outcome. Calls saved in replay are not wall-clock
savings, and this development exercise cannot certify the next policy on new
chemistry.

## Interface and evidence integrity

The query simulator contains development molecules only. It reveals reference
values through a charged oracle interface and scores a decision after stopping.
Its browser evaluator necessarily contains the labels in the downloaded file;
it is an educational replay, not a secure sandbox for hostile users. The CLI's
isolated trusted-policy process remains the experiment's execution boundary.

Saved outcomes are distinct from interactive what-if replay. The browser and
Python policy implementations are checked for matching selections, query
orders, charges, fallback, and stop reasons on deterministic and real cases.

New dashboards fail closed on missing or mismatched evidence seals. Complete
v2 seals cover tables, registries, manifests, logs, and reports. Derived HTML
is generated only after verification. Content checksums protect against
accidental modifications and mixed runs; they are not external attestations.

## Portability and historical preservation

New text evidence uses explicit UTF-8 and LF; compressed logs have zero gzip
timestamps and no filename-dependent header. CSV byte conventions and Git
line-ending rules are explicit. Native Windows execution is not claimed unless
it is actually performed. The historical v0.1 reproduction uses its retained,
verified source snapshot rather than weakening the original source-hash guard.
