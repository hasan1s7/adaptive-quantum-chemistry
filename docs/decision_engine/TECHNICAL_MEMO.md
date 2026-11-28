# Erkidu: MLIP and DFT decision engine
## Technical memo · 27 November 2026
### Hasan Laith and Ahmad Alsheikh

**Decision:** retain formulation B as a research-grade reliability and evaluation layer. Do not promote the current adaptive policy as a demonstrated way to save compute. It rescued one MACE top-two failure at equal reference count, but a prespecified frozen M3GNet baseline achieved the same tolerance success with no reference acquisitions. The useful product today is a defensible evaluation, protocol audit and decision record.

**Scope:** implemented and executed locally in the existing Erkidu repository at base commit f2a603e14f1d704084f6ddcb07645f2f701fa844. No GitHub push, deployment, outreach, new MLIP inference, fresh DFT calculation or paid compute was performed. Historical conformer replay, new materials replay, synthetic faults, exact mathematical examples and geometry-only generation remain separately labelled.

## 1. What the company should do

The scientific agenda is to determine which additional observation can change an expensive scientific decision, while preserving the distinction between what was known then and what was learned later.

The initial paid unit should be one auditable screening-batch evaluation: a customer's compatible structures, frozen model outputs, reference protocol, selection tolerance and actual job-cost records. Its output is a recommendation to accept a surrogate choice, buy a particular reference result, escalate the pool, or abstain. It remains useful without discovering a material: the customer learns whether a model, a simple top-k workflow, or a proposed acquisition rule makes better decisions for the work already arriving.

The following buyer and value propositions are hypotheses for interviews, not evidence that customers have agreed to buy.

| Formulation | Buyer and incumbent workflow | Unit of value | Data dependency | Possible moat | Strongest failure |
|---|---|---|---|---|---|
| A: a better ML interatomic potential | Simulation lead replacing or fine-tuning a public/internal potential | Better energy/force decisions or a larger valid domain per unit compute | Broad compatible energies, forces and stresses, coverage of relevant states, training compute | Proprietary reference coverage and a sustained transfer or efficiency advantage | This project has demonstrated no new potential advantage; migration cost and rapidly improving public models can erase a small gain |
| B: reliability and acquisition across MLIPs and reference workflows | Computational materials lead or simulation-platform owner using fixed top-k, expert checks, uncertainty thresholds and failed-job queues | Lower decision risk at the same actual cost, or lower actual cost at the same decision quality; a usable audit when simple rules win | Fixed pools, versioned predictions, compatible references, logs and costs from the customer's workflow | Outcome-labelled workflow history, protocol adapters, calibrated stopping, failure handling and evidence that changes real allocation | Simple baselines may already be sufficient; integration can consume more value than acquisition saves |
| C: end-to-end discovery for one material class | Materials R&D owner choosing a composition/structure for a downstream experiment | A validated candidate or shorter validated development cycle | Everything required by B plus generation, physical validation, synthesis and application testing | Exclusive validated candidates and a repeatable discovery-to-validation pipeline | A favourable energy proxy may not survive synthesis, stability, processing or application tests |

