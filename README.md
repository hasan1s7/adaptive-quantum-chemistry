# Erkidu · decisions before expensive calculations

Choose which structures need a reference calculation—and preserve the evidence behind the choice.

**Latest result:** adaptive acquisition rescues one failure of fixed top-two, but a frozen M3GNet baseline reaches the same selection target with zero reference acquisitions. Keep the evaluation engine; compute savings remain unproven.

| Frozen test comparison | Successful pools | Reference acquisitions |
|---|---:|---:|
| M3GNet alone | **30 / 30** | **0** |
| MACE top-two | 29 / 30 | 60 |
| Decision-aware acquisition | 30 / 30 | 60 |

Success means selecting within **20 meV/atom** of the lowest compatible reference energy in each pool. These are published relaxation-label replays, not fresh DFT measurements. [Read the evidence and limits](docs/decision_engine/TECHNICAL_MEMO.md).

## Start here

- **[Decision dashboard](results/decision_engine/oxide_run/dashboard.html)** — download/open the standalone HTML to compare policies, walk through the SnO₂ failure, and inspect uncertainty and costs.
- **[Run the decision engine](README_DECISION_ENGINE.md)** — setup, fixture and frozen-result verification.
- **[Complete runbook](docs/decision_engine/RUNBOOK.md)** — source reconstruction, audits, policy contract and known limits.
- **[Physics review](docs/decision_engine/MATERIALS_PHYSICS_REVIEW.md)** and **[statistical review](docs/decision_engine/HASAN_STATISTICAL_REVIEW.md)** — the decisions for Ahmad and Hasan.

## Quick check

With Python 3.12.14 and the pinned dependencies installed:

```bash
python -m pip install -r requirements-decision.lock.txt
python -m erkidu_decision fixture --out runs/fixture-001
python -m erkidu_decision verify --run results/decision_engine/oxide_run
```

The fixture is synthetic. The verifier checks the delivered real-data replay without submitting reference jobs. Raw public tables can be fetched by exact file ID and checksum when reconstructing the benchmark; they are not stored in this source release.

## Existing work

The **[conformer comparison workbench](README_CONFORMER_WORKBENCH.md)** remains available with its original UI, instructions and historical evidence. Launch it locally with `python -m aqc_app`. The [research directory](research/) contains earlier experiments with their own evidence labels.

This release adds the MLIP/DFT decision engine and a clearer presentation of its completed experiment. It does not establish force reliability, a discovered material or independent customer validation. [Release scope](docs/decision_engine/RELEASE_NOTES.md) · [Data attribution](data/decision_engine/ATTRIBUTION.md)
