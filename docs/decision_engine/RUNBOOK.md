# Erkidu decision engine: runbook

**Scientific snapshot: 27 November 2026. Documentation/source release: 28 November 2026.**

This is the detailed companion to [the concise entrypoint](../../README_DECISION_ENGINE.md). Commands run from the repository root. The source release retains small prepared inputs and sealed results; it omits the raw numerical downloads. Run `python -m erkidu_decision fetch` before an audit that reads raw source tables. That command downloads and checksum-verifies the five pinned files; it runs no MLIP or DFT calculation. See [release notes](RELEASE_NOTES.md) for the boundary between the frozen experiment and the presentation release.

**Scientific decision: keep the evaluation and provenance product; do not promote adaptive compute savings.**

At two historical reference acquisitions per pool, decision-aware expected improvement succeeds in 30/30 test pools, versus 29/30 for fixed MACE top-two. The difference is one SnO₂ rescue. A prespecified frozen M3GNet baseline also succeeds in 30/30 with **zero** reference acquisitions. That is the strongest challenge to the adaptive product, and it is included prominently in the dashboard.

The original 27 November experiment was a local addition at repository base `f2a603e14f1d704084f6ddcb07645f2f701fa844`. At that research stage, existing tracked application files were unchanged and there was no push, deployment, outreach, live MLIP inference, DFT calculation or paid compute. Those statements describe the historical run; the 28 November release prepares its source and presentation for publication on a focused branch. Nabu is outside this release. No deployment is part of this publication scope.

## Open these first

| File | Purpose |
|---|---|
| [docs/decision_engine/TECHNICAL_MEMO.md](../../docs/decision_engine/TECHNICAL_MEMO.md) | Company choices, exact decision mathematics, physics, experiments, limitations and founder calls |
| [results/decision_engine/oxide_run/dashboard.html](../../results/decision_engine/oxide_run/dashboard.html) | Self-contained interactive result dashboard; open directly in a browser |
| [results/decision_engine/oxide_run/dashboard_bundle.json](../../results/decision_engine/oxide_run/dashboard_bundle.json) | Material-replay dashboard input, including aggregates, paired comparisons, intervals, frontier and worst cases |
| [docs/decision_engine/HASAN_STATISTICAL_REVIEW.md](../../docs/decision_engine/HASAN_STATISTICAL_REVIEW.md) | Loss, dependence assumptions, uncertainty, strongest baseline and symbolic cost break-even |
| [docs/decision_engine/MATERIALS_PHYSICS_REVIEW.md](../../docs/decision_engine/MATERIALS_PHYSICS_REVIEW.md) | Ahmad's SnO₂ review, actual geometries and hypotheses that need fresh calculations |
| [docs/decision_engine/RECOVERY_PHYSICS_CASES.md](../../docs/decision_engine/RECOVERY_PHYSICS_CASES.md) | Two real failures from the old molecular development pools |
| [results/decision_engine/recovery/summary.json](../../results/decision_engine/recovery/summary.json) | Reproduced 956-call result and read-only verification of the saved 669-call result |
| [results/decision_engine/full_trace_audit.json](../../results/decision_engine/full_trace_audit.json) | Independent inspection of all canonical primary, random-seed and synthetic-fault traces |
| [results/decision_engine/generation/](../../results/decision_engine/generation/) | Executed geometry-only proposal comparison and all ten candidate records |
| [proposed/fresh_sno2_batch/](../../proposed/fresh_sno2_batch/) | Four real initial structures and review-required VASP input templates; NOT RUN |

The original 27 November downloadable handoff contained a PDF memo, HTML dashboard, an integrated `Erkidu-Result-Bundle.json`, and a source/evidence ZIP. The ZIP is a runnable research snapshot with selected unchanged dependencies from Erkidu, not a replacement for the full product checkout. An exported ZIP has a `HANDOFF_MANIFEST.json` hashing every included file; `tools/verify_handoff.py` checks those hashes without executing policies. That archive-specific manifest is not required to use this GitHub checkout.

## Evidence labels and boundaries

| Evidence | Status | What it establishes |
|---|---|---|
| Old 478-pool conformer experiment | EXECUTED HISTORICAL REPLAY | Four scientific output hashes reproduce exactly; all pools are development data |
| Saved 669-call gap/shape policies | EXECUTED READ-ONLY INSPECTION | 1,912 saved rows and original input hashes agree; policies were not rerun |
| Proposed fixed-pair shape-vs-gap allocation | PROPOSED / NOT RUN | Separate from the saved 669-call experiment |
| New oxide benchmark | EXECUTED REAL-DATA REPLAY | Ranking decisions using published model and reference relaxation endpoints |
| Fault injection and exact finite examples | EXECUTED SYNTHETIC | Software behavior and mathematical counterexamples |
| Five SiO₂ perturbations versus five unchanged inputs | EXECUTED GEOMETRY-ONLY | Geometry validity, duplicate screening and measured local overhead |
| Fresh DFT, force validation and physical generation efficacy | PROPOSED / BLOCKED | No such measurements were performed |

