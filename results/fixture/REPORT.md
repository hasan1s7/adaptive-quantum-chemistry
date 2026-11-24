# Adaptive Quantum Chemistry — executed benchmark

**Dataset: SYNTHETIC.** Offline fixed-pool replay; no quantum jobs, wall-clock savings, or shape-probe claims.

Held out **32 molecules in 8 families** after freezing choices on development data.

| Policy | Success ≤1 kcal/mol (95% family CI) | Median regret | P95 regret | Max regret | Calls / molecule | Total calls | Fallback |
|---|---:|---:|---:|---:|---:|---:|---:|
| adaptive | 100.00% (100.00%–100.00%) | 0.0000 | 0.0000 | 0.0000 | 3.000 | 96 | 0.00% |
| cheap_only | 50.00% (50.00%–50.00%) | 0.7500 | 2.1000 | 2.1000 | 0.000 | 0 | 0.00% |
| fixed_top_k | 100.00% (100.00%–100.00%) | 0.0000 | 0.0000 | 0.0000 | 3.000 | 96 | 0.00% |
| full_rerank | 100.00% (100.00%–100.00%) | 0.0000 | 0.0000 | 0.0000 | 6.000 | 192 | 0.00% |

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
    "gap": 0.1,
    "k": 3,
    "kind": "adaptive"
  },
  "cheap_only": {
    "kind": "diagnostic"
  },
  "fixed_top_k": {
    "k": 3,
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
    "candidates": 384,
    "families": 16,
    "molecules": 64
  },
  "evaluation": {
    "candidates": 192,
    "families": 8,
    "molecules": 32
  }
}
```

Split hash: `fa0fd94e332dff847f7c2bb1fe60ecd34340e95dbe8e1e77532e99756f0c98ca`. Config hash: `9cce6ca22b9e3911da18ed9abd363a1fc682e6317a31e303b4b0c30ee2ab26f1`.

Uncertainty: 5000 paired family-cluster bootstrap resamples, seed 1729. Point estimates weight each molecule equally. Intervals do not account for new-data selection bias or certify a population risk bound; all-success cells can yield degenerate empirical intervals.

## Scope and limitations

- Synthetic labels are designed to exercise mechanics, not chemistry or statistical generalization.
- The heldout frontier is descriptive: its finite configurations were frozen using development data before evaluation. No holdout result changes the primary choices.
- This evaluation set is now observed. Future shape probes require new held-out groups or an explicitly exploratory comparison; do not reuse this result for tuning and call it untouched.

## Reproduction artifacts

`per_molecule.csv`, `aggregate.csv`, `paired_comparisons.csv`, `traces.jsonl`, `development_traces.jsonl.gz`, `frozen_config.json`, `split_manifest.json`, `evaluation_seal.json`, `risk_vs_calls.png`, and the local `dashboard.html`.