B is the best initial scope because it asks a measurable question before demanding a new model or a new material. That does not make uncertainty-triggered reference acquisition novel. DP-GEN already combines exploration, labelling and training; FLARE already uses uncertainty to choose model predictions versus first-principles calculations. Erkidu must earn its place through decision-specific loss, actual costs, clear fallback and interoperability, not through the word “adaptive.” [DP-GEN](https://arxiv.org/abs/1910.12690); [FLARE](https://www.nature.com/articles/s41524-020-0283-z).

This experiment strengthens the engineering case for B and weakens a broad “adaptive MLIP saves DFT” sales claim. The caught correction issue, the strict oracle boundary, the failed constant-width certificate and the zero-query competitor are examples of problems an evaluation product can expose. They are not evidence of willingness to pay.

## 2. Benchmark choice and physical meaning

| Candidate workflow | Feasible first endpoint | Attraction | Limitation and decision |
|---|---|---|---|
| Battery-material screening | Rank structures within one compatible composition | A concrete screening decision with existing surrogate workflows | Ranking does not establish ion conductivity, degradation, synthesis or cell performance. Lithium oxides are retained only as a small shift slice |
| Ceramic / ordinary oxide screening | Select a structure within 20 meV/atom of the best recorded relaxed energy in its fixed composition pool | Published, licensed initial structures, DFT relaxation labels and three frozen MLIP prediction tables | Chosen primary experiment. Energy-only, retrospective, and restricted to simple formal-valence oxides |
| Ordinary molecular conformers | Select a low-energy member of a fixed pool | Existing Erkidu machinery and interpretable regret | Old data use xTB versus DLPNO-CCSD(T), have no compatible forces, and do not encode enough charge/spin information to certify a new closed-shell-only cohort |
| rMD17 molecular trajectories | Energy/force prediction on matched structures | Compatible PBE/def2-SVP energies and forces under CC0 | Ten molecules and correlated trajectories are weak support for the desired cross-family acquisition test; neighbouring frames require careful treatment |

The rMD17 author repository explicitly documents trajectory dependence and matching energy/force units. It remains a sensible later force-adapter test, not a substitute for an independently grouped materials decision evaluation. [rMD17 author data](https://github.com/andersx/rmd17-npz).

### Selected endpoint

A candidate is an **initial periodic oxide structure**. Its prediction is the energy reached by a particular MLIP relaxation. Its reference label is the outcome of a DFT relaxation from that candidate. Querying the reference oracle therefore means acquiring **one historical whole-relaxation outcome**. It is not a single-point DFT calculation at the MLIP geometry, and its cost is not one electronic SCF iteration.

Paid policies must select the best successfully queried candidate. Frozen MLIP-only policies can select an unqueried candidate and are explicitly distinguished. Regret is measured against the lowest compatible reference label in the same fixed pool. Neither the pool nor the result establishes a global ground state or stability against other compositions.

The chosen label is MP2020-corrected formation energy per atom. Within a fixed composition, elemental reference constants cancel. We do not compare these values across compositions, construct a convex hull, infer conductivity or claim materials performance.

### Physics protocol and its limits

The primary WBM paper specifies spin-polarized PBE, VASP PAW 5.2, a 520 eV cutoff, Γ-centred sampling at 1,000 points per reciprocal atom, energy convergence better than 2 meV/atom and geometry optimisation below 0.005 eV/Å. The selected cations exclude the paper's listed +U elements. No dispersion correction is specified for this source protocol. [WBM paper](https://www.nature.com/articles/s41524-020-00481-6).

Initial lattice vectors and Cartesian coordinates are stored in Å, fractional coordinates are retained, and periodic boundary conditions are true in all three directions. Formal valence is a prequery inclusion rule, not a recovered electronic-input charge/spin record. The source geometry charge field is null; exact site-ordered magnetic initialisations, original SCF logs and per-job PAW input hashes are unavailable. Those remain explicit gaps.

The model cards describe FIRE relaxations with a 0.05 eV/Å target and at most 500 steps. That protocol differs from the reference relaxation. The selected prediction CSVs do not include convergence flags, final forces or ionic-step counts. A finite prediction does not prove convergence. No unstable-relaxation frequency is inferred from these tables.

### Versions and licences

The Matbench source snapshot is 58b3bd5b95c1165c5208150203007cea0031c64c. The WBM data article is Figshare 22715158 version 42; the prediction article is 28187990 version 31. The delivered source metadata retains model cards and official checksums. Data attribution is CC BY 4.0. The MACE-MP-0 card identifies MIT code/checkpoint licences; CHGNet identifies BSD-3-Clause. The M3GNet card identifies version v2022.9.20 and checkpoint MP-2021.2.8-EFS, with BSD-3-Clause code and an MIT checkpoint label. Only licensed prediction data are redistributed here. This experiment consumed published predictions, not checkpoint binaries, so it does not claim local weight execution or a locally verified weight-binary checksum.

| Artifact | Figshare file | SHA-256 |
|---|---|---|
| WBM summary, 19 Nov 2026 | 71653870 | 68441da399d68f0da3183c692f51b115957e8da1e2ed809fd03e8859302992a2 |
| MACE-MP-0 predictions | 71653786 | f1b6b185556b9729d4dacaa0db22922352426fe059c4c3fdb4f9fb1a3ce89911 |
| CHGNet predictions | 71653801 | b46584771b4612fd6a2d7020490a0d108b62d53d38f447cc79e5bfc530183496 |
| M3GNet predictions | 71653831 | e3dd233d3ea580a1c3de4a7f4ae6bd71c1dc01c3df47933324c826afd62748cb |
| Initial-structure archive | 53161835 | 98d545172c1ea9060f03f40cace6f8173a4ac06f1ee875ccd963765211519b58 |

The data and predictions are tied to exact file versions rather than a moving “latest” download. The raw downloaded tables, subset geometries, preparation seals and source snapshots make the replay reproducible. The full initial-structure archive is not needed to rerun the delivered subset.

## 3. Recovery of the prior Erkidu result

The four-policy two-call experiment reproduced all four archived scientific outputs byte for byte. It uses 478 already examined molecular development pools and 287 inferred families.

| Historical policy | Success within 1 kcal/mol | Reference-label calls |
|---|---:|---:|
| Fixed top two | 457/478 | 956 |
| Steric overlap | 458/478 | 956 |
| Torsional diversity | 453/478 | 956 |
| Torsion plus steric | 453/478 | 956 |

The steric arm gains one threshold success, while continuous regret improves in nine pools and worsens in twelve. Its mean-regret interval includes no advantage. This remains development evidence and does not promote the steric rule.

A completed 669-call package already exists. Its saved gap-gated rule reaches 452/478 versus 457/478 for top two, with zero threshold rescues and five harms. The two shape variants also reach 452/478, with two rescues and seven harms each. All 1,912 saved policy–molecule rows and source hashes were inspected. **No 669-call policy was rerun.** That saved experiment changes second-candidate selection in the same 191 gated pools; it is different from the proposed fixed-pairs shape-versus-gap allocation test.

Two real historical cases are included in Ahmad's sheet:

- omegapdb_2byi: top two and steric leave 5.146528 kcal/mol regret. The optimum is cheap rank seven, outside the ranks-two-through-five shortlist; all eligible steric scores are zero.
- omegapdb_1bhx: fixed rank two finds the reference minimum, while the more torsionally diverse third-ranked candidate leaves 1.176506 kcal/mol regret.

Those observations expose candidate-set and descriptor failures without inventing a chemical explanation. The old experiment is GFN2-xTB versus DLPNO-CCSD(T) on B3LYP-D3BJ/def2-SVP geometries, not the new MLIP-versus-DFT experiment.

## 4. Data availability, leakage and group construction

A serious problem was caught before evaluation: recent published energy harmonisation includes changes to reference-derived MP2020 corrections. In addition, the dataset's unique_prototype flag is determined using DFT-relaxed prototypes and reference-energy duplicate selection. Such fields cannot enter a pre-reference acquisition policy. [Correction provenance issue](https://github.com/janosh/matbench-discovery/issues/358).

The experiment uses a prequery formula rule: O has formal valence −2; Li/Na/K/Rb/Cs +1; Mg/Ca/Sr/Ba +2; B/Al/Ga/Sc/Y +3; Si/Ge/Sn/Ti/Zr/Hf +4. Compositions contain two through four elements and satisfy formal charge balance. This is a deliberately narrow ordinary-oxide roster.

The source audit found 597 formula-eligible structures and 305 reduced compositions. **No eligible structure changed correction between the audited 2023 and 2026 tables, and no eligible composition has variable per-atom correction.** Each model's predictions are then offset by its value on the first lexicographic candidate in the pool. Composition-constant offsets cancel. The correction audit validates this chosen protocol; correction values are never policy features.

Twenty-eight repeated composition/initial-prototype records are conservatively deduplicated without labels. Two hundred and two remaining singleton records are excluded because they cannot pose a ranking decision. The final cohort is 103 nontrivial pools, 367 candidates and 93 chemical systems. There are no missing prediction pools or missing reference labels in this curated retained cohort. This is not a measured zero rate of failed original jobs.

| Role | Pools | Candidates | Whole chemical systems |
|---|---:|---:|---:|
| Uncertainty fitting | 35 | 147 | 33 |
| Interval calibration | 28 | 88 | 24 |
| Chemistry-disjoint test | 30 | 110 | 26 |
| Lithium-family shift | 10 | 22 | 10 |

Lithium systems are reserved for the shift slice. Remaining systems are SHA-256 ordered with seed 20261127 and assigned 40/30/30 to fitting, calibration and test. The roster, splits, tolerance, models, budgets and seed list were written before evaluation labels were used for fitting or policy selection.

All 367 retained initial geometries passed finite-coordinate, composition, cell and PBC checks. The geometry audit found no exact or screened near-duplicate pair across splits. The one retained GeO₂ near pair stays together in training. The screening method is not an exhaustive crystallographic identity proof.

### Pretrained exposure is a different question

MACE and CHGNet share MPtrj; M3GNet uses related Materials Project data. The public MP support table is an approximation to model support, not an exact reconstruction of each model's training split. Thirty-four retained candidates have an initial-prototype match in that proxy. No claim of fully unseen pretrained chemistry follows.

The distance feature is nearest-neighbour distance in a fixed composition/initial-symmetry descriptor to 2,440 eligible structures from the public MP support table. It is not distance in the neural model's embedding, nor proof of novelty. Shared abstract prototypes across different chemical systems and WBM parent lineage can still correlate errors. We report a chemistry-disjoint retrospective evaluation, not independent prospective validation.

## 5. Decision model, loss and value of information

For pool I, let Y_i be the compatible reference energy of candidate i. Public data contain candidate IDs, initial-structure metadata, frozen model predictions, uncertainty features, protocol IDs and an action budget. The state also records attempted queries, returned successful observations, failures and remaining resources.

The supported actions are: accept the frozen MLIP choice; acquire a reference relaxation label; escalate the remaining pool; or abstain. A force request returns an explicit unsupported state. The broader interface can represent force/single-point actions only after a compatible provider exists.

For a paid policy with successful queried set Q, the terminal choice and loss are

\[
d=\arg\min_{i\in Q}Y_i,\qquad L(d,Y)=Y_d-\min_{j\in I}Y_j.
\]

Stable candidate IDs break ties. Threshold success requires an accepted decision and L ≤ 0.020 eV/atom. We report continuous regret, near ties, tail regret, acceptance and failed attempts separately.

For decision state D, define terminal Bayes risk R(D). The value of a query is

\[
V(q\mid D)=R(D)-\mathbb E[R(D\cup Z_q)\mid D]-\lambda C(q\mid D).
\]

C must eventually be the incremental actual job cost, including failed attempts, queueing and batch effects where relevant. This replay only knows historical label counts, so it evaluates equal-count acquisition and labelled cost scenarios. It cannot assert optimality under unknown true reference costs.

Under the best-queried terminal rule, one-step risk reduction equals expected improvement in the current best observed energy b:

\[
EI(q)=\mathbb E[(b-Y_q)_+].
\]

The implementation uses a first-observation offset and a training-fitted marginal Gaussian scale. This is a model-based heuristic, not a validated joint posterior. If the terminal action can accept an unqueried candidate using updated beliefs, the corresponding knowledge-gradient expression differs and needs a joint update model.

### Exact example: the uncertain candidate that cannot help

A is already known at energy 0. B is −2 with probability 1/4 and +2 otherwise. C is 4 or 16 with equal probabilities, independent of B. B has variance 3; C has variance 36. Current expected regret is 1/2.

Querying C cannot change the optimum decision and leaves risk 1/2. Querying B removes all regret. At cost 1/10, net values are −1/10 for C and +2/5 for B. The delivered rational-arithmetic enumerator executes all states exactly; these are synthetic values, not chemistry results.

### Exact example: one-step value misses an informative probe

A is known at 0. Among four targets, one is −10 and the other three are +3, with a uniform prior on which target is low. A high-energy probe P has value 10+h, where h reveals the low target's identity. Two calls remain.

Each direct target has immediate EI 2.5; P has EI zero. Greedy EI queries two targets and has expected final regret 5. Querying P and then the identified target has zero regret at the same two-call budget. The enumerator verifies this with exact arithmetic.

The one-step approximation is more credible when little budget remains, the residual model is useful, query outcomes reveal little about other candidates and costs are similar. It can fail under correlated blind spots, informative noncompetitive probes, complementary observations, queue constraints and candidate generation.

## 6. Calibration and uncertainty signals

The experiment compares a constant residual scale, cross-model disagreement, public-support distance and a combined scale. Scale coefficients are fitted by nonnegative least squares on squared **training-only anchored energy-gap residuals**, with a 1 meV/atom floor. The three model outputs correspond to different relaxed endpoints; their spread combines model error and possible basin/optimizer differences.

For each calibration chemical system, the score is the maximum absolute normalized anchored residual over every candidate in all its pools. With 24 groups and alpha 0.10, the finite-sample rank is ceil(25×0.9)=23. Too few groups produce an infinite interval rather than a fabricated finite bound.

The combined q90 is 3.0014046194. Whole-system coverage is:

| Scale | Calibration | Chemistry-disjoint test | Lithium shift |
|---|---:|---:|---:|
| Constant | 23/24 | 22/26 | 10/10 |
| Disagreement | 23/24 | 22/26 | 9/10 |
| Distance | 23/24 | 22/26 | 9/10 |
| Combined | 23/24 | 23/26 | 9/10 |

The combined test coverage is 88.46%, compared with nominal 90%; its candidate coverage is 97.27%. Candidate coverage cannot replace the whole-system measure. The exchangeability assumptions are uncertain under chemical-system and pretrained-support dependence, and no shifted-domain guarantee is claimed.

The conservative rule first queries the frozen cheap-ranked anchor. It stops only when the observed best is within tolerance of all simultaneous lower bounds; otherwise it requests the remaining pool. Failed references or inadequate budget prevent a certificate and cause abstention. A numerical trace correction clamps the reported nonnegative regret bound at zero while retaining its signed margin; the complete replay was repeated and all decisions were unchanged.

## 7. Executed new materials results

The following test table uses 30 pools across 26 chemical systems. Calls are historical reference-relaxation labels. All model-only arms were specified before evaluation.

| Policy | Success ≤20 meV/atom | Calls | Mean regret, meV/atom | Worst regret, meV/atom |
|---|---:|---:|---:|---:|
| Frozen MACE-MP-0 | 29/30 | 0 | 6.5826 | 187.807 |
| Frozen CHGNet | 29/30 | 0 | 7.0317 | 187.807 |
| Frozen M3GNet | 30/30 | 0 | 0.5688 | 9.345 |
| Three-model mean | 29/30 | 0 | 6.6424 | 187.807 |
| Fixed MACE top two | 29/30 | 60 | 6.2622 | 187.807 |
| Seeded random, two | 27/30 | 60 | 5.5334 | 77.531 |
| Descriptor diversity, two | 30/30 | 60 | 0.3234 | 9.345 |
| Maximum disagreement, two | 30/30 | 60 | 0.3234 | 9.345 |
| Decision-aware EI, two | 30/30 | 60 | 0.0030 | 0.059 |
| Fixed MACE top four | 30/30 | 91 | 0.0015 | See ledger |
| Gap-threshold fallback | 29/30 | 101 | 6.2602 | 187.807 |
| Constant-scale interval | 29/30 | 102 | 6.2602 | 187.807 |
| Combined interval fallback | 30/30 | 94 | 0.0041 | 0.122 |
| Full reference | 30/30 | 110 | 0 | 0 |

The primary equal-budget comparison has one rescue, zero threshold harms and 29 common successes. Mean regret changes by −6.2592 meV/atom, with a 5,000-draw paired chemical-system-bootstrap interval of [−20.1190, 0]. The success difference is +3.333 percentage points, with interval [0, +10.714]. Both intervals include no improvement. The entire continuous-regret difference comes from one SnO₂ pool.

At the declared tolerance, M3GNet-only matches the adaptive policy while using zero reference acquisitions. Its prespecified presence makes this an essential comparator. Selecting it now for a production workflow would itself be a new policy choice requiring fresh evaluation. The result does not prove it is universally best.

The tiny regret differences among successful arms are below the source convergence scale. They do not establish physical superiority. A claimed “34.1% saving” from 60 versus fixed-top-four's 91 labels would also be misleading without the zero-query comparator, model-inference overhead and a risk definition. These are points on an observed frontier, not a validated cost reduction.

Eight prespecified random seeds were executed at budget two. Test success ranges from 83.33% to 93.33%, averaging 88.33%. This describes algorithmic seed variation on the same pools, not eight independent datasets.

### Shift, tails and failures

Both fixed top two and EI reach 10/10 in lithium systems at 20 calls. The combined interval rule uses 15 calls and the support fallback 16. M3GNet-only also reaches 10/10 without calls. Eight of ten shifted pools contain only two candidates; this is a weak stress test of a two-query policy, not persuasive broad transfer evidence. In the test slice, 19 pools contain more than two candidates: EI succeeds on 19/19 versus top-two's 18/19.

Nine test pools and three shift pools have their two lowest labels within 2 meV/atom. All are retained; fine-grained ordering is treated cautiously.

Synthetic failed-label injection is separately labelled. It created 17 failed attempted acquisitions across 120 stress executions. In the test slice, the conservative arm abstains on five of 30 pools instead of issuing incomplete certificates; in the shift slice it abstains on two of ten. These are software fault tests, not observed historical DFT-failure rates.

Pairwise model-error correlations are substantial. On 80 nonanchor test contrasts, MACE–M3GNet error correlation is approximately 0.796; on the small shifted slice, CHGNet–M3GNet is approximately 0.963. These are dependent descriptive contrasts, not independent-sample significance tests. The shared-error risk is consistent with the motivation for model failure audits. [Systematic-softening study](https://www.nature.com/articles/s41524-024-01500-6).

## 8. The SnO₂ case that changes the decision

Fixed top two queries wbm-4-25075 then wbm-1-37760 and finishes 187.807 meV/atom above the recorded minimum. EI queries the same first input, then wbm-1-37762, finishing 0.030 meV/atom above that minimum. M3GNet-only chooses the same acceptable input without querying a reference.

The constant-width interval and simple energy-gap rule stop after the first candidate and are wrong. The combined interval rule escalates all five. This is a concrete high-confidence stopping failure; the nominal interval statement must remain conditional.

There is also a shared blind spot: all three models overestimate wbm-2-33797 by more than 300 meV/atom. Another input reaches a practically tied reference endpoint, allowing terminal success despite this error. Perfect pool success is not accurate physics everywhere.

The two lowest reference inputs have different initial prototypes and the same final DFT prototype label. Possible explanations include basin divergence, potential error, optimizer behaviour or historical convergence issues. The available energy tables cannot identify the mechanism. The attached physics case records all five geometries and model/reference values, plus four proposed initial inputs for a forensic DFT audit.

## 9. Cost accounting and break-even

The canonical run has 1,320 primary policy–pool executions, 280 additional random-seed executions and 120 synthetic-failure executions. These all reuse 40 evaluation pools; they are not 1,720 independent scientific replications. Primary replay charges total 2,594 historical labels across all arms and budgets, additional seed runs 560, and synthetic failures 269 attempts. Separate files account for the initial run and the verification rerun after the risk-bound semantics repair.

Measured runtime is local replay overhead, including process startup, scoring and uncertainty reporting. The first full run took 30.849 wall seconds and 108.71 child CPU seconds with four parallel workers. The canonical rerun took 32.259 wall seconds and 114.50 child CPU seconds; both runs are separately accounted. Nine logical CPUs and approximately 10 GB memory were visible. Live DFT jobs and live MLIP inference were both zero; reference runtime, queue time, GPU time and actual dollar savings are unknown. No paid compute was used.

For mean-regret scalarisation, compare policies using

\[
J = \overline L+\lambda_{\rm ref}\overline q+\eta_{\rm model}m.
\]

Against M3GNet-only, EI's test mean-regret reduction is about 0.5658 meV/atom for two extra labels per pool and two extra model passes. Ignoring model overhead, the algebraic break-even is **0.2829 meV/atom of regret-equivalent cost per extra label**. At the binary 20 meV tolerance, both succeed 30/30, so any positive extra reference cost favours the zero-query baseline on these observed decisions.

These quantities are not dollars. Mapping them to price requires the customer's value of a bad selection, reference job costs, model runtimes, queueing and operational overhead. The dashboard exposes hypothetical weights and keeps them separate from measurements.

## 10. Generation prototype and the remaining physical gate

The fixed-pool engine works, so a bounded geometry-generation prototype was executed: one seeded cell-strain/fractional-jitter proposal from each of five permitted SiO₂ initial structures, compared with five unchanged-input validations. Both arms have five geometry-validation attempts.

All ten geometries pass basic cell, composition and close-contact checks. The generated arm has zero exact duplicates and two screened near matches to the available SiO₂ inputs. Three proposals remain unmatched by this limited screen and await physical validation. They are not three discovered materials, and they may relax back to their parents.

No energies, forces, MLIP relaxations or DFT results were fabricated. Both arms used zero physical reference jobs. Proposal and geometry-validation CPU time are measured separately; equal geometry-validation counts do not establish equal physical cost or better materials. Ten complete candidate records include provenance, actual perturbations, coordinates, duplicate/rejection reasons and unsupported validation states.

Do not add generation to a commercial claim yet. The next physical test must compare generated and non-generated candidates at equal total relaxation/reference effort and report validated physical proxies. The existing geometry-only result cannot decide that question.

## 11. Usability, verification and open limits

The package contains a runnable CLI, pinned direct and transitive runtime dependencies, a synthetic fixture, raw source tables, source licences/metadata, frozen splits, calibration, isolated policies, traces, paired results, a result seal and a compact local dashboard. The historical engine and product interfaces remain unchanged.

Verification covers units/protocols, tie handling, repeated queries, failed labels, cost accounting, oracle visibility, heldout-label perturbation, group splitting, calibration-only fitting, invalid structures and deterministic generation. The original oracle's 18 tests also pass. Historical reproduction has its separate ten-test record. The full repository's unrelated chemistry/UI test suite was not rerun or represented as green.

The dashboard's embedded JavaScript and control logic were exercised and the exported scientific figure visually inspected. Full browser rendering could not be verified in this environment: the local browser binary was unavailable and the remote browser could not access the local preview. The HTML is self-contained and has no network dependencies.

A first preparation attempt failed on a missing formula in the public MP support metadata. The parser now rejects missing/non-string formulas explicitly, and unsupported support rows are skipped. The failure record is retained. An interval trace initially named a negative signed margin an upper regret bound; it now emits both the signed margin and a correctly nonnegative bound. Re-execution checks that scientific decisions did not change.

## 12. Three calls and a candidate paid evaluation

### Call one: lock the buyer, material class and endpoint

Select a computational materials lead who already owns repeated oxide screening and reference-job expenditure. Lock ordinary oxide fixed-pool selection at a declared tolerance and one reference protocol. Require the actual strongest frozen model and simple top-k workflow in the comparison. Do not offer discovery, conductivity or force reliability as deliverables.

A candidate paid scope is a two-week evaluation of 30–50 customer-owned compatible pools, with enough provenance to group them honestly. Deliver the import audit, baseline frontier, failure analysis, per-query traces and a recommendation. A hypothetical fixed fee of $7,500 is a quoting hypothesis for the call, not researched market pricing or an agreed contract. The first engagement should promise a decision audit, not compute savings.

### Call two: review the strongest baseline and its failures

Review M3GNet-only, MACE top two and the SnO₂ case. Determine whether the customer's actual endpoint values reference confirmation, a tighter physical tolerance or a different property enough to justify acquisitions. Inspect the two old molecular failures to distinguish missing candidate coverage from a poor acquisition rule. Freeze model selection using training data before opening any new test labels.

Stop or shrink the adaptive project if simple model selection/top-k matches the required risk at lower total cost, if protocols cannot be reconciled, or if the inference/integration overhead exceeds the work saved. Retain ingestion, provenance, replay and failure analysis even if acquisition is dropped.

### Call three: choose a forensic batch or a paid audit

Four actual SnO₂ initial POSCARs and review-required VASP templates are prepared. A proposed cap is four initial single points, four relaxations and four final statics, with no automatic retries. This is a forensic test of an examined case, not fresh policy validation. No jobs have been submitted and no spend is authorised. Exact PAW files, magnetic choices, k meshes, software versions, convergence and machine resources must be locked before use.

Alternatively, sell the evaluation of already available customer results first. For an initial pilot, operational success means reproducible ingestion, no protocol mixing, complete attempt/failure accounting, all decisions auditable and a baseline comparison that changes an actual workflow choice. An acquisition-promotion target can be at least 20% lower measured total cost at a predefined noninferiority margin on untouched groups, but 30–50 pools may only screen feasibility; it cannot reliably certify a tight population-risk bound.

Stop at the agreed data/compute cap, report negative results, and do not retune against the test set. A failed data/protocol audit is a useful result if it prevents a false performance claim.

**Hasan's next 45 minutes:** freeze the import contract and a sample customer manifest; run the delivered fixture and sealed-trace verifier; write the one-page paid-audit scope with the zero-query baseline mandatory.

**Ahmad's next 45 minutes:** inspect the four SnO₂ inputs, decide the charge/spin and convergence intent, and resolve whether model error, different basins or incomplete relaxation is the first falsifiable explanation. Deliver a reviewed protocol or a specific blocking discrepancy.

The immediate decision is to keep B narrow: a transparent evaluation and recommendation layer that can tell a customer when the simplest workflow is already sufficient.
