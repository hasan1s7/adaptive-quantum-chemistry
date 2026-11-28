# Erkidu decision mathematics, statistical design, and company choice

**Status:** design analysis plus exactly executed synthetic counterexamples. Commercial statements are hypotheses for buyer interviews, not market validation. No external actions were taken. The executable `decision_examples.py` uses rational arithmetic and has been run successfully.

## 1. Company formulations: choose B as a testable operating hypothesis

| Formulation | Proposed buyer | Incumbent workflow to investigate | Unit of value | Data dependency | Moat if demonstrated | Strongest failure mode |
|---|---|---|---|---|---|---|
| A: better ML interatomic potential | Computational materials team with enough recurring atomistic work to justify a model change | Existing pretrained or internal potential, local fine-tuning, and reference calculations | Lower reference error or larger valid operating domain at a stated inference/training cost | Broad, compatible energy/force/stress labels, coverage of the customer's compositions and states, sufficient compute | Proprietary high-value reference coverage, sustained architecture/training advantage, demonstrably better transfer | Strong public models improve rapidly; an incremental accuracy result may not justify migration or maintain a moat. This project has not demonstrated an MLIP advantage. |
| B: reliability and acquisition across MLIPs and reference workflows | Lead scientist or simulation-platform owner responsible for choosing which predicted candidates warrant expensive calculations | Domain expert checks, fixed top-k reranking, hand-tuned gap or uncertainty thresholds, exception queues | Fewer expensive reference workflows at equal decision quality, or lower decision risk at an equal budget, with auditable records | Customer-specific decisions and compatible labels, visibility into model/dataset versions and reference settings, out-of-domain and failure cases | An expanding record of which observable evidence improves decisions in particular workflows; audited integration and calibrated failure handling; evidence reusable across model replacements | Simple top-k/gap rules may perform as well; model disagreements may share blind spots; integration and acquiring unbiased reference labels may cost more than the savings. An attribution/trace layer alone may be useful but not defensible enough. |
| C: end-to-end discovery for one material class | One materials R&D program with a narrowly specified property and validation route | Human selection, candidate proposal, relaxation, property screening, synthesis/testing | Independently validated improvement in the specified physical property or faster elimination of unsuitable candidates | More than energies: credible application-specific properties, valid structures, relevant environments, and experimental validation access | High-value proprietary data and a reproducible generate-test-learn process for the selected class | Energy stability is insufficient for most applications; synthesis, kinetics, transport, interfaces, degradation, and product integration can dominate. A successful energy proxy need not produce a valuable material. |

B is the best *next experiment* because its benefit and failure can be measured before discovery succeeds, and because it can retain working model components as they improve. That is not yet evidence of willingness to pay or an adaptive advantage. Sell a bounded evaluation only after agreeing on the buyer's real decision, baseline, labels, and costs. Do not sell a generic reliability guarantee.

**Initial research-grade decision:** given a frozen, compatible-composition pool, which reference-relaxation labels should be acquired so that the lowest-energy *queried* structure has low regret at a specified acquisition budget? The immediate output is a ranked recommendation, the query/escalation decision, an uncertainty diagnostic, and the evidence available at that time. No claim of newly discovered materials is required.

For the intended WBM replay, a published relaxed-energy label corresponds to a completed reference **relaxation workflow**, not a single-point DFT call. One label may represent many electronic and ionic steps. Use “reference-label acquisitions” for replay budget and retain the reference job/step cost as unknown unless actual logs establish it.

## 2. The mathematical object

For independent evaluation group g (for example a disjoint chemical system) and compatible-composition pool p within g, let I_p be its frozen candidate IDs. Each candidate contains pre-reference geometry/metadata, frozen MLIP output, permitted descriptors, protocol ID and units. Y=(Y_i) is the vector of unknown compatible reference energies. Model outputs and descriptors x_i are observable at time zero. Test references remain inside the oracle.

The state at t is D_t = (pool/version, available candidate IDs and masks, frozen model/version, descriptors and predictions, calibration artifact/version, queried IDs, successful returned values, failures, remaining budget and elapsed/measured cost). State must not include hidden reference extrema, query-independent reference rankings, excluded-job labels, or post-hoc metadata derived from test references.

