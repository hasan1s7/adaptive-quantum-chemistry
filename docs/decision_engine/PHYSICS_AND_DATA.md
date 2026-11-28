# Erkidu physics and source review — 27 November 2026

## Recommended benchmark and the claim it supports

Choose a licensed **WBM same-composition oxide ranking replay**, using published CHGNet, MACE-MP-0 and M3GNet relaxed-energy predictions against WBM DFT-relaxed labels. This is an **energy-only, whole-relaxation reference-acquisition experiment**. It does not test a reference single point at the MLIP geometry, force error, molecular dynamics, ionic conductivity, battery degradation, synthesis, or experimental stability.

The candidate is an initial periodic structure. Each predictor performs its own structural relaxation and estimates a final energy. The oracle reveals the recorded DFT relaxation outcome for that candidate. Consequently, the accepted and reference geometries can differ. Call the query `reference_relaxation`, not `single_point`. A successful ranking decision remains valuable for computational screening even when no material is generated.

### Benchmark comparison

| Candidate workflow | Concrete endpoint | Useful data | Main limitation for this experiment | Recommendation |
|---|---|---|---|---|
| Battery materials screening | Rank candidate structures with a fixed composition before spending more DFT relaxations | WBM contains periodic inorganic candidates; modern MLIPs cover relevant elements | A correct relaxed-energy ranking establishes neither conductivity nor electrochemical or cell performance; redox/magnetism and +U conventions complicate many battery chemistries | Keep as a later vertical with a buyer-defined endpoint; do not lead with battery performance |
| Benign ceramic/solid-state screening | Choose a low-energy basin from a fixed candidate pool of charge-balanced simple oxides | WBM + published Matbench predictions, CC BY 4.0; many independently grouped compositions | Predictions and labels are relaxed outcomes; missing force/trajectory labels; known pretrained support overlaps | Best initial materials replay, with explicit protocol and overlap limits |
| Ordinary closed-shell molecular conformers | Find a conformer within a prespecified energy regret of the reference best in a fixed pool | Existing Erkidu/Folmsbee–Hutchison replay; rMD17 adds actual compatible E/F data | Existing examined conformers are development data; rMD17 has only ten originating molecular trajectories; pharmacological claims unsupported | Reproduce existing baseline, use it as an engineering regression and development evidence |

The original-author rMD17 repository makes small datasets feasible: commit `4f6bb0a186822c90d47cd98b7a27991fe0b3173b` contains 1,000-frame train/test NPZ files for all ten molecules. Coordinates are Å, energies kcal/mol, forces kcal/mol/Å, and `old_indices` retains MD17 provenance. Labels are PBE/def2-SVP with tight SCF and dense integration; CC0. It is not the chosen main benchmark because frames from each trajectory are correlated and ten molecular systems are a weak basis for a new-family guarantee. Do not combine rMD17 labels with SPICE/MACE-OFF labels: the latter use a different functional/basis protocol.

## Frozen source artifacts

The inspected Matbench repository head is `58b3bd5b95c1165c5208150203007cea0031c64c`. The original research captures were stored in a local source cache. The public release includes scoped metadata extracts in `data/decision_engine/source_metadata/`; `sources.json` distinguishes captured-source and published-extract checksums. This is a recent head, so byte checksums and source commit are essential rather than relying on the package's version label.

| Artifact | Exact file | Download | Published MD5 |
|---|---|---|---|
| WBM summary | `wbm/2026-11-19-wbm-summary.csv.gz` | https://ndownloader.figshare.com/files/71653870 | `e63906af07b0408ee3eaa7028aa02d27` |
| CHGNet v0.3.0 | `models/chgnet/chgnet-0.3.0/2026-11-19-discovery.csv.gz` | https://ndownloader.figshare.com/files/71653801 | `3944fdbf7d1b041aae6ea811011008cc` |
| MACE-MP-0 medium | `models/mace/mace-mp-0/2026-11-19-discovery.csv.gz` | https://ndownloader.figshare.com/files/71653786 | `3bfe7826a613684a92a7dd28643cac9f` |
| M3GNet v2022.9.20 | `models/m3gnet/m3gnet/2026-11-19-discovery.csv.gz` | https://ndownloader.figshare.com/files/71653831 | `b9bcef0e065876de910516b9a1f7a777` |
| MP public support table | `2025-02-01-mp-energies.csv.gz` | https://ndownloader.figshare.com/files/52080797 | `7eb0c49fc169ba92783f2f6d0d19d741` |
| Prior WBM summary, protocol audit only | `2023-12-13-wbm-summary.csv.gz` | https://ndownloader.figshare.com/files/44225498 | `fb23d85dab61fab001b92cb0ac4f8f3d` |

