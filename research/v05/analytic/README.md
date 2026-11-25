# Erkidu — decision-value and surface complexity research track

**Research candidate, not v0.5 application release.** The stable v0.4 repository was read at commit `81e5fb8228ecd65e108f9d9a6edf325f3d2b5f7e`. No production, existing `aqc/`, `aqc_app/`, UI, sealed scientific evidence, data split, or Nabu changes. No live quantum calculations, MLIP training, network services, external contacts, or paid compute. No published commit from this package. The research package is separate and uses standard-library Python and Node.

## Research question and results

The supplied thesis, *Slicing and Architecture Dependence of Complexity in Machine-Learned Potential Energy Surfaces*, Candidate 1105515, motivates matched linear/circular trajectories, comparison of spectral and curvature measures, amplitude dependence, and cautious interpretation of a null result. Its numerical data and training code were not supplied. Its text does not give a complete numerical definition of the complexity metrics. The lab therefore implements explicitly defined proxies, not a replication of its PaiNN/MACE/TensorNet or GFN2-xTB findings. Source SHA-256: `5a76a7914e2f02b1a9a85fa941cde4f295c8378d7c21f952542eb4057491a748`.

The supplied November 2026 *Towards Intelligent Atomistic Simulation* white paper (sections 4, 5, 8 and 11) motivates reliability, cost-aware acquisition, model-agnostic multi-fidelity decisions and downstream scientific utility. Rare events, degradation, physical rates, force accuracy, MD stability, actual cost measurements, and industrial validation are NOT implemented. Source SHA-256: `eea10470f3f7525a645da0d4976fb8395a3ef1f3debb9e594556a173d95ccfef`. No raw document is redistributed.

### 1. Actual conformer replay: expected decision value of a second reference

Using only the original 478 development molecules in 287 families, and their frozen five family folds, estimate P(top1 regret > 1 and top2 regret <= 1 | cheap gap). The target is a **rescue**, not generic uncertainty or a claim of calibration on new chemistry. The simple statistical model is a beta-smoothed histogram over fixed gap boundaries 0.1, 0.25, 0.5, 1, 2, 4 kcal/mol, with 20 pseudocounts at the fold-training rate. Evaluate out-of-fold. The comparator is the fold-training constant rescue rate. A second reference costs one charged-job equivalent; choose two if estimated rescue probability exceeds a specified cost penalty. This is a constrained one-vs-two query policy, not a general sequential optimizer. Regret is measured only by the evaluator against the full pool. The fitted probability uses only the cheap gap and training observations. First query is mandatory. Costs are offline equivalents, not real monetary charges.

| Rule | Success within 1 kcal/mol | Offline calls |
|---|---:|---:|
| Fixed top 1 | 438/478 (91.63%) | 478 |
| Fixed top 2 | 457/478 (95.61%) | 956 |
| Gap rescue threshold .02 | 455/478 (95.19%) | 802 |
| Gap rescue threshold .05 | 450/478 (94.14%) | 571 |
| Gap rescue threshold .10 | 445/478 (93.10%) | 503 |

The .02 exploratory point saves 154 calls (16.11%) vs top2; conditional paired family bootstrap 95% percentile interval [13.42%, 19.05%]. Success difference -0.418 percentage points; interval [-1.07, 0] pp. No claim of equivalence, >=95% population guarantee, or 30% savings at matched risk. Thresholds and model are exploratory, not a newly preregistered external test. The frozen v0.2 sequential vs matched-simple result remains negative and unchanged. Brier for predicting *rescue* improves from .038209 to .035697; small event counts and no external calibration. Only 19 rescue events. The cheap gap is not a monotonic risk estimate; 7/25 rescues in the [0.5,1) bin, 5/271 in [0,.1). This motivates an improved diagnostic, not assuming large gaps are universally safe or dangerous. Family bootstrap intervals condition on fitted predictions, do not account for model selection or refit uncertainty. The original historical evaluation labels were not fetched or used.

The three real inputs were retrieved in full through GitHub connector with exact reported blob identities, and results computed in V8 Code Mode. The local Node implementation re-expresses the same analysis and verifies the original Git blob hashes independently. It passed a synthetic cohort test; the container cannot resolve github.com, so the full real-data local Node replay remains a gate. `results/real-results.json` is the recorded connector-computation receipt (not an independent local Node run). Input filenames and pins are in `real_diagnostic.js`.