The oracle returns a success with an energy and provenance, or a failed/unsupported response with its cost record. Availability of a reference energy and availability of compatible forces are separate capabilities. A force action must fail explicitly if only relaxed energy labels exist. A same-composition relaxed-energy ranking cannot be described as a matched-geometry energy or force benchmark.

Actions are accept the frozen surrogate recommendation; acquire an allowed reference energy/relaxation label; acquire forces if the oracle really supports them; escalate the entire remaining pool or trajectory; or abstain with a reason. The replay implements the supported subset and reports unsupported actions explicitly.

### Terminal decision and objective must stay consistent

For paid acquisition arms, a particularly auditable endpoint is

- Q_t: successfully queried candidates.
- d_t = argmin_{i in Q_t} Y_i, deterministic stable-ID ties.
- L(d_t,Y) = Y_{d_t} − min_{i in I_p} Y_i, in the declared unit.

The zero-query MLIP arm chooses argmin frozen predicted energy and is scored by the same regret definition, but has no reference certificate. Distinguish it from paid arms in the results. The full-reference arm queries all eligible candidates and is an oracle comparison, not an achievable zero-cost baseline.

For comparing a tolerance endpoint, define miss = 1[L > epsilon] with epsilon fixed before reading evaluation labels. Report continuous regret and the miss rate together: a policy can reduce mean regret while increasing the number of threshold misses.

A stochastic decision model conditions on D_t. Bayes terminal risk is R(D_t)=min_d E[L(d,Y)|D_t], with d constrained by the terminal-action definition. For query q,

VOI(q|D_t) = R(D_t) − E_{Z_q|D_t}[R(D_t ∪ Z_q)] − lambda*C(q|D_t).

C is the *incremental actual cost* if known; it is not automatically one unit per label, wall time, or dollars. Cost must include failed attempts if they consumed resources. A replay can evaluate label-count and scenario-weighted costs, with measured inference time kept separate.

### Expected improvement and knowledge gradient are different endpoints

If the terminal selection must be the best queried structure, b=min observed reference energies, a new noiseless query can only improve that terminal energy. The one-step reduction in expected simple regret is exactly

EI(q|D_t)=E[(b−Y_q)_+ | D_t].

The unknown full-pool minimum cancels between the two terminal risks. With a discrete training-only residual law e_j and calibrated prediction mu_q, a transparent plug-in approximation is mean_j max(0,b−mu_q−e_j). It is model-based, not an empirically certified value of information. Any conditioning or residual rescaling must use only currently observed data and training/calibration parameters.

If terminal selection may include an unqueried candidate using posterior means, one-step Bayes regret reduction is instead

KG(q|D_t) = min_i mu_i(D_t) − E_z[min_i mu_i(D_t,z)],

because E[min_i Y_i | D_t] also cancels. This requires a joint posterior/update model. Marginal EI is generally not exact for this second endpoint. Correlated errors matter because querying q can change beliefs about other structures, including ones with low marginal uncertainty.

A greedy EI rule is reasonable when the next step nearly finishes the budget, the current posterior is useful, reference outcomes provide little information about other candidates, jobs have similar latency/cost, and no future action is unlocked. It fails with complementary information, shared model errors, queue/batch constraints, delayed reference returns, strong multi-step exploration benefits, or future candidate generation.

### Absolute energy and normalization leakage

Never expose a queried energy after subtracting the hidden reference minimum. A zero would reveal that it is globally optimal. The oracle may return absolute reference energies or an offset fixed without hidden reference labels. Evaluation may subtract the full-pool reference minimum after the policy finishes. Pairwise gaps are safe once both reference values have been revealed. Comparing energies across different compositions requires a separate formation-energy convention and chemical reservoirs; same-composition ranking does not.

## 3. Exact finite examples, executed

### 3.1 Largest uncertainty wastes the query

The incumbent A has energy 0. B has energy −2 with probability 1/4 and +2 with probability 3/4. C has energy 4 or 16, each with probability 1/2, independent of B. These are synthetic exact values.

| Candidate | Mean | Variance | Can beat A? | Risk after querying |
|---|---:|---:|---|---:|
| A, already known | 0 | 0 | Incumbent | — |
| B | 1 | 3 | Yes | 0 |
| C | 10 | 36 | No | 1/2 |

