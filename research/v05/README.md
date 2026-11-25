# Erkidu scientific decision laboratory (research v0.5)

**A separate research track, not an application release or validated quantum policy.**

Base commit: `81e5fb8228ecd65e108f9d9a6edf325f3d2b5f7e` (stable v0.4). All existing science and workbench source remain unchanged. The research branch is `research/v0.5`. The public Pages preview is at https://hasan1s7.github.io/adaptive-quantum-chemistry/research/; the original acquisition preview remains at the root. Pages has no backend and cannot protect reference labels. Only derived research results and generated geometries are redistributed; neither supplied document is uploaded. No Nabu access, live quantum calculations, MLIP training, external partnerships or paid compute.

## Question and progression

The supplied thesis motivates matched linear/circular potential-energy-surface (PES) slices, Chebyshev spectral and curvature diagnostics, perturbation amplitude and centre-level dependence. The founders' white paper motivates objective-specific statistical reliability, cost-aware acquisition, multi-fidelity and eventually rare-event degradation. The experiments ask whether a feature improves *decisions* after accounting for its acquisition cost. The original thesis data/models were not supplied, so our metric definitions are explicit proxies rather than a numerical replication. The white paper's rare-event, MD, force-accuracy and industrial goals remain future validation gates.

### A. Existing real conformer labels: exploratory original-development CV

478 molecules, 287 families, five frozen folds; 19 cases where buying the second-ranked reference rescues a failed first choice within 1 kcal/mol. A train-fold-smoothed cheap-gap histogram predicts rescue probability; the policy buys the second reference when that probability exceeds a chosen penalty. The 2% threshold uses 802 calls for 455/478 successes vs fixed top-2's 956 calls and 457 successes (16.11% call savings, -0.418 pp success difference). Conditional paired-family bootstrap: savings [13.42%,19.05%], success difference [-1.07,0] pp. Constant Brier .038209 vs gap .035697. Thresholds exploratory, no equivalence or untouched external holdout. Exact three Git blobs were fetched and computed in connector V8. The byte-pinned local Node script passed fixture tests; full local Node replay still requires an accessible checkout. See `analytic/results/real-results.json`, `analytic/real_diagnostic.js`. Original sealed sequential feedback 455/478 using 973 calls vs matched simple 457/478 using 964 calls remains negative and unchanged.

### B. Analytic stress regimes

7,200 synthetic trajectories; four regimes with common random numbers, 40 train and 20 held-out synthetic centres per regime. Five directions, three amplitudes, two paths, 128 points. At free probe cost, 15/60 shape comparisons improve utility, 32 tie, 13 worsen; at hypothetical per-point costs .001 and .01 comparison equivalents, none improves. These analytic surfaces are not chemistry. All numerical definitions and evidence are in `analytic/`.

### C. New molecular force-field pilot (executed)

36 newly generated molecules (not a borrowed experimental dataset), 12 explicit chemical-class blocks. Train: alkanes, alcohols, ethers, ketones, esters, amines, cycloalkanes, aromatics (24 molecules); test: amides, nitriles, thioethers, haloalkanes (12 molecules). Canonical identities unique, class blocks disjoint. This is a new holdout *within this generated pilot*, not a certified fresh external scaffold-family holdout; cross-class chemical similarity is not excluded. Four held-out blocks and 12 molecules cannot establish population guarantees. Source/protocol saved and hashed before execution.

RDKit 2025.09.4, NumPy 2.3.5, Python 3.13.5. Deterministic embedding and MMFF94 optimization for each centre; all 36 embeddings and optimizations converged. Each centre gets five orthonormal, translation-removed directions, three RMS per-atom displacement amplitudes (0.05, 0.10, 0.20 Å), and matched linear/circular paths of 128 points. 720 train and 360 held-out paths (1,080 total; 138,240 sample evaluations **per** force field, 276,480 paired-model evaluations; shared centres make them dependent). UFF is the cheap feature model and MMFF94 the comparison label, **not established higher fidelity or quantum truth**. Neither xTB nor DFT is available locally. No neural potentials are trained. Both force fields evaluated the same coordinates; the coordinate-evaluation test compares against a newly initialized force field. Nonbonded thresholds are deliberately large; fixed connectivity; no bond breaking or actual dynamics.

Spectral metric: degree-16 Chebyshev least-squares fit to centred energy along path parameter, fraction of nonconstant coefficient power above degree 2. MAC proxy: mean absolute second derivative of energy w.r.t. arc length (finite differences; circular wrap). Translation removed, rotational components not projected out. Path length, geometry and parameterization differ between linear and circular. Amplitude is defined as RMS displacement, not claimed identical to thesis normalization. Reference shape metrics used only for retrospective assessment. Candidate indices 0,14,28,42,56,71,85,99,113,127; regret relative to best of ten comparison energies. Fit histograms on train only, using prior pseudocounts. Shape rules buy 118 extra UFF evaluations per trajectory. Reference labels for test paths are evaluator-only; static Pages is a retrospective display. No optimization after seeing test outcomes.