### 2. Analytic synthetic shape stress test

Four regimes: error amplitude positively related to roughness, independently drawn, negatively related, and a train-to-test reversal. Common random numbers across regimes facilitate comparison; they are not independent datasets. Each has 60 synthetic centres (40 train/20 held-out), 5 directions, 3 amplitudes, 2 matched paths, 128 Lobatto sample points per path, 10 candidate positions (circle excludes duplicate endpoint). 7,200 trajectories, 921,600 point evaluations per fidelity (counted samples, not independent configurations or live quantum calculations). The synthetic energy units are not kcal/mol. The reference function adds a higher-frequency residual to a cheap analytic surface. These are illustrations and stress tests, not physical molecules. Linear/circular samples share centre/direction and amplitude, but traverse different locations and lengths; this alone prevents interpreting differences as a pure MLIP architecture effect.

Metrics: degree-16 discrete Chebyshev nonconstant spectral power fraction above degree 2 (energy offset and scale invariant unless negligible power); mean absolute second derivative of energy with respect to arc length, using a nonuniform finite-difference approximation and interior control-volume weights (not curvature of the graph). No claim of reproducing the thesis metrics exactly. D = (reference minus cheap complexity)_linear minus (reference minus cheap complexity)_circular. Centre-clustered percentile intervals on equal-centre mean D, 1,000 bootstrap draws. Descriptive intervals are not a multiplicity-controlled hypothesis test. No architecture comparison.

Decision feature uses only cheap spectral power, with training-only medians by method/amplitude; candidate gaps and the rescue label for training. Test reference spectral and curvature metrics are evaluation-only. At the original utility penalty .05, both gap and shape policies always buy two, so shape gives no decision improvement. A post-initial-run sensitivity sweep (not an independent test) checks .05/.10/.15/.20/.25 and spectral, MAC and both. At zero additional probe cost: 15/60 shape comparisons improve utility, 13 worsen and 32 tie. At .001 and .01 hypothetical cheap evaluation costs relative to a reference query: 0/60 improve in either case. Those are chosen scenario costs, not measured xTB/DFT timings. Shape-aware policies pay for all 118 additional cheap evaluations per trajectory beyond 10 candidate cheap predictions. Reference metric evaluations are retrospective synthetic evaluator work, not policy observations. No extra physical shape probes authorized or run.

The right next experiment is to collect permissioned matched path data from the actual project, confirm geometry/reference definitions and physical cost, freeze a family-blocked evaluation and compare incremental value against the real cheap-gap baseline at prespecified cost and risk. Reject if no advantage. A pilot cannot substantiate industrial reliability or lifetime predictions. A fresh holdout is required before scientific adoption; nothing in this package is an accepted policy change.

## Reproduce

Open `dashboard.html` in any ordinary browser (offline, embedded derived data; no API). The Python files work without scientific packages. No repository checkout needed for the synthetic track. From this directory:

```sh
python -S -m unittest -v test_shape_lab
python -S shape_lab.py --out new-run
python -S sensitivity.py new-run/trajectories.csv new-run/sensitivity.json
node test_real_diagnostic.js
node real_diagnostic.js /path/to/pinned/adaptive-quantum-chemistry new-real-results.json
```

The output directories/files must not exist already. Verify Git inputs on checkout; do not substitute historical or newly modified labels. Compare the real output to the receipt, ignoring the receipt's `execution` field and allowing floating-point rounding tolerance. Tests use only a synthetic fixture in Node. Chromium rendered and exercised the exact embedded HTML via set_content: all 60 regime/penalty/cost combinations, both metrics, real thresholds, and 320/390/430 CSS widths passed without JS errors after fixing narrow overflow. The environment blocked file:// navigation; that failure and the initial narrow failure are retained. Opening the downloaded file in a normal desktop browser is intended but not verified directly here. Native-device and full v0.4 integration tests were not performed this turn. If your browser blocks local files, serve this directory with `python -m http.server 8766 --bind 127.0.0.1` and open http://127.0.0.1:8766/dashboard.html. Main remained unmodified by this work. A review branch is appropriate only after a complete checkout and real replay have been verified.

Files: `shape_lab.py`, `test_shape_lab.py`, `sensitivity.py`, `real_diagnostic.js`, `test_real_diagnostic.js`, `results/trajectories.csv`, `results/synthetic-results.json`, `results/sensitivity.json`, `results/real-results.json`, logs, dashboard and manifest.