Before querying, choose A. Expected regret is (1/4)*2=1/2. C has the largest uncertainty but cannot change the decision in any state. Querying B reveals whether to choose B or A and removes all regret. At cost 1/10, B's net value is 2/5; C's net value is −1/10. `decision_examples.py` enumerates all four joint states with rational arithmetic and verifies these quantities.

### 3.2 Myopic expected improvement fails under the best-queried endpoint

This example matches the implemented replay endpoint. The incumbent A is already reference-known at0; two more calls remain. Four equally likely states contain targets T0,T1,T2,T3, exactly one with energy−10 and the others+3. A diagnostic probe P has energy10+h, where h is the identity of the low-energy target. The exact correlation is assumed known; all calls have equal cost1/10.

A direct target query has expected immediate improvement(1/4)*10=2.5. Querying P cannot beat A and has immediate improvement0. Greedy EI therefore chooses a target. If that target fails, one further target query finds the optimum with conditional probability1/3. Overall, two target queries succeed with probability1/2, so expected final regret is5. Querying P and then the target its response identifies always yields the best reference-confirmed target, so regret is0, at the same two calls. With exactly two calls, total losses including cost are5.2 and0.2. If greedy stops after a first-call success, it uses1.75 calls on average and its loss is5.175, still worse than0.2 for the two-call lookahead. The rational enumerator verifies both paths. Shared errors and informative-but-noncompetitive structures can therefore create value that one-step EI misses even when the terminal selection is strictly limited to queried structures.

### 3.3 A same-cost counterexample with complementary probes

Let hidden bits (U,V) be uniformly distributed over {00,01,10,11}. A has energy0. Four targets T00,T01,T10,T11 have energy−1 when their name matches the bits, and+3 otherwise. Probe P has energy10+U; probe Q has energy12+V. All reference queries cost1/10. The exact joint prior is known. The terminal may accept an unqueried candidate whose energy is determined by observations; this is the unqueried-acceptance endpoint, deliberately distinguished from best-queried replay.

| Hidden state | T00 | T01 | T10 | T11 | P | Q |
|---|---:|---:|---:|---:|---:|---:|
| 00 | −1 | 3 | 3 | 3 | 10 | 12 |
| 01 | 3 | −1 | 3 | 3 | 10 | 13 |
| 10 | 3 | 3 | −1 | 3 | 11 | 12 |
| 11 | 3 | 3 | 3 | −1 | 11 | 13 |

Initially each target has mean2, so choose A; true minimum is always−1 and Bayes regret is1. Either probe alone leaves two possible targets with posterior mean1, so it provides no immediate risk reduction. Querying one target has a 1/4 probability of finding the optimum and reduces expected risk to3/4. Myopic choice therefore prefers a target.

With exactly two calls, a greedy target-first policy can find or infer the optimum with probability1/2, leaving expected regret1/2 and total loss7/10 including cost. Querying both probes identifies the bits and optimum with certainty, leaving regret0 and total loss1/5 at the same two calls. The executed enumerator verifies both paths. The example proves that marginal uncertainty and one-step value can both miss complementary information; it does not claim that actual MLIP errors follow these bits.

## 4. Split, calibration, and failure design

### Grouping and exposure

Freeze group IDs, pool IDs, candidate IDs, duplicate/near-duplicate components, and train/calibration/test membership before fitting residual models or thresholds. Build a graph connecting candidates through the strongest available shared provenance: originating trajectory, exact geometry/structure hash, duplicate material ID, near-identical structures, and the chosen molecular/composition/prototype grouping. Connected components cannot straddle splits. Report limitations if provenance or near-duplicate detection is incomplete.

For WBM, exact composition defines a decision pool; chemical system may define an independent unit. A formula such as Li2O and Li4O2 must map to the same reduced stoichiometry, with a clearly documented per-atom energy convention. A chemical-system split is a strong chemistry-disjoint test, not necessarily an IID split. A second milder held-out-group slice can be reported as in-domain only after its support definition is fixed.

Pretrained exposure is separate from split leakage. A test set assembled now is not independent of a model that trained on those labels or related parent structures. Record declared training corpus and revision, direct ID/geometry intersections when available, and unresolved overlaps. “No direct ID overlap detected” does not mean “no related-data exposure.” If earlier humans inspected all pools, call all subsequent subdivisions development evidence.

