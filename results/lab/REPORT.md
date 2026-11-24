# Adaptive Quantum Chemistry v0.2 — expanded development experiments

**Internal development cross-validation. No new external holdout was used.**

Registered **1020 parameter-distinct configurations** before execution. They produced **659 distinct acquisition/selection behaviors** on **478 original-development molecules**. Parameter count is not independent evidence.

All **487560 config/pool replays** were independently charged: **1803309 offline expensive-job equivalents**. Trace deduplication only reduced storage.

Five deterministic chemical-family outer folds choose each operating point on the other four folds. The matched simple comparator is the cheapest original fixed/window/full rule meeting the training risk of the selected sequential rule, and at least 95% training success.

| OOF role | Success ≤1 kcal/mol (95% descriptive family interval) | Median / p95 regret | Mean calls | Total calls | Fallback |
|---|---:|---:|---:|---:|---:|
| adaptive | 95.61% (93.76%–97.29%) | 0.0000 / 0.7782 | 2.017 | 964 | 0.21% |
| cheap_only | 91.63% (89.13%–94.02%) | 0.0538 / 1.7932 | 0.000 | 0 | 0.00% |
| fixed_top_k | 95.61% (93.76%–97.29%) | 0.0000 / 0.7782 | 2.000 | 956 | 0.00% |
| full_rerank | 100.00% (100.00%–100.00%) | 0.0000 / 0.0000 | 9.960 | 4761 | 0.00% |
| matched_simple | 95.61% (93.76%–97.29%) | 0.0000 / 0.7782 | 2.017 | 964 | 0.21% |
| sequential | 95.19% (93.20%–97.01%) | 0.0000 / 0.8978 | 2.036 | 973 | 0.00% |

All regrets are kcal/mol. Cheap-only remains an unverified diagnostic.

## Recorded development-CV decision

Sequential versus matched simple call savings: **-0.93%** (descriptive 95% interval -5.82%–3.44%).
Success difference: **-0.418 percentage points** (-1.237–0.426).
Observed development-CV joint target met: **False**. This is not a fresh-holdout or population guarantee.

Descriptive family bootstrap within fixed outer folds, conditional on the selected fold policies. Does not reselect configurations, account for overlapping training sets, or establish a joint 95% confidence guarantee. This is development cross-validation, not a fresh external holdout.

## Important limitations

- The sequential envelope and one-query gate are heuristics. Queried residuals are not a calibrated bound on unseen candidates.
- The design follows inspection of the earlier benchmark. This development CV must not be presented as independent confirmation.
- The original final-evaluation cohort was not rescored, retuned on, or merged into these experiments.
- Pooled experiment rows are descriptive development outcomes; only the role table uses fold-excluded selections.
- Boundary success rates and constant paired differences can produce degenerate empirical intervals; warnings are recorded explicitly.
- Reference labels, complete-case coverage, geometry provenance and inferred-family limitations remain those of the original benchmark.
- No shape features, neural model, live quantum work, paid compute or wall-clock benefit is measured.

## Reproducible evidence

The registry, source/data/fold hashes, experiment table, five-fold choices, all decision ledger rows, deduplicated charged-query catalog, independently repeated OOF selections, verification manifest, paired table and risk plot are retained. `evaluation_seal.json` covers all scientific outputs.