Figshare API metadata was read directly. Data Files article **22715158, version 42**, and Model Predictions for Discovery article **28187990, version 31**, both state **CC BY 4.0**. The predictor IDs above are present in the latter article. MPtrj article **23713842, version 2**, states MIT. The supplementary rMD17 article **12672038, version 4**, states CC0. Keep attribution and provenance when packaging subsets.

The published prediction CSVs contain only `material_id` and `e_form_per_atom`. Their existence establishes a prediction, not a successful convergence test. The CHGNet table has 256,963 rows, MACE 256,925, M3GNet 256,610; finite-value and selected-cohort checks remain necessary. Missing predictions cannot simply disappear from the denominator. The source WBM summary contains 256,963 rows.

## Physics contract

The primary WBM paper specifies VASP, PAW datasets version 5.2, a 520 eV plane-wave cutoff, Gamma-centered reciprocal sampling at 1,000 points per reciprocal atom, energy convergence better than 2 meV/atom, and relaxation termination below 0.005 eV/Å. Calculations are spin-polarized PBE, with specified +U values for selected Co/Cr/Fe/Mn/Mo/Ni/V/W oxides or fluorides. Our simple-oxide roster excludes those +U elements. No dispersion correction is stated in the cited DFT protocol. The structures are bulk periodic crystals; the summary does not include individual INCAR/KPOINTS/POTCAR hashes, magnetic initializations, final magnetic moments, or per-job SCF traces. Mark those fields unavailable rather than inventing them. Pseudopotentials require a separately licensed VASP installation for fresh reproduction.

Matbench's CHGNet and MACE cards describe FIRE optimization, a Frechet cell filter, at most 500 steps, and 0.05 eV/Å maximum force; M3GNet uses ExpCellFilter. These surrogate settings are different from the DFT protocol. Energy-only replay must not imply that force or stress errors were evaluated. The displayed model metadata include environment records that have evolved after the historic relaxations; use the *published prediction file* as the executed artifact and do not claim locally reproduced MLIP inference.

Use eV per atom consistently. Convert regrets to meV/atom only for display. Within an identical reduced composition, elemental formation reference constants cancel. MP2020 anion corrections can still depend on structure, so this cancellation alone is insufficient for the full WBM set. No cross-composition formation-energy ranking or convex-hull inference belongs in the current endpoint.

### Executed correction audit and prequery eligibility

Before looking at model performance, apply a fixed composition rule: require oxygen and at least one cation, permit only the following formal valences, and require their stoichiometric charge sum to be zero.

* Li, Na, K, Rb, Cs: +1.
* Mg, Ca, Sr, Ba: +2.
* Al, Ga, Sc, Y, B: +3.
* Si, Ge, Sn, Ti, Zr, Hf: +4.
* O: −2.

This deterministic, prequery composition rule selects **597 structures, 305 reduced compositions, of which 110 have at least two candidates**, before other leakage or missing-data exclusions. The check is recorded in `physics_source_cache/oxide_correction_audit.json`.

The audit compared old and new source correction columns for the whole eligible set. **Zero of its structures changed MP2020 correction between the 2023 and 2026 releases, and zero eligible compositions have variable correction per atom** at a 1e-6 eV/atom tolerance. Thus within-composition normalization by a public, fixed anchor removes these constants for this preselected cohort. The audit uses reference metadata only to validate the protocol; it must not supply acquisition features, change candidate membership after observing performance, or expose reference values in traces.

Why the audit matters: the current Matbench commit changed 3,044 WBM anion corrections and shifted 15 model prediction files by the same per-entry correction changes. This would introduce oracle-derived harmonization information for arbitrary new pools. The chosen composition rule happens to avoid all of these changes and all within-pool correction variation. Do not generalize that result to the rest of WBM. Do not subtract hidden DFT corrections from each model prediction as a purported prequery operation.

## Availability and contamination

Allowed before a query: input candidate identity; composition; atom count computed from the input composition; `protostructure_spglib_initial_structure`; deterministic generation round encoded in the WBM ID; published MLIP prediction values; public MP support data; already queried observations. A future raw-geometry deployment can additionally use initial distances, neighbor environments, and model embeddings.

Unavailable before the corresponding oracle query: DFT energy, DFT-relaxed volume, final DFT prototype, DFT bandgap, final magnetic moments, and `site_stats_fingerprint_init_final_norm_diff` because it compares the initial and final DFT geometries. Crucially, **`unique_prototype` is not a clean prequery feature or cohort rule**: it uses DFT-relaxed prototypes and keeps the lowest DFT-energy representative among duplicates. A clean workflow should deduplicate by initial structure/prototype and a deterministic non-label tie-break; final duplicates may be diagnosed after evaluation without changing the primary endpoint.

