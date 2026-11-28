# Ahmad's physics review: two real development failures

**Status:** actual archived energy-label replay, reproduced now; no chemist
review or causal interaction assignment has occurred. Geometry is available
in `results/decision_engine/recovery/physics_failure_cases.json` with its
pre-label fingerprints. The cases concern ordinary fixed molecular pools;
they do not establish pharmaceutical activity or application performance.

## Case 1: `omegapdb_2byi` — a shared ranking failure survives two queries

Family `family_5eb52cf034a3345a`. The cheap rank-one candidate is
`rmsd129-opt`. The fixed and steric rules both query it and rank two,
`rmsd164-opt`. Their final regret is **5.146528 kcal/mol**, the worst fixed
top-two result in this development set. The xTB gap is only 0.13 kcal/mol.
Every eligible candidate's steric penalty is zero, so that feature contributes
no distinguishing evidence. This is not a forecasted high-confidence event:
the historical policies emitted no calibrated uncertainty.

| Cheap rank | Candidate | xTB energy above cheap minimum, kcal/mol | Reference above reference minimum, kcal/mol |
|---:|---|---:|---:|
| 1 | `rmsd129-opt` | 0.00 | 5.146528 |
| 2 | `rmsd164-opt` | 0.13 | 5.874949 |
| 3 | `rmsd180-opt` | 1.31 | 3.204543 |
| 4 | `rmsd229-opt` | 1.55 | 2.168778 |
| 5 | `rmsd235-opt` | 1.68 | 2.311847 |
| 7 | `rmsd78-opt` | 2.21 | 0.000000 |

The actual best reference candidate is cheap rank seven. The selector's
rank-two-through-five shortlist excludes it regardless of the descriptor.
Even moving to the most torsionally different eligible candidate leaves
3.204543 kcal/mol regret. This exposes a shortlist limitation as well as
cheap-model misranking.

**Review questions:** Verify connectivity, charge and multiplicity from the
authoritative source. Which intramolecular interactions could plausibly be
misranked, and what observation would contradict that explanation? Is the
rank cap scientifically justified? Would a geometry descriptor visible
before reference labels flag this pool, and can that claim be frozen for
unseen families? Do not infer a particular hydrogen bond or dispersion
mechanism solely from the ranking table.

## Case 2: `omegapdb_1bhx` — diversity spends the same budget and makes selection worse

Family `family_5099cb7747f52e7a`. Both rules start at `rmsd107-opt`. Fixed top
two buys `rmsd212-opt`, which is the reference minimum. The torsion policy
instead buys rank three, `rmsd124-opt`, and finishes **1.176506 kcal/mol**
above the reference minimum. The steric rule keeps rank two and succeeds.

| Candidate | Cheap rank | xTB gap, kcal/mol | Torsion RMS from rank one, rad | Steric penalty | Reference gap, kcal/mol |
|---|---:|---:|---:|---:|---:|
| `rmsd107-opt` | 1 | 0.00 | — | — | 3.645705 |
| `rmsd212-opt` | 2 | 2.01 | 1.522484 | 0 | 0.000000 |
| `rmsd124-opt` | 3 | 2.63 | 1.949391 | 0 | 1.176506 |

Both second candidates meet the fixed cheap-energy window. Greater torsional
distance does not imply greater decision value. The inferred graph has 61
bonds and 11 eligible heavy-atom torsions; no expert checked those inferred
torsions or their atom correspondence. The threshold loss is 0.176506
kcal/mol beyond the chosen 1 kcal/mol tolerance, so the downstream reason
for that threshold matters.

**Review questions:** Verify the graph and symmetry treatment. Are all measured
torsions chemically relevant, or does the metric overweight a peripheral
degree of freedom? What pre-label property could justify preferring rank
three at equal budget? Would the physical endpoint change if the loss were
continuous regret rather than a 1 kcal/mol threshold?

## Review decision fields

For each case record: verified source identity; charge and multiplicity;
connectivity checked; proposed physical explanation; contradicting evidence;
one observable available before the reference query; and a frozen prediction
for a future family. Mark an unsupported field **unknown**. No successful
review or approved fresh reference calculation is implied by this sheet.
