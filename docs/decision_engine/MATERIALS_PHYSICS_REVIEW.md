# Ahmad's materials physics review — SnO₂ ranking failure

**Evidence:** executed labeled replay. **Fresh DFT jobs:** zero. **Live MLIP inference:** zero. The SnO₂ pool was in the frozen `test` split during execution; after this inspection it is an examined development case. It is suitable for forensic reproduction, not for another claim of independent validation.

## Decision

The decision-aware second query rescues one failure of MACE fixed top-two, but this is not a reason to deploy the adaptive policy. M3GNet-only chooses the same acceptable endpoint with no reference query. Retain this case as a stringent test of reference-job provenance, stopping, and model failure diagnosis. The best next physics experiment asks why the models disagree on which initial structures relax into low-energy outcomes.

This is a fixed-pool decision: choose a candidate whose **recorded DFT-relaxed energy is within 20 meV/atom of the best recorded energy in this pool**. It does not identify the global SnO₂ ground state, prove experimental phase stability, or establish any material application property.

## 1. The five actual candidates

Published predictions and reference values below are MP2020-corrected formation energies in **eV/atom**. The correction is **−0.458 eV/atom for every row**, so it cancels from these same-composition ranking differences. Each model's value is the outcome of its own structural relaxation from the initial candidate, not a single-point value evaluated at a shared final geometry.

| Initial candidate | Atoms in input cell | MACE-MP-0 | CHGNet | M3GNet | DFT relaxed label | Reference regret, meV/atom |
|---|---:|---:|---:|---:|---:|---:|
| `wbm-1-37760` | 9 | −1.7687 | −1.7277 | −1.7566 | −1.784614 | 264.613 |
| `wbm-1-37761` | 9 | −1.7686 | −1.7291 | −1.7567 | −1.785227 | 264.000 |
| `wbm-1-37762` | 12 | −1.7505 | −1.7177 | −2.0394 | −2.049197 | 0.030 |
| `wbm-2-33797` | 6 | −1.7397 | −1.6955 | −1.7112 | −2.049227 | 0.000 |
| `wbm-4-25075` | 9 | −1.8567 | −1.8479 | −1.8646 | −1.861420 | 187.807 |

These values are reproduced from the pinned source tables, with exact IDs, geometries, digests and trace references in [`materials_physics_case.json`](materials_physics_case.json). No molecule, phase or material property was generated or measured in this review.

### Geometry evidence

| Candidate | Published initial prototype | Published final DFT prototype | Initial volume, Å³ |
|---|---|---|---:|
| `wbm-1-37760` | `A2B_hP9_152_c_a:O-Sn` | `A2B_mC18_5_3c_ac:O-Sn` | 129.144563 |
| `wbm-1-37761` | `A2B_hP9_154_c_a:O-Sn` | `A2B_mC18_5_3c_ac:O-Sn` | See source geometry record |
| `wbm-1-37762` | `A2B_tP12_92_b_a:O-Sn` | `A2B_tI12_141_e_a:O-Sn` | 188.707790 |
| `wbm-2-33797` | `A2B_tI12_122_d_a:O-Sn` | `A2B_tI12_141_e_a:O-Sn` | 100.041125 |
| `wbm-4-25075` | `A2B_cF12_225_c_a:O-Sn` | `A2B_cF12_225_c_a:O-Sn` | 121.885265 |

Final DFT prototypes are **evaluation-only information**. They never entered the acquisition payload. The two lowest-label candidates begin with different initial prototypes and have the same final prototype label. Their final-cell sizes differ. A shared prototype label is evidence of related endpoints, not a complete atom-by-atom equivalence proof.

## 2. Two real failure modes

### Case A — apparently separated winner, wrong terminal decision

MACE places `wbm-4-25075` 88 meV/atom below its second-ranked input. Its absolute energy prediction for that candidate is accurate to approximately 4.72 meV/atom relative to the published label. The failure is in the competing candidates: the model predicts the low-energy endpoints too high, making the selected cubic input appear decisively preferable.

