# Independent engineering review of the data boundary

**Evidence class: executed inspection and synthetic contract tests.** This
review is independent code inspection within this development session; it
is not an independent laboratory replication or a fresh scientific cohort.

## Actual prepared data

The prepared oxide benchmark has **103 same-composition pools, 367 retained
candidates and 93 chemical-system groups**. Whole-system assignments contain
35 training pools, 28 calibration pools, 30 test pools and ten Li-system shift
pools. All candidate IDs, source prediction hashes, output seals and raw
reference values were inspected.

`scripts/audit_decision_data.py` passed these checks:

- Every chemical system remains in its assigned split; each composition has
  one pool, and a candidate ID appears once.
- The same-composition initial-prototype deduplication contains no remaining
  duplicate keys. No relaxed symmetry, reference minimum, relaxed volume,
  reference correction or other undeclared field appears in public
  candidate records.
- Each model's public prediction is exactly its raw published value minus
  that model's value at the lexicographically first candidate. This uses
  no reference energy. The primary mean is MACE; disagreement uses the
  three models' contrasts to the cheap-selected anchor.
- The evaluator's private energy equals the published uncentered corrected
  formation energy for every candidate. No reference-minimum normalization
  was inserted into a policy observation.
- Group calibration scores are the maximum standardized anchored error
  over all candidates and all pools in each of **24 calibration chemical
  systems**. The stored finite-sample quantiles reproduce exactly. The
  combined scale has q90 = 3.001405 and q95 = 3.085848.

The review also added a guard to fitting: verify the preparation seal before
creating any fit output, and reject missing or invalid training/calibration
labels explicitly as unsupported. No successful-label subset is silently
substituted.

## Geometry backing and near duplicates

Initial structures are available for every retained candidate. A separate
inspection of all **367** verifies the geometry-artifact digest, source
stage before DFT relaxation, composition, system, atom counts, three periodic
boundaries, finite arrays, positive cell volume and the fractional-to-Cartesian
coordinate conversion.

There are **zero cross-split exact or screened near-duplicate pairs**. The
retained close pair `wbm-1-37022` / `wbm-1-37023` (GeO₂, two initial symmetry
labels) stays within the same training pool. Other screened pairs lose one
or both members under pre-query prototype/singleton exclusions. The detailed
membership record is `independent_geometry_audit.json`.

The source screen uses species-pair periodic distance spectra, equal atom
counts, relative volume difference ≤0.001, RMS distance-spectrum difference
≤0.01 Å and maximum difference ≤0.03 Å, searching periodic images from −2
through +2. It is a diagnostic screen, not a proof of crystallographic
identity or exhaustive near-duplicate detection. Chemical-system partitioning
keeps same-composition neighbors together even when the screen misses one.
Different compositions can share abstract prototypes and remain correlated.

## Executed behavioral tests

Nine independent tests in `tests/test_decision_engine_data.py` passed. The
critical leakage tests changed all test and Li-shift reference labels by very
large offsets and confirmed unchanged training coefficients, cutoff and
calibration quantiles. Changing calibration labels changed the intervals but
left fitted scale coefficients and the training-only cutoff unchanged.
Other tests cover invalid oxide formula rules, deterministic system splits,
cross-split and duplicate rejection, finite-group quantile edge cases,
tampered sealed inputs and unavailable training labels.

These are tests of the implemented information boundary. They do not prove
the model has never seen related structures: pretrained model overlap and
shared training protocols remain scientific limitations.

## Reproduce the inspections

```bash
python -m unittest discover -s tests -p test_decision_engine_data.py -v
python scripts/audit_decision_data.py \
  --prepared results/decision_engine/oxide_prepared \
  --fit results/decision_engine/oxide_fit \
  --out runs/independent-data-audit.json
python scripts/audit_initial_geometry_splits.py \
  --prepared results/decision_engine/oxide_prepared \
  --out runs/independent-geometry-audit.json
```

The first data-only audit's metadata limitation is supplemented by the
separate initial-geometry audit. Neither inspection acquires labels, retunes
the policy, performs a new relaxation or alters a split.