The oxide reference action is a **whole historical DFT relaxation outcome**. It is not a single-point calculation at the MLIP endpoint. The experiment is energy-only; compatible force labels and MLIP final coordinates/convergence logs are absent. It evaluates selection within a fixed composition at 20 meV/atom tolerance, not a convex hull, transport, synthesis or cell performance.

## Runtime and dependencies

The executed environment was Python **3.12.14**, with nine visible logical CPUs, approximately 10 GB RAM and no usable GPU or installed DFT executable. The scientific runtime does not need PyTorch, ASE, RDKit or model weights. It consumes versioned published predictions.

```bash
python3.12 -m venv .venv-decision
. .venv-decision/bin/activate
python -m pip install -r requirements-decision.lock.txt
python -m erkidu_decision --help
```

`requirements-decision.txt` pins direct numerical/reporting dependencies; the lock file records the complete installed runtime dependency closure. It is an exact version inventory, not a wheel-hash lock or a bundled offline wheelhouse. Reinstallation needs a package index that supplies those versions. PDF generation uses separately available ReportLab and Pandoc and is not required for the CLI or dashboard.

Run commands from the repository/snapshot root. Every newly executed output should use a new directory so the delivered evidence remains intact.

## Fast fixture and tests

```bash
python -m erkidu_decision fixture --out runs/fixture-001
python -m unittest tests.test_decision_engine_core tests.test_decision_engine_data tests.test_bounded_oxide_generation tests.test_oracle -v
python scripts/decision_examples.py
```

The delivered scoped test log has **51 passing tests**: 22 new core, 9 new data/calibration, 2 geometry-generation and 18 existing oracle tests. These cover unit/protocol validation, oracle visibility, ties, repeated successful/failed calls, charged failures, unavailable force requests, split leakage, heldout-label perturbation, calibration fitting and geometry checks. This is not a claim that the full existing application/chemistry/UI suite was run.

The synthetic CLI fixture contains 32 runs and 64 charged offline attempts. It includes a rank rescue, shared blind spot, failed reference and exact tie; it does not validate chemistry.

## Verify delivered results without rerunning acquisition

```bash
python -m erkidu_decision verify --run results/decision_engine/oxide_run
python scripts/audit_decision_traces.py --out runs/full-trace-audit.json
python scripts/audit_initial_geometry_splits.py --prepared results/decision_engine/oxide_prepared --out runs/geometry-audit.json
python scripts/inspect_saved_669.py --out runs/saved-669-inspection.json
```

The source-to-prepared audit also compares raw prediction tables. The raw cache is intentionally omitted from the source release, so restore it first:

```bash
python -m erkidu_decision fetch
python scripts/audit_decision_data.py --prepared results/decision_engine/oxide_prepared --fit results/decision_engine/oxide_fit --out runs/data-audit.json
```

The CLI verifies the 19-file scientific result seal, 1,320 primary traces and 2,594 charged primary attempts. The separate full trace audit additionally covers 280 extra random-seed traces and 120 synthetic-failure traces. Neither verification submits calculations.

## Reproduce the historical fixed-budget experiment

```bash
python scripts/reproduce_decision_history.py --out runs/history-956
python scripts/test_decision_history.py
```

This executes the original archived four-policy source and checks four scientific output hashes. The historical ten tests are separate from the 51-test scope above. It does **not** execute any 669-call policy or the proposed new allocation experiment.

## Run the frozen new benchmark

Use the delivered, sealed data and fit:

```bash
python -m erkidu_decision run --prepared results/decision_engine/oxide_prepared --fit results/decision_engine/oxide_fit --out runs/oxide-replay-001 --workers 4
python -m erkidu_decision verify --run runs/oxide-replay-001
python -m erkidu_decision report --run runs/oxide-replay-001
```

To reconstruct from raw source tables using the pinned preparation and fitting rules:

```bash
python -m erkidu_decision real --out runs/oxide-from-source-001 --workers 4
```