| Frozen arm | Actual reference-query sequence | Selected input | Calls | Regret, meV/atom |
|---|---|---|---:|---:|
| MACE fixed top-two | `wbm-4-25075`, `wbm-1-37760` | `wbm-4-25075` | 2 | 187.807 |
| Decision-aware acquisition | `wbm-4-25075`, `wbm-1-37762` | `wbm-1-37762` | 2 | 0.030 |
| M3GNet-only | None | `wbm-1-37762` | 0 | 0.030 |
| Frozen 50 meV energy-gap stop | `wbm-4-25075` | `wbm-4-25075` | 1 | 187.807 |
| Frozen constant-width calibrated interval | `wbm-4-25075` | `wbm-4-25075` | 1 | 187.807 |
| Disagreement-scaled interval fallback | All five | `wbm-2-33797` | 5 | 0.000 |

The constant-width rule reports a certificate under its calibration assumptions and is wrong on this case. Its frozen half-width is 77.024 meV/atom. After the first observation it lower-bounds the unqueried `wbm-1-37762` at −1.832244 eV/atom, but the actual label is −2.049197 eV/atom, outside that interval. The certificate is not a blanket correctness guarantee.

The decision-aware second query is supported by information actually available at the time: the anchored cross-model disagreement of `wbm-1-37762` is 169.589 meV/atom and its fitted scale is 127.063 meV/atom. The logged expected-improvement score is 0.01433345 eV/atom. Competing second-query scores are near zero. At that point only the reference label of `wbm-4-25075` had been revealed.

Do not interpret the first candidate's zero *anchored* disagreement as measured certainty. Subtracting each model's prediction on that anchor forces its disagreement to zero. The fitted uncertainty still has a nonzero floor. Likewise, its exact match to a public MP prototype is a support indicator, not a correctness certificate.

### Case B — shared blind spot hidden by successful pool selection

All three models substantially overestimate the relaxed reference energy of `wbm-2-33797`:

| Model | Prediction error for `wbm-2-33797`, meV/atom |
|---|---:|
| MACE-MP-0 | +309.527 |
| CHGNet | +353.727 |
| M3GNet | +338.027 |

M3GNet succeeds at the terminal selection because it recognizes a different initial input, `wbm-1-37762`, that reaches a practically tied reference endpoint. Thus perfect observed pool-level success does not establish accurate potential energies on every candidate, force reliability, or successful generalization to a pool that omits that rescuing input. This is a concrete correlated-error failure despite terminal success.

