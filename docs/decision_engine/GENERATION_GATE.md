# Should Erkidu add generation?

**Current evidence class: executed geometry-only prototype; physical
validation is blocked.** After the fixed-pool replay executed, a bounded
proposal and geometry-validation loop ran on five published initial SiO₂
structures. It evaluated no energy, force, MLIP relaxation or DFT job.
Published fixed-pool relaxed energies apply to their original records and
protocols; they cannot label a newly perturbed crystal. A structure's nearest
published neighbor is not a reference oracle for the structure.

## Executed bounded prototype

```bash
python tools/bounded_oxide_generation.py --out runs/geometry-prototype
python -m unittest discover -s tests -p test_bounded_oxide_generation.py -v
```

With seed **20261127**, each of the five available initial SiO₂ structures
produced one proposal using a symmetric cell strain with each entry bounded
by 0.002 and per-site fractional-coordinate jitter bounded by 0.002. The
code caps requested proposals at twelve and uses at most one per available
parent; five were available here. Parent identity, source and geometry
hashes, actual perturbation arrays and new cell/coordinates are recorded.
No reference label was used to select parents or construct proposals.

The comparison validates the same five unmodified inputs. Both arms have
five geometry-validation attempts; generation overhead is measured
separately. Validation checks finite arrays, positive cell volume, unchanged
stoichiometry, periodic boundaries, and a loose 0.9 Å minimum periodic
distance screen. That contact threshold is an engineering reject rule, not
a guarantee of a chemically sensible or stable structure.

| Observed geometry result | Unchanged-input baseline | Bounded proposals |
|---|---:|---:|
| Geometry-validation attempts | 5 | 5 |
| Geometrically valid | 5 | 5 |
| Exact matches to available input set | 5 | 0 |
| Screened near matches to available input set | 0 | 2 |
| Duplicate/near-duplicate rate | 100% | 40% |
| Remaining proposals awaiting physical validation | 0 | 3 |
| MLIP relaxations / DFT jobs | 0 / 0 | 0 / 0 |

The baseline's exact matches are expected because it deliberately reuses
existing inputs. The three unmatched proposals are **not demonstrated new
basins or materials**. They could relax to their parents or fail under a
physical calculation. Novel-material rate and physical improvement are
undefined. The novelty screen compares only five available same-composition
initial inputs, using the same documented pair-distance/volume screen as
the geometry audit. It does not search all public structures or prove
crystallographic inequivalence.

Total measured local runtime was **0.132870 wall seconds / 0.132856 CPU
seconds**, including loading and output. Bounded proposal computation used
0.000302 CPU seconds; baseline input copying used 0.000225 CPU seconds.
Geometry validation used 0.007537 CPU seconds for proposals and 0.002578 for
baseline inputs. These very small single-run timings are bookkeeping
measurements; they do not establish production throughput or a physical-cost
advantage. No queue time, quantum runtime or dollars were measured.

All ten candidate records include geometry, hashes, validity outcome,
duplicate matches, rejection reasons and explicit
`mlip_relaxation="unsupported_no_runtime_weights_loaded"` and
`dft_validation="not_run"` states. The two generated near duplicates are
rejected from the novel-candidate queue; the other three await physical
validation. Two tests passed: invalid cells, composition and collisions are
rejected; seeded proposals repeat and the near screen handles translation.
No artificial failure was inserted into the observed candidate batch.

Results are in `results/decision_engine/generation/`. The previous proposed
status is preserved under its `history/` directory, and the current status
and candidate-record exports now describe this executed prototype.

## Decision now

Retain acquisition and reliability as the first product scope. A functioning
fixed-pool replay establishes that we can audit decisions; it does not by
itself establish that an acquisition policy saves reference work, that a
generator finds useful new structures, or that either advantage transfers to
a customer's workflow.

Advance physically scored generation only after the fixed-pool comparison identifies a buyer
endpoint and a frozen policy that is at least competitive with its strongest
simple baseline at the same reference budget, with an acceptable severe-tail
risk. If the adaptive policy loses, retain the evaluation harness and spend
the next iteration investigating that loss. Generating more candidates
before reliable selection can increase the cost of the same unresolved
decision.

