# Erkidu recovery and historical development replay

## What was recovered

The existing `hasan1s7/adaptive-quantum-chemistry` repository was cloned locally.
The inspected `main` head was `f2a603e14f1d704084f6ddcb07645f2f701fa844`.
Historical packages and source refer to repository commit
`6d81701875b996426c07f383789767ea423a899a`; all four historical input files
match the bytes in the current checkout. The underlying Folmsbee–Hutchison
data revision is `0109c8ec7cff3c10d3617ed65392fffc81492755`, with its MIT license
retained in `data/UPSTREAM_LICENSE`. No existing source was modified, no
remote branch was updated, and no Nabu repository was edited.

The `Hanash-Protocol-2026-11-24.zip` package supplied the original two-call
policy, sealed pre-label plans, and scientific outputs. The prior
`erkidu-three-policy-replay.zip` supplied the already executed 669-call
comparison. The latter has been inspected rather than rerun.

## Executed reproduction: exactly two queries per pool

```bash
python scripts/reproduce_decision_history.py --out runs/history-956
```

This invokes the unmodified archived policy source, first planning with only
cheap energies and geometries, then scoring after validating the plan. The
following four scientific output files reproduce their archived SHA-256
digests byte for byte: `sealed_prelabel_plan.jsonl`, `results.json`,
`per_pool.csv`, and `rank4_rescue_harm.json`. The separate timing receipt is
new. Ten original historical tests passed in 6.241 seconds.

| Historical policy | Success at regret ≤1 kcal/mol | Attempted replay calls | Mean regret, kcal/mol | P95 | Worst | Threshold rescues / harms versus top two |
|---|---:|---:|---:|---:|---:|---:|
| Fixed top two | 457/478 | 956 | 0.183035 | 0.778190 | 5.146528 | — |
| Steric overlap | 458/478 | 956 | 0.178120 | 0.766387 | 5.146528 | 1 / 0 |
| Torsional diversity | 453/478 | 956 | 0.195274 | 1.082478 | 3.550562 | 4 / 8 |
| Torsion plus steric | 453/478 | 956 | 0.192360 | 1.082478 | 3.550562 | 4 / 8 |

The steric difference is +0.209 percentage points, with a 2,000-draw
family-bootstrap descriptive interval of [0.000, +0.718] percentage points.
Its mean-regret difference is −0.004915 kcal/mol, interval
[−0.016340, +0.003316]. These are conditional development intervals; a zero
bootstrap boundary does not establish a population improvement. Steric has
9 per-pool regret wins, 12 losses, and 457 ties. It does not uniformly improve
on top two. Keep top two as the comparison rule.

The new reproduction took 6.496 seconds of local wall time. That includes
loading, feature computation, repeated plan verification, scoring and
bootstrap aggregation. It does not measure original quantum jobs, queues,
billing or parallel reference execution. All live job counts are zero.

## Already executed 669-call comparison: inspected, not rerun

```bash
python scripts/inspect_saved_669.py --out runs/saved-669-inspection.json
```

The completed package contains 1,912 policy–molecule rows: one fixed control
and three 669-call rules for each of 478 pools. Inspection checked every
recorded queried set, selection membership, reference regret, threshold
outcome, family assignment, aggregate total and paired rescue/harm count.
The four input hashes match. No acquisition policy was rerun, no new
reference was purchased, and the original verification log is preserved.

| Saved rule | Success | Calls | Rescues / harms versus fixed top two |
|---|---:|---:|---:|
| Fixed top two | 457/478 | 956 | — |
| Large-gap gate, rank-two second choice | 452/478 | 669 | 0 / 5 |
| Same gate, heavy-atom RMSD second choice | 452/478 | 669 | 2 / 7 |
| Same gate, RMSD plus gyration second choice | 452/478 | 669 | 2 / 7 |

All three save 287/956 = 30.02% of **offline call counts** but fail the 95%
success target, which requires at least 455 successes on 478 pools. Their
shared allocation buys rank one everywhere and 191 second calls, allocated
proportionally across the original five folds. Within folds it prioritizes
the **largest** cheap rank-one/rank-two gaps; this is the actual saved rule,
not a corrected or retuned threshold. The three rules share exactly the
same second-call pools and vary the second candidate.

The newly proposed 669-call experiment would instead hold candidate pairs
fixed and compare allocation based on shape features against allocation
based on cheap energy gap. That is a different experiment and has not been
performed here. Do not conflate either allocation experiment with the
two-call-per-pool steric comparison.

## Physics scope and limitations

These old data compare GFN2-xTB cheap single points with
DLPNO-CCSD(T)/cc-pVTZ TightPNO references, on the authors' fixed
B3LYP-D3BJ/def2-SVP geometries. The cheap program was xTB 6.2; reference
program ORCA 4.0.1. Full protocol details and original exclusions are in
`docs/PROVENANCE.md`.

They are **not an MLIP-versus-DFT result**. No compatible force labels are
present. The prepared records do not encode charge/spin; the original source
contains neutral and charged subsets. The inherited cohort must not be
relabelled as an independently checked closed-shell-only benchmark. A fresh
job needs explicit charge, multiplicity and complete input settings.

The prior filters excluded 55 partial-reference molecules, six molecules
with no references, and seven singleton pools; 640 complete nontrivial
pools remained. The 478 development pools contain 4,761 candidates across
287 inferred generic-scaffold families. The already observed historical
evaluation cohort was not scored for new policy selection here. All results
above are previously examined **development evidence**, not a new holdout.

Recorded steric topology was inferred from XYZ distances and remains
unreviewed. All eligible steric scores were zero in 411/478 pools. No
probability forecasts were emitted, so the old experiment cannot supply
predictive calibration or certified selective-risk claims.

## Review deliverables

`results/decision_engine/recovery/summary.json` provides a compact
machine-readable recovery record. `physics_failure_cases.json` contains two
real cases, exact pre-label plans, geometry hashes and coordinates, with
reference values explicitly separated as evaluator-only information. The
associated review sheet is `RECOVERY_PHYSICS_CASES.md`.