### Three signals, no equivalence claim

1. Ensemble disagreement: standard deviation or robust spread across fixed model outputs. Shared training, architecture and data can create shared confident errors. An ensemble is a diagnostic, not a reference distribution by definition.
2. Distance to training support: nearest-neighbor distance in a frozen, training-fitted descriptor representation, with normalization fitted on training only. Missing descriptor coverage is unsupported. A composition-only descriptor is not structural novelty.
3. Predictive intervals: separately calibrated residual scores, with their coverage unit and assumptions stated. Do not call ensemble spread an interval without calibration.

If available models predict independently relaxed geometries, their disagreement combines model and geometry differences. Name it “workflow disagreement” and do not present it as same-geometry epistemic uncertainty.

### Group-level calibration

For each calibration group g compute one score S_g=max over all its eligible pool/candidate errors |Y_i−mu_i|/s_i, where s_i is fixed from training and bounded away from zero. With m calibration groups, use k=ceil((m+1)*(1−alpha)); q is the kth ordered score when k≤m, otherwise q=+infinity. This explicit infinity is required for honest finite-sample calibration. A family simultaneous interval mu_i±q*s_i controls the event that every eligible candidate in a fresh exchangeable group is covered under the usual split-conformal assumptions, not the fraction of individually covered conformers.

For ranking, gauge-invariant pairwise-gap scores can be more relevant: max over candidates or pairs of the error in predicted relative reference energies. The anchor must be fixed from pre-reference information. A group-max over all candidate comparisons supports a decision certificate on the joint coverage event. Absolute energies are acceptable where the physical protocol and normalization match.

Freeze the model and scale before calibration. If acquisition retrains or changes predictions, the original interval guarantee does not automatically persist. Frozen simultaneous intervals can safely be inspected by adaptive selection because their event already covers all candidates. Online shrinkage or conditional coverage claims require separate validation.

Report: number of calibration groups; quantile index and value; whole-group empirical coverage; candidate coverage as a secondary diagnostic; mean/worst interval width; each domain slice; and the rate of intervals infinite or unavailable. Report binomial uncertainty over genuinely independent groups. Under shift, report observed coverage without extrapolating the exchangeability guarantee.

### Selective policy and conservative fallback

A conservative energy certificate for chosen i is U_i−min_j L_j≤epsilon, where L/U are simultaneous bounds and a successful queried noiseless label collapses its bound to its exact value. If supported and no candidate is excluded, this bounds selection regret by epsilon on the joint coverage event. A threshold should be frozen on training/calibration groups, not selected for a favorable test result.

Fallback triggers include unsupported chemistry/protocol, missing required predictions or geometry, nonfinite energies, out-of-support distance, unsafe width, missing labels, reference failures, or exhaustion of the reference budget before the certificate holds. A missing-label pool cannot silently drop the missing competitor and claim the minimum over the original pool. Mark it incomplete/abstain, and separately provide any explicitly narrowed eligible-pool analysis.

Report full-pool escalation and abstention frequencies and acquisition costs. Zero accepted mistakes is meaningless if the policy abstains on almost everything. Show the acceptance-versus-risk curve and total completed/failed/missing denominators. If force or relaxation outcomes are unavailable, those decisions remain unsupported.

### Evaluation and paired uncertainty

Use one pinned evaluation roster and matched deterministic budget allocation for every stochastic/acquisition arm. Compare at exactly the same successful/attempted-query convention, reporting both counts. A failed job consumes an attempted-job budget if it consumed compute; a cached repeat should neither spend again nor create another independent observation. If equal budget is impossible because pools are too small or jobs fail, state the discrepancy.

Always include frozen MLIP-only, full oracle, random acquisition, fixed top-k/gap/confidence, diversity, and the decision-aware arm. Random acquisition needs seeded repeated draws; do not select its best seed. An average over random seeds has two uncertainties: seed noise and group-sampling uncertainty.

For each pair, report rescue (challenger succeeds / baseline fails), harm (reverse), common success and common miss. Compute regret differences per pool then bootstrap whole independent groups, keeping all member pools and both paired policy outcomes together. State whether the estimand weights pools equally or groups equally; large chemical systems can dominate a pool-weighted estimate. Use a fixed seed and percentile interval with an explicit number of resamples. Bootstrap intervals with few groups or no observed discordance are fragile, not proof of equivalence. Report worst-case and tail-regret cases with trace records.

