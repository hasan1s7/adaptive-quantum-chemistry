# Hasan’s statistical review

**Decision:** keep the evidence engine; do not promote adaptive acquisition as a demonstrated saving. EI rescues one MACE top-two miss, but the prespecified frozen M3GNet arm already meets the declared tolerance without a reference query. This is an executed public-label development replay, not independent prospective validation.

## 1. What was estimated

The primary estimand is the **pool-weighted mean selection regret over the frozen evaluation roster**, with threshold success reported separately. For composition pool \(I\), compatible reference energies \(Y_i\), and a paid policy’s successful queried set \(Q\),

\[
 d=\arg\min_{i\in Q}(Y_i,\mathrm{ID}_i),\qquad
 L=Y_d-\min_{i\in I}Y_i.
\]

Units are eV/atom. Stable IDs resolve ties. Success requires an accepted selection with \(L\le0.020\) eV/atom. Frozen MLIP-only arms may accept an unqueried prediction; paid arms must select a successful reference observation. Their different confirmation status is visible, but the declared loss does not assign a separate benefit to confirmation. If a buyer requires confirmation, change that endpoint **before** evaluating a new cohort.

Thirty non-lithium test pools belong to 26 chemical systems; ten lithium-shift pools belong to ten systems. The 1,720 executions are repeated policy/seed/fault evaluations of these 40 pools—not 1,720 independent scientific observations. Reference count is the number of historical whole-relaxation labels attempted, not the number of SCF cycles, measured DFT seconds, or dollars. [Protocol and cohort](../../results/decision_engine/oxide_prepared/preregistered_protocol.json); [execution accounting](../../results/decision_engine/oxide_run/execution_accounting.json).

## 2. The decisive paired result

| Test arm | Success within 20 meV/atom | Reference attempts | Mean regret, meV/atom |
|---|---:|---:|---:|
| Frozen M3GNet | 30/30 | 0 | 0.5687667 |
| MACE fixed top-two | 29/30 | 60 | 6.2622000 |
| Decision-aware EI | 30/30 | 60 | 0.0029667 |

EI versus fixed top-two has **one rescue, zero harms, 29 common successes and zero common misses**. The mean-regret difference is −6.2592333 meV/atom. Its paired 95% chemical-system bootstrap interval is **[−20.1189643, 0] meV/atom**; the success-rate difference is +3.333 percentage points with interval **[0, 10.7143] percentage points**. The interval includes no advantage. On the ten lithium pools, both paid rules succeed 10/10 at 20 attempts, with zero rescues or harms. [Paired results](../../results/decision_engine/oxide_run/paired_results.json); [aggregates](../../results/decision_engine/oxide_run/aggregates.json).

Bootstrap draws resample whole observed chemical systems and retain all member pools, preserving the pairing. The ratio estimator weights pools equally, so systems with more pools have more weight. Intervals condition on the frozen fit, split, policies and empirical groups. Shared source/prototype lineage can leave dependence between groups. A degenerate [0,0] empirical interval on the small lithium slice does not prove zero population risk.

M3GNet’s observed maximum regret is 9.345 meV/atom, below the 20 meV threshold. The extra EI acquisitions produce no additional threshold successes. Its mean-regret difference from M3GNet is below the declared 2 meV/atom near-tie scale; numerical differences alone do not establish a physical or commercial benefit. M3GNet was a prespecified comparator, but selecting it for future deployment after viewing this table would still require model-selection discipline: select on training data and evaluate the frozen choice on untouched groups.

## 3. Calibration: unit, assumptions and observed failure

The residual scale was fitted on 35 training pools in 33 chemical systems. Calibration uses 24 separate systems. Each system contributes **one maximum absolute normalized anchored residual** over all its candidates and pools. The anchor is fixed from cheap predictions; the policy never sees a reference minimum.

At nominal 90% group coverage, the finite-sample rank is \(\lceil(24+1)0.9\rceil=23\). The combined-scale quantile is 3.0014046194. Insufficient calibration groups produce an infinite interval rather than an invented finite bound.

| Combined interval | Covered whole systems | Observed coverage |
|---|---:|---:|
| Calibration | 23/24 | 95.83% |
| Chemistry-disjoint test | 23/26 | 88.46% |
| Lithium shift | 9/10 | 90.00% |

These are whole-system counts, not individual candidate coverage. The split-conformal interpretation needs exchangeable group scores conditional on the fixed training fit. Related pretrained data, shared model errors, WBM parent lineage and deliberate chemistry shift can violate that assumption. No blanket shifted-family guarantee follows. No online model refitting is covered by these frozen intervals. [Coverage](../../results/decision_engine/oxide_run/calibration_coverage.json); [fitted calibration](../../results/decision_engine/oxide_fit/calibration.json).

The **constant-scale interval wrongly certifies SnO₂**, leaving 187.807 meV/atom regret. Its arithmetic is correct for its bounds; the interval misses the relevant reference outcome. This is a substantive calibration failure, preserved in the audit rather than “fixed” by retuning the test case. The repaired trace semantics now distinguish a signed unqueried-energy margin from the nonnegative regret bound \(\max(0,\mathrm{margin})\).

