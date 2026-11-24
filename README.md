# Adaptive Quantum Chemistry

A reproducible CLI benchmark for choosing which conformers deserve expensive
reference single-point calculations. This repository contains a working
hidden-label oracle, baseline policies, a verified Folmsbee–Hutchison replay,
an explicitly synthetic fixture, and a portable results dashboard.

**Executed result:** on 162 held-out molecules from 124 chemical families,
fixed top-2 and the development-selected adaptive policy both achieved
**96.30% within 1 kcal/mol with 2.00 calls per molecule**. The adaptive policy
saved **0.00% additional calls** against the matched-risk fixed baseline.
The requested 30% incremental saving was **not met**. Their success interval
is 93.29–98.77%, so the observed success rate is not a certified ≥95% population
guarantee.

## Start here

Open `results/real/dashboard.html` directly in your browser. It is a single,
self-contained local file, with no server, external assets, API requests,
quantum jobs, or deployment. Use the outcome filter and molecule rows to
inspect the six failures and their exact paid-query traces. Development and
held-out plots are labelled separately. The dashboard has no tuning controls.

`results/real/REPORT.md` is the executed report. The full source audit is in
[`docs/PROVENANCE.md`](docs/PROVENANCE.md). The synthetic dashboard is
`results/fixture/dashboard.html`.

## Install