High-confidence failures require joint inspection of disagreement, distance, interval/certificate, predicted and true gaps, protocol compatibility, duplicate lineage, and the actual available observations. Do not retune to fix a test case and retain its old test label.

## 5. Cost frontier and break-even

Let policy A have mean terminal loss r_A, q_A attempted reference-label acquisitions, and measured overhead h_A; let B have r_B,q_B,h_B. In a scalarized scenario, total score is r + lambda*(q*c_ref+h), where c_ref has the same cost units as h. If q_A<q_B and r_A>r_B, A is worthwhile only when

c_ref > [(r_A−r_B)/lambda + h_A−h_B] / (q_B−q_A).

If loss is a miss indicator valued at v per miss, use total excess misses M_A−M_B and monetary overhead H_A−H_B: c_ref > [v*(M_A−M_B)+H_A−H_B]/(Q_B−Q_A). This is a scenario calculation, not a measured willingness-to-pay figure. If one policy has both higher risk and higher cost, it is dominated for every positive valuation.

A public relaxed-label replay cannot measure original DFT runtime, queue time, failed SCF attempts, number of ionic steps, hardware, or cloud dollars unless those logs accompany the data. It can measure local loading, descriptor/inference/policy overhead, elapsed wall time and CPU time. Keep these fields distinct. Wall time under parallelism depends on a schedule/max or queue simulation, not just a sum of per-job times. Queue and batch assumptions should be explicit scenario inputs.

The 669-versus956 historical acquisition comparison, if verified as 5 additional misses with287 fewer labels, has a purely symbolic break-even of c_ref > 5v/287 plus any overhead adjustment. This is not proof of acceptable risk. A fixed95% success gate can reject the policy even if a monetized objective would accept it. Do not rerun a verified historical result just to reproduce a number already available.

## 6. Three calls and immediate tasks

**Call1 — scope.** Lock one buyer hypothesis, one material class/composition roster, one energy convention/reference protocol, one terminal endpoint and one priced cost unit. Candidate pilot: retrospective audit of a customer's fixed, already calculated compatible-composition screening pools; use a frozen pretrained model and a frozen acquisition policy. Obtain buyer agreement on whether selection must be reference-confirmed and how much regret is tolerable. No generation is needed to deliver this evaluation.

**Call2 — evidence.** Review the strongest simple baseline, paired rescue/harm counts, worst high-confidence misses, uncertain/shifted families, and fallback cost. Ahmad checks the two largest scientifically interpretable failures. Hasan checks the split graph, calibration unit, exposure ledger, and policy traces. If adaptive selection loses, retain the oracle abstraction, protocol checks, cost ledger, and reporting; change or drop the acquisition heuristic. Do not enlarge the experiment solely to search for a positive subset.

**Call3 — investment.** Choose a small fresh reference batch only if the decision and reference protocol are locked and expected information could change the pilot decision. Otherwise offer a paid evaluation only with an explicit retrospective scope and no adaptive-savings promise. Fresh DFT spend needs approval. Generation remains deferred until a fixed-pool gate works; future bounded generation must include generation/relaxation failures, duplicate accounting and independent labels at matched total cost.

Candidate pilot success criteria must be agreed before labels: no protocol/unit or visibility failures; complete traces; exact roster reconciliation; a noninferiority margin in regret/miss risk justified by the buyer; measured reference-cost reduction after overhead; and a tolerable fallback rate. Stop criteria: unresolved training/test exposure that defeats the claim, incompatible protocols, insufficient independent groups, better performance of a simple baseline, savings swallowed by overhead, or a buyer whose actual objective is not the energy proxy.

**Ahmad,45 minutes:** review two real development failures using geometry/protocol/gap evidence; classify each as model error, relaxation-path mismatch, reference inconsistency, near tie, or unresolved. Record what fresh calculation would distinguish the explanations.

**Hasan,45 minutes:** freeze the decision roster, group split, loss threshold, budget and strongest baseline in a manifest; inspect one trace for hidden-label leakage and calculate the actual risk-cost tradeoff from the paired table. Do not spend this block adding another model.