A support-distance filter does not rescue reliability here. The lowest-distance quarter retains eight test pools, **including the SnO₂ miss**, and has a 12.5% selective failure rate versus 3.33% over all 30 pools. SnO₂ is third closest by the recorded maximum support distance (0.0121739130). This descriptor can regard a wrong prediction as familiar. These are retrospective diagnostic slices, not tuned acceptance thresholds or evidence that distance is uniformly harmful. [Selective-risk record](../../results/decision_engine/oxide_run/selective_risk.json).

## 4. Exact cost break-even, without invented prices

For the finite test cohort, define

\[
J=\overline L+\lambda\overline q+\eta m,
\]

where \(\lambda\) is the regret-equivalent cost per historical reference acquisition and \(\eta\) is the regret-equivalent cost per model pass over a pool. Future inference passes are assumed to be one for fixed MACE/M3GNet and three for the combined EI signal; actual MLIP inference and reference runtime were not measured here.

Using exact decimal reference labels, the total regrets across the 30 pools are 0.187866 eV/atom for fixed top-two, 0.000089 for EI, and 0.017063 for M3GNet.

- **EI versus fixed top-two:** reference counts cancel. EI is favored by this mean-regret objective only when
  \[
  2\eta < \frac{0.187866-0.000089}{30},\quad
  \eta < \frac{187777}{60000000}\approx0.0031296167\ \mathrm{eV/atom}.
  \]
- **EI versus M3GNet:** two extra labels and two extra passes per pool require
  \[
  2\lambda+2\eta < \frac{0.017063-0.000089}{30}=0.0005658,
  \quad \lambda+\eta < \frac{2829}{10000000}=0.0002829\ \mathrm{eV/atom}.
  \]
  At zero model overhead, the label threshold is 0.2829 meV/atom equivalent. Under the **binary 20 meV success loss**, both arms have zero observed misses, so any positive additional cost favors M3GNet on this roster.

These are point-estimate algebraic thresholds, not dollars, savings, willingness to pay, or robust population-optimal policies. Integration, descriptor calculation, reference failure, queueing and batch costs must enter a customer calculation. [Exact arithmetic audit](../../results/decision_engine/full_trace_audit.json); [scenario bundle](../../results/decision_engine/oxide_run/cost_sensitivity.json).

## 5. Full trace audit and the pilot import limit

The saved-record audit inspected **all 1,720 traces and 3,423 charged attempts**: 1,320 primary runs, 280 additional seeded-random runs and 120 synthetic-fault runs. It reconciled 3,406 successful responses and 17 injected failures. Every available-observation prefix, anchor, remaining budget, absolute reference response, terminal choice, cost ledger and evaluator regret/success score matched. CSVs, paired results and bootstrap intervals, calibration coverage, source hashes, seals, dashboard data and cost scenarios also matched. All 156 interval-check events had nonnegative risk bounds; 31 negative signed margins correctly became zero bounds. No policy, oracle, fit or physical calculation was rerun. [Reproducible auditor](../../scripts/audit_decision_traces.py).

Real replay scoring **requires complete evaluator ground truth**. The injected oracle failures retain truth for scoring; they cannot estimate loss when the reference truth itself is missing. The current paired aggregation is not an end-to-end adapter for incomplete evaluator labels. A pilot importer must reject that evaluation as unsupported or explicitly redesign the estimand and denominators before producing paired results. Do not silently drop unknown competitors.

Existing tests cover unit/protocol rejection, missing/nonfinite reference charges, repeat caching, unsupported forces, split leakage, held-out-label perturbation and missing training labels. Bool/string malformed references are rejected in the implementation but lack a dedicated named test. The canonical traces contain no repeat queries, so cache behavior is supported by synthetic unit tests, not by these logs. Plausible numbers carrying a false unit/protocol tag still require source and physics review.

The audit supports implementation consistency. It does not prove the benchmark was externally preregistered, unseen by humans or pretrained models, or prospectively representative. No post-test improvement should inherit this test set’s status.

## 6. Three calls and immediate founder work

1. **Lock the purchase decision.** Choose an oxide-screening buyer, compatible reference protocol, acceptance versus confirmation requirement, tolerance, actual cost unit and fixed pilot roster. Make the strongest zero-query model a mandatory comparator.
2. **Inspect the strongest baseline and its failures.** Review the one SnO₂ rescue, the failed constant-scale certificate, and the simple model/top-k alternatives. Freeze the next model/policy choice without using new test labels. Shrink acquisition work if the simplest rule already meets the customer’s endpoint.
3. **Choose a bounded next investment.** Either offer a retrospective paid audit of already available customer data or review a capped forensic reference batch. The examined SnO₂ case is suitable for diagnosing a failure, not for fresh policy validation. A 30–50-pool pilot can assess feasibility; it cannot by itself certify a tight population noninferiority bound. No compute spend is authorized by this review.

**Hasan—45 minutes:** freeze a sample customer manifest with the loss, independent grouping, strongest baseline, data-completeness gate and actual cost columns; run the saved-trace auditor; write the one-page evaluation scope with an explicit negative-result outcome.

**Ahmad—45 minutes:** examine the SnO₂ geometries and reference protocol; identify the first calculation that distinguishes model error, different relaxation basins and incomplete convergence, then specify a bounded protocol or a concrete blocking discrepancy.