The primary literature reports systematic softening across these three model families, which makes shared failure modes plausible, but this particular case does **not** establish softening as its cause. [Deng et al., systematic-softening study](https://www.nature.com/articles/s41524-024-01500-6).

## 3. What the case does and does not establish

**Observed:** frozen fixed top-two misses an acceptable endpoint; changing the second query rescues that miss at the same two-call budget. Simple diversity, disagreement and uncertainty policies also find an acceptable endpoint in this pool. M3GNet-only finds it without any new reference label. Two lower-label inputs have the same final DFT prototype and differ by only 0.03 meV/atom.

**Hypotheses requiring new evidence:** the models may relax into different basins; optimization or symmetry handling may preserve a high-energy configuration; potential-energy errors may misorder related basins; an individual historical DFT or MLIP run may need a convergence audit. The selected energy CSVs do not contain MLIP final geometries, convergence flags, ionic trajectories or step counts, so these alternatives cannot be distinguished here.

The source paper reports energies converged better than 2 meV/atom. The 0.03 meV/atom ordering of the two best labels lies far below that scale and below the source prediction precision. Treat those endpoints as tied for this review. The adaptive policy's near-zero mean regret does not provide evidence of physical superiority at thousandths of a meV/atom. Conversely, the 187.807 meV/atom fixed-top-two miss is much larger than the stated convergence scale and the 20 meV/atom decision tolerance. [Wang, Botti and Marques, WBM protocol](https://www.nature.com/articles/s41524-020-00481-6).

## 4. Proposed four-input forensic batch

The following complete **initial** POSCARs and deliberately unfinished settings templates have been exported to `proposed/fresh_sno2_batch/`:

1. `wbm-4-25075`: the selected high-energy cubic endpoint.
2. `wbm-1-37760`: the fixed-top-two second query.
3. `wbm-1-37762`: the adaptive second query and M3GNet-only choice.
4. `wbm-2-33797`: the recorded reference minimum and shared model blind spot.

The fifth input is a closely related high-energy alternative and is omitted to keep this forensic batch bounded. That omission is a development choice made after inspection; it cannot support an independent policy-validation claim.

### Reference work and cost cap

Stage one proposes four initial-geometry single points, four variable-cell relaxations, and four final static checks: **at most 12 reference jobs**, with each attempt, failure and restart separately logged. Initial single points measure a different endpoint from relaxed energies and must be kept in separate result fields. The first pass has no automatic retries. A starting planning estimate is eight CPU ranks and 16 GiB per job, one job at a time, with a 60-minute wall cap per job. This implies a maximum 96 CPU-rank-hours if every proposed job reaches its cap; it is an unmeasured planning limit, not an estimate of expected runtime or cost. Ahmad must size it against his actual VASP installation and available hardware before any paid submission.

Start with the same PBE target, no +U for SnO₂, no added dispersion, a 520 eV cutoff, and force termination at 0.005 eV/Å. The proposed tighter electronic `EDIFF=1e-6` eV, smearing, symmetry handling and other template settings are **new audit choices**, not recovered historical inputs. The exact Gamma mesh, PAW symbols and hashes, VASP build, charge convention and site-ordered initial magnetic moments require review. Source `charge` is null; a neutral formal Sn⁴⁺/O²⁻ interpretation is the intended starting hypothesis, not a recovered electronic-input record. The paper describes spin-polarized calculations but does not provide this batch's magnetic initializations. The original study used PAW version 5.2. [Primary protocol](https://www.nature.com/articles/s41524-020-00481-6).

Do not claim exact historical reproduction when the software build or PAW files differ. Archive those differences and assign a new protocol ID. Pin the k-point mesh and verify energy differences at the chosen numerical tolerance. Report energies in eV/cell and normalize by the actual atom count; do not compare different cells' total energies directly.

### Commands prepared, not executed

Regenerate the review kits locally:

```bash
python tools/export_fresh_vasp.py \
  --geometries data/decision_engine/initial_geometries.json.gz \
  --out proposed/fresh_sno2_batch
```

There is no DFT or scheduler invocation in the exporter. It writes `POSCAR`, `INCAR.relax.template`, `INCAR.single_point.template`, `KPOINTS.template`, `POTCAR.spec.json` and a machine-readable batch manifest. It does not supply licensed POTCAR bytes.

Only after settings are reviewed and compute is approved, the operator can copy the relevant template to `INCAR`, replace all review placeholders, create the reviewed `KPOINTS` and licensed `POTCAR`, preserve input hashes, and use the site's approved VASP launcher in one case directory. For example, an existing local MPI installation might use:

```bash
mpirun -np 8 vasp_std > vasp.stdout 2> vasp.stderr
```

That command has **not** been run. A scheduler, license, machine-specific MPI setup and elapsed queue time remain outside this package.

### Required readout and stop rules

Record SCF convergence, maximum final force, stress, ionic steps, final cell/geometry, initial/final energies and forces, magnetic moments, input/version hashes, CPU/wall/queue time, and every failed attempt. Stop at the declared wall or step cap. Do not treat a finite energy from a nonconverged run as a successful reference label. If a different electronic protocol is needed, keep its outputs in a separate comparison.

This first batch can compare initial single-point ranking with actual relaxation and confirm whether the large fixed-top-two miss persists. It cannot isolate potential-energy error from basin-selection error by itself. Doing that also requires the actual MLIP final geometries and DFT single points on selected model-relaxed endpoints; that is a separately reviewed extension, not hidden inside the 12-job cap.

## 5. Ahmad's 45-minute review

Spend 15 minutes inspecting the four initial POSCARs and the two low-energy final-prototype records; 15 minutes locking the physical charge/spin intent, PAW family, convergence target and electronic protocol; and 15 minutes deciding whether the evidence justifies the bounded forensic batch. The deliverable from the call is a signed-off input/protocol record or a specific blocking discrepancy. No materials-performance or customer-readiness claim follows from this replay.

**Recommendation:** keep the model-independent oracle, provenance, physical-unit checks and honest failure reporting. Do not promote adaptive acquisition or generation on the strength of this single rescue. The simpler M3GNet baseline must remain in the next evaluation, and this examined SnO₂ family must not become a fresh test family after any adjustment.
