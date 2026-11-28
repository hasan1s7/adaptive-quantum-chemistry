# Erkidu decision engine

**Find the cheapest observation that can change a scientific decision.** Erkidu compares frozen model outputs, acquires compatible reference results when useful, and records exactly what each recommendation knew.

## What the experiment says

**Keep the evaluation product. Adaptive compute savings are not yet demonstrated.** On the 27 November 2026 oxide replay, the adaptive rule rescued one MACE top-two failure. A frozen M3GNet baseline already met the same tolerance with no reference acquisitions.

| Frozen arm | Within 20 meV/atom | Reference-label acquisitions |
|---|---:|---:|
| MACE top two | 29/30 pools | 60 |
| Decision-aware acquisition | 30/30 pools | 60 |
| M3GNet model only | 30/30 pools | **0** |

These are 30 test pools across 26 chemical systems. The adaptive improvement is one SnO₂ case, and its paired interval includes no improvement. Published relaxation outcomes support this **energy-only retrospective replay**; no fresh DFT or MLIP inference was executed. One reference label represents a whole historical DFT relaxation, not a single point.

The practical product is an auditable answer to: **Which existing model or acquisition rule is sufficient for this batch, and what evidence would change that answer?**

## Three quickstart steps

Run from the repository root with Python 3.12.

### 1. Install the numerical runtime

```bash
python3.12 -m venv .venv-decision
. .venv-decision/bin/activate
python -m pip install -r requirements-decision.lock.txt
```

No model weights or quantum-chemistry software are needed for the replay.

### 2. Verify the recorded result and exercise the contract

```bash
python -m erkidu_decision verify --run results/decision_engine/oxide_run
python -m erkidu_decision fixture --out runs/fixture-001
```

Verification checks saved evidence. The fixture is explicitly synthetic. Use a new output directory for each execution.

### 3. Inspect the decision and its failure case

Open [the standalone dashboard](results/decision_engine/oxide_run/dashboard.html) locally, or serve the checkout:

```bash
python -m http.server 8765 --bind 127.0.0.1
```

Then visit [the local dashboard](http://127.0.0.1:8765/results/decision_engine/oxide_run/dashboard.html). The scientific record stays visible alongside the explanation.

## Go deeper

| Question | Start here |
|---|---|
| How do I reproduce, audit or connect a provider? | [Runbook](docs/decision_engine/RUNBOOK.md) |
| What should the company sell, and what did the experiment establish? | [Complete technical memo](docs/decision_engine/TECHNICAL_MEMO.md) |
| Is the physics comparison compatible? | [Ahmad's materials review](docs/decision_engine/MATERIALS_PHYSICS_REVIEW.md) |
| What are the loss, uncertainty assumptions and cost tradeoffs? | [Hasan's statistical review](docs/decision_engine/HASAN_STATISTICAL_REVIEW.md) |
| Where are the exact decisions? | [Per-pool results](results/decision_engine/oxide_run/per_pool.csv), [current trace audit](results/decision_engine/release/full_trace_audit.json), [result seal](results/decision_engine/oxide_run/result_seal.json) |
| What changed in this release? | [28 November release notes](docs/decision_engine/RELEASE_NOTES.md) |

Raw source tables are downloaded on demand with `python -m erkidu_decision fetch`; the prepared inputs and recorded results are included. The [data attribution](data/decision_engine/ATTRIBUTION.md) records licences, sources and transformations. The 28 November presentation/source release uses the frozen 27 November experiment; it adds no new scientific result or deployment.
