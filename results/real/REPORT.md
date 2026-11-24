# Adaptive Quantum Chemistry — executed benchmark

**Dataset: REAL.** Offline fixed-pool replay; no quantum jobs, wall-clock savings, or shape-probe claims.

Held out **162 molecules in 124 families** after freezing choices on development data.

| Policy | Success ≤1 kcal/mol (95% family CI) | Median regret | P95 regret | Max regret | Calls / molecule | Total calls | Fallback |
|---|---:|---:|---:|---:|---:|---:|---:|
| adaptive | 96.30% (93.29%–98.77%) | 0.0000 | 0.8530 | 4.5703 | 2.000 | 324 | 0.00% |
| cheap_only | 95.06% (91.72%–98.10%) | 0.0468 | 0.9524 | 4.5779 | 0.000 | 0 | 0.00% |
| fixed_top_k | 96.30% (93.29%–98.77%) | 0.0000 | 0.8530 | 4.5703 | 2.000 | 324 | 0.00% |
| full_rerank | 100.00% (100.00%–100.00%) | 0.0000 | 0.0000 | 0.0000 | 9.981 | 1617 | 0.00% |

All regrets are kcal/mol. Cheap-only has **zero verification**, so it is a diagnostic and excluded from paid comparisons.

## Decision

Frozen matched-risk comparator: **fixed_top_k**.

Adaptive call savings: **0.00%**, 95% paired-family CI 0.00% to 0.00%.

Adaptive minus comparator success: 0.00 percentage points (95% CI 0.00 to 0.00).
Observed joint target met: **False**. Conservative bootstrap evidence for all three conditions: **False**.

Both frozen policies meet the observed 95% target: **True**. If false, call differences are descriptive and do not establish savings at the target risk.

Risk matching is selected on development data. A holdout risk mismatch is reported, never repaired by choosing a different test-set point.

A reduced-call fixed baseline met the development 95% target: **True**.

## Frozen policies

```json
{
  "adaptive": {
    "cap": 4,
    "gap": 0.0,
    "k": 2,
    "kind": "adaptive"
  },
  "cheap_only": {
    "kind": "diagnostic"
  },
  "fixed_top_k": {
    "k": 2,
    "kind": "fixed"
  },
  "full_rerank": {
    "kind": "full"
  }
}
```

## Data and split

```json
{
  "development": {
    "candidates": 4761,
    "families": 287,
    "molecules": 478
  },
  "evaluation": {
    "candidates": 1617,
    "families": 124,
    "molecules": 162
  }
}
```

Split hash: `29607bec2250e2116e9e16b7d23b91ff941764c495e0fdef09d7b2e4b86431bd`. Config hash: `c757a6a2238f50a5e1389302a172a83fb899ce92b9d83994e66951b6dc6db540`.

Uncertainty: 5000 paired family-cluster bootstrap resamples, seed 1729. Point estimates weight each molecule equally. Intervals do not account for new-data selection bias or certify a population risk bound; all-success cells can yield degenerate empirical intervals.

## Scope and limitations

- Published energy extracts and author method/geometry mapping; full job inputs, SCF/convergence logs, and per-method geometry checksums absent.
- No solvent, thermal, zero-point or experimental-population inference.
- Whole incomplete pools excluded; results conditional on complete-case coverage.
- Generic scaffold families are an operational inference, not supplied labels; analogs with different scaffolds can remain related.
- No original per-job quantum calculations repeated; offline replay call counts are not wall-clock savings.
- The heldout frontier is descriptive: its finite configurations were frozen using development data before evaluation. No holdout result changes the primary choices.
- This evaluation set is now observed. Future shape probes require new held-out groups or an explicitly exploratory comparison; do not reuse this result for tuning and call it untouched.

## Reproduction artifacts

`per_molecule.csv`, `aggregate.csv`, `paired_comparisons.csv`, `traces.jsonl`, `development_traces.jsonl.gz`, `frozen_config.json`, `split_manifest.json`, `evaluation_seal.json`, `risk_vs_calls.png`, and the local `dashboard.html`.