The `real` command verifies cached source files and downloads only missing/mismatched pinned files. The original full handoff ZIP included the five numerical source tables required for preparation. This GitHub source release omits `data/decision_engine/raw/`; `fetch` or `real` restores the exact checksum-pinned inputs when network access is available. A stepwise alternative is `fetch`, `prepare --out ...`, `fit --prepared ... --out ...`, then `run` and `report`. Each stage records hashes; fitting validates the preparation seal, and execution validates the fitted artifact.

The frozen protocol contains a descriptive M3GNet checkpoint-label typo (`PES` rather than official `EFS`). `data/decision_engine/source_metadata/metadata_errata.json` corrects it without altering the frozen evidence. The correct official model card, prediction file ID and prediction checksum were used throughout. No model weight binary was executed.

### Split, information and scoring contract

- Train: 35 pools / 147 candidates / 33 chemical systems. Calibration: 28 / 88 / 24. Test: 30 / 110 / 26. Lithium shift: 10 / 22 / 10.
- All candidates with the same chemical system stay in one split. Composition/initial-prototype duplicates are removed without reference labels. Initial geometries are audited for cross-split exact and screened near duplicates.
- Policies receive a strict public whitelist through an isolated interpreter. The parent evaluator retains reference values and sends only requested responses. This prevents accidental leakage; it is not an OS sandbox for hostile policy code.
- Query traces include the public state, successful observations available before the query, previous attempts, remaining budget, acquisition scores, response, charge and final recommendation.
- Successful repeated queries and repeated failed queries are cached without a second charge. A valid first failed attempt costs one reference job. Invalid IDs, incompatible units/protocols and unsupported forces do not invent jobs.
- Paid policies return the best successfully queried candidate; model-only policies may select without querying. Stable IDs resolve exact ties.
- Real-replay regret scoring requires complete compatible evaluator truth for the retained pool. Synthetic reference faults preserve that truth in the evaluator. A dataset with genuinely missing reference minima needs a different incomplete-truth evaluation protocol; the present scorer must not be interpreted as estimating those unknown regrets.
- Chemical-system grouping does not prove independence from shared prototypes, WBM source-parent lineages or pretrained MP exposure. Public MP support distance is a descriptor proxy, not exact training membership or a neural embedding distance.

## Policy adapter

`erkidu_decision.core.Oracle` owns the private label mapping. `run_policy(public_payload, oracle)` runs the policy in the default isolated interpreter and returns the recommendation, query ledger and pre-query states. `normalize_payload` rejects unknown fields rather than silently passing reference-derived metadata.

Supported policy identifiers are `mlip_only`, `full_ref`, `fixed_top`, `random`, `diversity`, `uncertainty`, `disagreement`, `decision_aware`, `calibrated_interval`, and `gap_threshold`. The experiment builds the frozen MACE, CHGNet, M3GNet and ensemble-only comparator payloads explicitly. Public energies and scales are in eV/atom under one protocol ID; descriptors must have matching dimensions.

Before connecting a real backend, implement protocol-checked reference responses and actual cost receipts. Add single-point and force actions only when geometry identity and label compatibility are established. An energy-only interval is not a trajectory force certificate.

## Generation and a future physics batch

```bash
python tools/bounded_oxide_generation.py --out runs/generation-geometry-001 --seed 20261127 --cap 5
python tools/export_fresh_vasp.py --out runs/proposed-sno2-inputs
```

The first command makes and validates bounded perturbations only; it runs no relaxations or DFT. The second exports actual inputs and review-required templates, not a submitted calculation. See `docs/decision_engine/MATERIALS_PHYSICS_REVIEW.md` and the proposed batch manifest for unresolved PAW, magnetic and k-mesh choices, proposed resource caps and future execution commands. No licensed PAW files are redistributed.

## Cost and artifact integrity

The canonical replay took **32.259 wall seconds**, 3.40 parent CPU seconds and 114.50 child CPU seconds with four workers. Its 3,423 charged attempts comprise 2,594 primary, 560 extra-seed and 269 synthetic-stress attempts. These are offline label counts across many policy comparisons, not 3,423 freshly computed reference jobs. The initial run and one verification rerun are separately accounted in `replay_fix_verification.json`; all scientific decisions stayed identical after the trace-bound naming fix.

Reference compute time, queues, batch parallelism, model inference overhead and dollar savings remain unmeasured. Dashboard cost sliders use labelled hypothetical regret-equivalent costs. The paired primary interval includes no improvement, and the zero-query comparator already meets the tolerance on this small retrospective sample.

Dataset attribution, exact source revisions, metadata and licences are in `docs/decision_engine/sources.json` and `data/decision_engine/ATTRIBUTION.md`. Source/output hashes are checks of byte identity, not independent validation of the underlying physics.