Use Python 3.12 (executed with 3.12.14). Dependencies and all numerical/plotting
transitive dependencies are pinned in `requirements.txt`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
```

On Windows, create the environment with `py -3.12 -m venv .venv` and activate
it using `.venv\Scripts\Activate.ps1`. The remaining commands use `python`.

### One command for the fixture

```bash
python -m aqc fixture --out runs/fixture --bootstrap 5000
```

### One command for the real replay

```bash
python -m aqc real --out runs/real --bootstrap 5000
```

The distribution includes a checksummed, 8.6 MB compressed snapshot of the
required upstream files, so the real replay needs **no data download** after
dependency installation. It extracts into `.cache/`, verifies every included
file, reconstructs the geometry audit, prepares the same family split, tunes
on development data, writes and verifies frozen choices, then evaluates in a
separate process and produces all outputs plus the dashboard.

If the snapshot is absent, the same command clones the public repository and
checks out the pinned commit. No quantum executable is installed or invoked.
For your own clean checkout of that exact revision:

```bash
python -m aqc real --source /path/to/conformer-benchmark --out runs/real-checkout
```

For an exact replay of the **already sealed** delivered evaluation without
retuning:

```bash
python -m aqc reproduce --run results/real --out runs/reproduced-real
```

This reuses the frozen choices and verifies byte-for-byte equality of the
per-molecule results, aggregate table, paired comparisons, decision JSON,
and complete primary evaluation query trace. It does not use observed
holdout outcomes to select a new operating point. Existing frozen/sealed
output directories refuse silent retuning or overwriting.

```bash
python -m unittest discover -s tests -v
python -m aqc dashboard --results results/real
```

Node is optional and only used by dashboard JavaScript logic tests. Those
checks skip if Node is unavailable; the benchmark and dashboard generation
use Python alone. Browser interaction checks were also performed on the
rendered real dashboard.

## Data verification and eligibility

Upstream: [ghutchis/conformer-benchmark](https://github.com/ghutchis/conformer-benchmark).
Pinned commit:

```text
0109c8ec7cff3c10d3617ed65392fffc81492755
```

The upstream repository carries the MIT license, copyright 2020 Geoff
Hutchison. Its original license is retained inside the source snapshot and
in `data/UPSTREAM_LICENSE`. The source snapshot is a documented subset of
the repository, not a substitute dataset. `data/upstream_lock.json` records
the Git blob SHA-1, SHA-256, byte count and path of all 13,999 included files.
No upstream executable scripts are run.

The paper describes single-point energies on the same B3LYP-D3BJ/def2-SVP
geometries: GFN2 using xTB 6.2 and DLPNO-CCSD(T)/cc-pVTZ with TightPNO using
ORCA 4.0.1. See [Folmsbee and Hutchison, DOI 10.1002/qua.26381](https://doi.org/10.1002/qua.26381).

The join key is exactly `(molecule_id, rmsdN-opt)`. A filename stem retains
its geometry suffix; `-mmff`, `-pm7`, and `-opt` are never treated as the same
geometry. Every candidate has an ordered-elements-and-coordinates hash.
All 6,995 published MOL/XYZ pairs agree in atom counts, ordering and
coordinates within 0.000051 Å. Explicit compositions also agree with the
author-supplied molecular SMILES. Molecular identities use those SMILES,
because the MOL files contain unreliable perceived bonding/charge metadata.

| Inventory or exclusion | Count |
|---|---:|
| Raw GFN2 energy rows | 28,481 |
| Non-opt GFN2 rows excluded | 21,486 |
| Published optimized geometries | 6,995 |
| Molecules before exclusions | 708 |
| Raw paired DLPNO outputs | 6,755 |
| Optimized geometries missing DLPNO outputs | 240 |
| DLPNO rows without corresponding GFN2 | 0 |
| Molecules with partial references, excluded wholesale | 55 |
| Molecules with no references, excluded wholesale | 6 |
| Complete singleton molecules, excluded as no ranking decision | 7 |
| **Eligible complete nontrivial pools** | **640 molecules / 6,378 candidates** |

A missing output is never converted to zero or removed from only one
policy's pool. Entire incomplete molecules are excluded. Exact candidate,
molecule and raw-row exclusion manifests preserve every reason.

**Energy sign matters.** Raw GFN2 kcal/mol values are positive atomization
energies, so the benchmark negates them before ranking low to high. It uses
the published rounded kcal/mol column, retaining its 0.01 kcal/mol precision,
and cross-checks the accompanying Hartree field. Reference labels are raw
CCSD(T) total Hartree multiplied by **627.509469**, the original compilation
constant. Their relative differences agree with the negated published
atomization-energy differences within 1e-6 kcal/mol. Cheap features are
centered only on the minimum **cheap** energy within a molecule.

No original per-conformer molecular input files or full output/convergence
logs are supplied by upstream. Pairing is supported by the authors'
same-geometry methodology, exact keys, published coordinate files, and
independently cross-checked energy extracts. This does not claim an audit
of original per-job convergence or original input coordinate checksums.

## Chemical families and untouched evaluation

Families are inferred, not supplied by the authors. With RDKit 2025.09.6:

1. Parse the supplied molecular SMILES.
2. Obtain a Bemis–Murcko scaffold.
3. Make it generic: atoms become carbon and bonds become single; use
   canonical nonstereochemical scaffold SMILES.
4. Put all acyclic molecules in one conservative `ACYCLIC` family.
5. Require identical canonical molecules to have identical families;
   conflicting assignments fail validation.

This produces **411 families**. It is an operational grouping, not a claim
that every chemically related analogue is isolated by these scaffolds.
All conformers of a molecule always travel together.

Sort families by SHA-256 of `1729|family_id`. Put the first `floor(0.7*411)`
families into development and the rest into evaluation. The rule and seed
were fixed before inspecting policy performance.

| Split | Families | Molecules | Candidates |
|---|---:|---:|---:|
| Development | 287 | 478 | 4,761 |
| Evaluation | 124 | 162 | 1,617 |

`split_manifest.json` contains every assignment, family size and split hash.
The evaluation set was untouched for tuning; it is now reported and must not
be treated as fresh validation for future probe development.

## Hidden-label oracle

`aqc/policy_worker.py` runs in a separately launched `python -I -B` interpreter,
with an empty temporary working directory and a restricted environment. It
imports only `json` and `sys`. Its strict input contract accepts exactly
candidate IDs and cheap energies plus a frozen policy configuration. It
receives no family IDs, molecular structures, dataframe, reference summary,
reference-based scaling, reference table, or inherited evaluator object.

The evaluator owns all labels. A valid first query charges one job and
returns only that candidate's reference energy. A failed output is charged;
a duplicate is a logged cache hit without a second charge; an unknown ID is
rejected. Failure-triggered fallbacks and unsuccessful runs retain their
query accounting. A run without a successfully verified candidate fails.

The evaluator independently enforces selection of the lowest reference
energy among successfully queried candidates. Cheap and reference ties
break deterministically by candidate ID. Each paid policy must make at
least one paid query. Separate policy sessions serve development and final
evaluation; caches and observations are reset for every molecule/policy.

This is a strong boundary against **accidental** reference access. It is not
an OS security sandbox against deliberately malicious policy code running
as the same user. Only the built-in audited policies run in this milestone.

## Policies and operating-point selection

| Policy | Behavior |
|---|---|
| Full reference rerank | Query all candidates and return the best observed reference. |
| Fixed top-k | Query the k lowest cheap-energy candidates; choose the best reference among those. Failed outputs trigger a full fallback. |
| Adaptive cheap-gap | Query initial k; continue while the next candidate lies within a cheap-energy window of the cheap minimum. If the window remains crowded at the cap, query the whole remaining pool. Failed outputs also trigger full fallback. |
| Cheap-only diagnostic | Pick the cheapest conformer without reference verification; zero paid calls. It is excluded from paid comparisons. |

The adaptive policy is deliberately simple: it allocates calls based on
cheap-energy crowding. Observed references choose the returned conformer;
they do not train a hidden surrogate or tune stopping thresholds online.

The prespecified development grid is fixed k=1…10; adaptive initial
k in `{1,2,3,4,6,8,10}`, windows in `{0,0.1,0.25,0.5,1,2,4,8}` kcal/mol, and
caps in `{2,4,6,8,10}` subject to cap≥k. There are 204 real development
configurations including the ceiling and diagnostic. Every development
query and decision is recorded in compressed traces.

For fixed and adaptive rules separately, require observed development
success≥95%, then minimize total calls, then p95 regret, then maximize
success, with deterministic lexical configuration tie breaking. If no
reduced-call point qualifies, the report says so; full reranking remains
available. The primary simple comparator is the least costly fixed point
whose development success also matches or exceeds the selected adaptive
success. If that differs from the fixed 95% point, both are retained.

Freeze configurations, source-module hashes, provenance hashes and split
hashes before a separate evaluation process opens the final label table.
The holdout risk curve contains only configurations selected in advance:
all fixed k and adaptive points selected at predefined development success
targets. The curve is descriptive; no test-set point replaces the frozen
primary comparator.

## Executed real result

Development fixed top-1 success was **91.63%**; fixed top-2 reached **95.61%**.
The selected adaptive configuration was `k=2, gap=0.0 kcal/mol, cap=4`.
It made one extra tie-triggered query in development without improving
success. On evaluation it made exactly the same queries and decisions as
fixed top-2. The fallback implementation was exercised by tests/fixtures,
but the selected real operating point triggered no fallback.

| Held-out policy | Within 1 kcal/mol | Median regret | P95 regret | Worst regret | Mean calls | Total calls | Fallback |
|---|---:|---:|---:|---:|---:|---:|---:|
| Full rerank | 100.00% | 0.000 | 0.000 | 0.000 | 9.981 | 1,617 | 0% |
| Fixed top-2 | 96.30% | 0.000 | 0.853 | 4.570 | 2.000 | 324 | 0% |
| Adaptive | 96.30% | 0.000 | 0.853 | 4.570 | 2.000 | 324 | 0% |
| Cheap-only, unverified | 95.06% | 0.047 | 0.952 | 4.578 | 0.000 | 0 | 0% |

Regrets are kcal/mol relative to the best reference in the same fixed pool.
Fixed top-2 and adaptive succeed on **156/162 molecules**. The paired
adaptive-minus-fixed differences are zero for calls, regret, success, and
fallback; the measured extra saving is **0% (95% paired-family CI 0–0%)**.
Their reduction against full reranking is **79.96%**, but that is not the
requested incremental gain over the strongest simple comparator.

There are 5,000 bootstrap resamples of entire chemical families with
replacement, retaining every molecule and using the same family
multiplicities for both sides of each paired difference. Point estimates
weight molecules equally. The 95% percentile success interval for top-2
and adaptive is **93.29–98.77%**; the p95-regret interval is **0.457–1.399**.
These are descriptive sampling intervals, not a learned risk guarantee.
Degenerate 100% intervals for full reranking reflect its deterministic
ceiling in an entirely labelled fixed pool. The legacy output field
`bootstrap_joint_evidence` means that all specified **marginal** interval
checks pass; it is **not** a simultaneous 95% joint confidence statement.

Cheap-only's evaluation percentage must not be used to tune k=1 after the
fact. The paid k=1 point is visible in the descriptive curve; the original
development-selected primary comparison remains unchanged.

## Synthetic fixture

The fixture contains 24 invented families and four explicit scenarios per
family: easy, escalation helps, escalation wastes, and confidently wrong
cheap rankings. No synthetic outcome is presented as a molecular result.

`fixture_case_checks.json` executes a diagnostic fixed top-1 versus
adaptive `k=1, gap=0.5, cap=2` on two named cases:

| Case | Fixed top-1 | Adaptive with full fallback |
|---|---|---|
| Escalation helps | 1 call; 2.1 kcal/mol regret | 6 calls; 0 regret |
| Escalation wastes | 1 call; 0 regret | 6 calls; 0 regret |

These explicit behavior checks are separate from the fixture's tuned
operating point, which chooses three paid queries and does not establish
scientific performance.

## Outputs

Each completed run contains:

- `dashboard.html`: portable interactive decision table, uncertainty plot,
  search, outcome/fallback filters, molecule traces, and provenance details.
- `per_molecule.csv`: selection, reference regret, success, calls, query
  order, fallback, and stop reason for every held-out pool and policy.
- `aggregate.csv` and `paired_comparisons.csv`: point estimates and
  family-cluster intervals.
- `traces.jsonl`: every primary held-out oracle event; unqueried references
  are absent from policy traces.
- `development_frontier.csv`, compressed development decision/query logs,
  and `heldout_frontier.csv` plus its compressed query log.
- `frozen_config.json`, `evaluation_seal.json`, `environment.json`,
  `split_manifest.json`, `audit.json`, and `REPORT.md`.
- `risk_vs_calls.png`: standalone scientific figure.
- `prepared/`: separate cheap-feature and evaluator-only reference tables
  for development/evaluation; geometry, family, missing-output and exclusion
  manifests. These are evaluator inputs, never policy features.

## What this milestone decides

The measurement system is working and reproducible. The cheap-gap adaptive
rule offers **no incremental efficiency** at the selected risk level.
This is not evidence that shape probes help or that every adaptive rule
must fail. A future shape acquisition experiment has a concrete bar:
approximately **≤1.4 paid calls per molecule** instead of two, while retaining
the target accuracy and demonstrating matched risk on fresh evaluation
families. The current evidence supports a narrowly scoped probe experiment,
not a claim of shape-aware advantage or a large implementation sprint.

Complete-case selection, one inferred-family split, finite held-out size,
the source's limited low-energy conformer pools, and absent original full
quantum logs limit generalization. Calls saved in offline replay are never
equated with actual elapsed time or quantum-compute cost.

No neural networks, new shape probes, live quantum jobs, paid compute,
deployment, or outreach were performed.