CHGNet and MACE-MP-0 share MPtrj as a training corpus. M3GNet used initial/middle/final structures from an earlier Materials Project corpus of 62,783 trajectories. Their errors are not independent draws. The official registry acknowledges WBM prototype overlap with MPtrj. No downloaded public summary proves absence of exact training structures or related basins. Report overlap as a limitation and keep a diagnostic count of final-prototype overlaps separate from policy inputs. There is no clean-pretraining or independent-validation claim.

The MP support table has 154,718 rows with composition, site count, and relaxed prototype strings. A distance or prototype-membership signal based on this table is a **public Materials Project support proxy**. It is not a learned embedding distance, and it does not establish membership in each model's exact train split. It overapproximates some model supports and uses a different historical snapshot from M3GNet. Either use that precise label or call a nearest-neighbor signal built only from policy-fitting families “distance to policy-fit support.”

Split whole chemical systems or other explicit structural family groups before fitting calibration or tuning. Keep all same-composition candidates together and use initial-geometry deduplication. Within this limited oxide roster, a shifted test cohort such as explicitly held-out cation families is feasible, but any resulting coverage is empirical; it is not exchangeable with a random in-distribution calibration split. Neighboring frames do not arise in these final-structure tables, but equivalent initial prototypes and shared substitution lineages remain possible.

## What the sources imply for company B

Formulation B has a plausible wedge if it sells a measurable reduction in expensive decisions at a buyer's tolerated regret, with failure handling and auditable evidence. It cannot claim novelty merely because an uncertainty threshold triggers DFT. DP-GEN and FLARE already implement active acquisition around atomistic models. The differentiator to test is **decision-specific, model-independent acquisition with actual job costs and explicit abstention**, measured against frozen top-k and simple gap rules.

A published study reports common systematic softening across M3GNet, CHGNet, and MACE-MP-0. This supports testing shared high-confidence failures: low disagreement is not evidence of low error by itself. A common training corpus makes disagreement a useful signal to evaluate, not a calibrated guarantee. Neither this source nor the replay establishes customer willingness to pay. The paid pilot remains a commercial hypothesis until a buyer accepts an agreed endpoint, baseline and evaluation scope.

Model licensing should be specific. MACE-MP-0 weights are listed as MIT by the official foundation-model repository; MACE-OFF23 weights are under an Academic Software License with commercial use excluded. The inspected Matbench cards call CHGNet code/checkpoint BSD-3-Clause. The M3GNet card's checkpoint field says MIT but links to an upstream BSD-3-Clause license; preserve that discrepancy and resolve it before distributing those weights. This experiment needs only the licensed published prediction data and does not redistribute pretrained weights.

## Sources

Primary URLs and exact local snapshots are enumerated in `physics_sources.json`. Particularly useful web citations are the WBM primary paper, Matbench primary paper, official original-author rMD17 repository, official MACE foundation-model cards, the Matbench correction issue, DP-GEN, FLARE and the systematic-softening study. The parent response must open any subagent web source before citing its retrieval reference.

## Executed initial-geometry extraction

`erkidu/tools/prepare_wbm_geometries.py` downloaded the pinned initial-structure archive at https://ndownloader.figshare.com/files/53161835, verified MD5 `b809f101dd42a745ec2baabe7eb16f11` and SHA-256 `98d545172c1ea9060f03f40cace6f8173a4ac06f1ee875ccd963765211519b58`, then streamed the JSONL records. Eligibility was recomputed from initial-site element counts using the formal-oxide rule; no reference energy, final geometry or summary label was used. The result is `erkidu/data/decision_engine/initial_geometries.json.gz` with 597 initial structures, 305 compositions and zero invalid records. Each has input lattice, Cartesian and fractional coordinates, PBC, atomic numbers, source-record and canonical geometry digests, and the original initial-structure object for future reference input construction. The source charge is null and stays explicitly unknown.

`initial_geometry_audit.json` records three literal duplicate groups and five conservative near-duplicate candidate pairs. The latter uses equal atom counts, relative volume within 0.001, and species-labelled periodic pair-distance spectra with RMS difference <=0.01 Å and maximum difference <=0.03 Å, using images [-2,2]^3. This screens possible duplicates; it is not a complete crystallographic equivalence certificate. All detected pairs share composition, so placing whole chemical systems into one split prevents these pairs from straddling train/calibration/test. The full 49.5 MB archive remains a temporary source; the deliverable subset is approximately 317 KB.

Reproduce with `python tools/prepare_wbm_geometries.py --archive /path/to/2022-10-19-wbm-init-structs.jsonl.gz --download` from the Erkidu repository.