The machine-readable `generation_status.json` distinguishes the executed
geometry proposal loop from the unexecuted physical experiment below. The
working prototype establishes reproducible candidate bookkeeping and reject
handling. It does not yet answer whether generation earns its computational
cost for the buyer's physical decision.

## Small bounded follow-up, if the gate is passed

**Proposed class and proxy:** ordinary-valence periodic oxides, beginning
with a single compatible composition such as SiO₂. The endpoint is
reference relaxed-energy regret within the union of a bounded starting and
generated pool. A lower electronic energy is not evidence of conductivity,
cycle lifetime, synthesis, or experimental stability.

1. Obtain a permissioned fresh batch of eight initial structures with one
   exact composition, protocol, geometry identity and declared charge/spin
   treatment. Pin a model version and weights whose training overlap is
   auditable. Freeze all inputs and a seed before requesting any references.
2. **Generator arm:** use bounded coordinate perturbations and small cell
   strains from the seeds. Maximum 24 proposals, eight valid candidates
   retained, eight MLIP relaxations, and four reference relaxations. The
   maximum cell strain and displacement, distance screens, force/step
   stopping conditions and failure handling are fixed by Ahmad before the
   run. Numerical screens are engineering filters, not proofs of chemical
   validity.
3. **Non-generative arm:** use eight unperturbed seed structures, the same
   model and eight MLIP relaxations, and four reference relaxations chosen
   by the strongest frozen fixed-pool rule. Charge proposal handling and
   surrogate relaxation overhead in the generator arm. Both arms receive
   the same total **attempted** reference-job budget, including failures.
4. Run a prespecified decision-aware selection in the generator arm and
   the simple baseline in both arms as an ablation. Compare changes in
   candidate pool separately from changes in acquisition policy. Do not
   attribute the effect of both changes to generation alone.
5. For candidate-level outcomes, retain geometry before/after every
   relaxation, exact forces/energy units, elapsed/queue times, failed
   attempts, and the explicit model and DFT settings. No free retry is
   silently added. Unconverged reference jobs return a failed/unknown
   state, never zero energy.

Eight surrogate relaxations and four attempted references are proposed
caps, not an estimate of compute time or a purchase authorization. Common
physical calculations may be cached operationally but each counterfactual
policy must be charged according to its declared accounting. Evaluation
labels acquired solely to measure regret are reported as a separate
evaluation budget; they are not free information in the deployment policy.

## Required candidate records

Every attempted proposal gets a record, including rejects:

| Field | Required meaning |
|---|---|
| `candidate_id`, `parent_id`, `seed` | Stable identity and reproducible origin |
| `geometry_before_sha256`, `geometry_after_sha256` | Exact periodic cell, species and coordinates |
| `composition`, `protocol_id` | Compatible comparison group and reference definition |
| `proposal_kind`, `proposal_parameters` | Perturbation/search procedure |
| `validity_status`, `failure_reason` | Invalid cell, changed stoichiometry, collision screen, duplicate, model failure, nonconvergence or reference failure |
| `duplicate_of`, `duplicate_rule_version` | Structure matching after periodic/symmetry handling; a hash alone detects only exact byte repeats |
| `novelty_scope` | Only novelty relative to the actually inspected reference set; not a discovery claim |
| `mlip_relaxation`, `reference_relaxation` | Explicit status, model/settings, timing, costs, converged energy and forces if available |
| `decision_trace_id` | What was visible to selection before every reference query |
| `evidence_class` | Proposed, synthetic, replay or independently computed reference |

Record separately proposal rejection rate, pre/post-relaxation duplicate
rate, convergence failures, near-tie frequency and diversity across retained
basins. Report denominators even when a metric is undefined.

## Success and stop rules to lock before execution

Generation earns another batch only if it improves the buyer's chosen
physical proxy at equal measured cost, without unacceptable failure or
tail-risk increases, and the improvement survives fresh independent
reference calculations. The practically useful energy difference and
acceptable failure rate must be chosen by Ahmad and the buyer before the
first result is inspected; the current replay supplies neither a universal
threshold nor independent validation.

Stop or shrink the loop if most proposals return to existing basins, failed
relaxations consume the budget, apparent improvements disappear under the
reference protocol, or the simple non-generative pool provides equal
decisions more cheaply. Report any negative result rather than silently
enlarging search, changing the structure matcher, or using a different
functional after seeing the outcome.