| Primary penalty .05 | Held-out success | Comparison calls | Cheap points | Mean regret (kcal/mol) | Total cost equivalents | Utility |
|---|---:|---:|---:|---:|---:|---:|
| Fixed top-1 | 303/360 | 360 | 3,600 | 1.615 | 3,511.9 | 0.35390 |
| Fixed top-2 | 333/360 | 720 | 3,600 | 0.530 | 3,871.9 | 0.38723 |
| Gap | 331/360 | 670 | 3,600 | 0.571 | 3,821.9 | 0.38862 |
| Gap + spectral | 331/360 | 672 | 46,080 | 0.560 | 41,016.5 | -4.77729 |
| Gap + MAC | 329/360 | 612 | 46,080 | 0.590 | 40,956.5 | -4.77451 |

The gap rule saves 50 comparison calls (6.94%), at two fewer successes (-0.56 pp), or roughly 1.29% of total modeled cost at the measured training ratio. Cost ratio measured using batched `CalcEnergy` wall time, excluding setup and metric computation; training UFF 7.880 μs, MMFF94 9.001 μs, ratio .875531; repeat ratio .879936. These are hardware- and implementation-specific local CPU timings, not xTB/DFT or money. The excluded overhead makes dense shape probing look more favorable, not less. Total cost = comparison calls + ratio × cheap samples; utility = success fraction − penalty × cost per trajectory. None of the six shape policies at three penalties beats gap-only utility under measured cost. At primary penalty, MAC can only beat gap at a hypothetical ratio below 18/42480 (~.000424); the spectral policy cannot at any nonnegative ratio. These are algebraic break-even calculations on fixed observed outcomes, not future performance guarantees.

D = (MMFF94−UFF complexity)_linear − (MMFF94−UFF complexity)_circular: 60 pairs per amplitude per metric, descriptive equal-class means. Spectral means -0.122265, -0.027713, +0.066893; MAC means -64.620376, -84.490697, -131.515312 kcal/mol/Å². They measure two different properties and do not prove a slicing effect, MLIP simplicity bias, or equivalence. No population-level significance test with only four held-out class blocks. All class means available in `run/summary.json` and Pages controls. The dense shape feature did not earn its cost. **Reject production adoption at this evidence level.**

## Reproduce

From this directory with Python 3.13.5 and the pinned local packages (RDKit 2025.09.4, NumPy 2.3.5), Node for the separate real replay:

```sh
python molecular_pilot.py --out new-pilot
python -m unittest -v test_molecular_pilot
(cd analytic && python -S -m unittest -v test_shape_lab && node test_real_diagnostic.js)
(cd analytic && python -S shape_lab.py --out new-synthetic)
(cd analytic && python -S sensitivity.py new-synthetic/trajectories.csv new-synthetic/sensitivity.json)
node analytic/real_diagnostic.js /path/to/pinned/original-repo new-real-results.json
python -m http.server 8766 --directory pages --bind 127.0.0.1
```

The unit tests read the delivered `run/summary.json`, not a rerun's output. All six pilot component checks passed, and a separate run exactly reproduced all 1,080 non-timing trajectory records. The old analytic unit suite passed 10/10 and the Node fixture checks passed. Raw data saved in compressed form to reduce transport, restore with `gzip -dc run/trajectories.jsonl.gz > run/trajectories.jsonl` (and `gzip -dc analytic/results/trajectories.csv.gz > analytic/results/trajectories.csv`) if the uncompressed files are not present. `build_data.py` rebuilds the exact Pages data from those recorded summaries and uncompressed pilot rows; `repeat/summary.json` provides the repeat timing. Use `cd pages && python test_pages.py` for Chromium checks. The browser in this workspace blocked direct HTTP navigation, so HTML and exact asset bodies were tested via set_content/script injection; CSP/hosted navigation not tested by that harness. Passed 3 real thresholds, 18 pilot cost/penalty settings, 6 paired conditions, 18 viewer combinations, invalid input, keyboard rotation, actual CSV download, widths 320/390/430, no JS errors. Screenshots and raw test logs are in the downloadable archive, the small logs/receipt are in `verification/`.

## Next gates, not completed

Permissioned quantum-reference matched path labels (actual GFN2-xTB or DFT and explicit cost measurement), MLIP baseline and independent model training, fresh external scaffold-family holdout, pre-specified matched-risk/utility test with enough families, cost-inclusive probe decisions, rare-event/MD/industrial validation. Confirm exact thesis metric definitions with author-provided numerical data. Do not promote force-field proxy results into quantum or industrial claims. Stable v0.4 app and its sealed results are unchanged; full application suite not re-run this turn.
