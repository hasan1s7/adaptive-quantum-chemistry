# Data provenance and verification

This replay uses published, precomputed single-point energies. It does not run
xTB, ORCA, new quantum calculations, or geometry optimization. Its scientific
question is selection within a fixed published conformer pool.

## Upstream revision and terms

Repository: <https://github.com/ghutchis/conformer-benchmark>

Pinned commit: `0109c8ec7cff3c10d3617ed65392fffc81492755`

Commit date: July 9, 2020. Git tree:
`cf6accfe6bc27fdce5808c2078be67adff697199`.

The repository is described by its authors as a living benchmark. This replay
uses the pinned revision, not a moving branch. The upstream repository's
[MIT license](https://github.com/ghutchis/conformer-benchmark/blob/0109c8ec7cff3c10d3617ed65392fffc81492755/LICENSE)
is copyright 2020 Geoff Hutchison. Retain that license with redistributed
upstream material. The article is separately published; the replay does not
redistribute its full text.

Scientific citation: Dakota Folmsbee and Geoffrey Hutchison, “Assessing
conformer energies using electronic structure and machine learning methods,”
*International Journal of Quantum Chemistry*, 121(1), e26381, first published
July 9, 2020. DOI: <https://doi.org/10.1002/qua.26381>.
The [primary article](https://onlinelibrary.wiley.com/doi/full/10.1002/qua.26381)
provides the method descriptions below.

## What the energies describe

| Component | Published method metadata |
| --- | --- |
| Cheap score | GFN2-xTB, xTB version 6.2 |
| Reference | DLPNO-CCSD(T), TightPNO, cc-pVTZ, ORCA 4.0.1 |
| Geometry optimization preceding these scores | B3LYP-D3BJ/def2-SVP |
| Initial candidate generation | Diverse initial poses followed by PM7 selection and DFT optimization |
| Physical setting | Gas-phase electronic single-point energies on fixed geometries |

The article's introduction explicitly limits this comparison to single-point
energies on the same DFT-optimized geometries. Its computational-methods and
results sections identify the programs, basis sets, and optimized geometry
source. Iodine-containing species were omitted from the ab initio comparison
because the specified basis/ECP support was unavailable. Missing outputs have
additional causes that cannot all be reconstructed from these published
extracts; the loader reports missing keys rather than inventing explanations.

This benchmark does not establish solution free energies, entropy corrections,
experimental populations, chemical reactivity, or the completeness of global
conformer search. Its ceiling is the best available reference energy **inside
the retained published pool**.

## Files and matching keys

| File | Purpose | Git blob SHA at the pin |
| --- | --- | --- |
| `data-final.csv` | Author-compiled energy table with `name` and `geom` columns | `2d5c2123549468ae969d8fa7429293e58c18d8d8` |
| `energies/gfn2.txt` | Raw GFN2 atomization-energy extracts | `33932d14c82adaa58ad57ef4e4f2364b39769655` |
| `energies/ccsdt.txt` | Raw reference total-energy extracts | `80dd4b963e6d1e17f9983b20d3343bad7ad46bd2` |
| `compile-conformer-data.py` | Author's join and unit/sign transformations | `a9cd554d282e15334fdb960ae3fa9686a579ae53` |
| `SMILES/molecules.smi` | Molecular structures indexed by molecule name | `d865f1352176c8723108f85067b3f87a7153dbcb` |
| `LICENSE` | Upstream MIT license | `43fb9db6fd136283d74ea1c8529991cd09df6252` |

The join key is `(molecule ID, exact geometry stem)`, for example
`(astex_1gm8, rmsd112-opt)`. The geometry stem retains `-opt`. File extensions
such as `.mol` and `.out.bz2` are removed according to their verified formats.
No row-position join is used.

Published geometry locations are:

```text
geometries/Neutral_jobs/<molecule>/<stem>-opt.mol
geometries/Neutral_jobs/<molecule>/<stem>-opt.xyz
geometries/CHG_jobs/<molecule>/<stem>-opt.mol
geometries/CHG_jobs/<molecule>/<stem>-opt.xyz
```

`-mmff`, `-pm7`, and `-opt` refer to different geometry variants. The GFN2
extract contains all three. Only exact `-opt` entries are paired with the
reference here. A matching RMSD number alone is insufficient.

## Units and the important sign convention

Raw `energies/ccsdt.txt` lines end in a **total energy in Hartree**, where lower
is more stable. Raw `energies/gfn2.txt` provides positive **atomization
energies** in Hartree and kcal/mol. The upstream compilation uses its kcal/mol
field, rounded to 0.01 kcal/mol.

The author's
[compilation script](https://github.com/ghutchis/conformer-benchmark/blob/0109c8ec7cff3c10d3617ed65392fffc81492755/compile-conformer-data.py)
converts the reference to atomization energy using:

```text
reference_atomization_kcal
    = (sum_of_isolated_atomic_energies_hartree - molecular_total_hartree)
      * 627.509469
```

Consequently, both `gfn2` and `dlpno` in `data-final.csv` are atomization
energies: **larger atomization energy is more stable**. They cannot be ranked
as lower-is-better total energies without reversing their sign. Within a
molecule with unchanged composition:

```text
physical_reference_difference(i, j)
    = (raw_total_hartree(i) - raw_total_hartree(j)) * 627.509469
    = atomization_kcal(j) - atomization_kcal(i)
```

The conversion constant is retained from the pinned upstream script for
reproducibility. Absolute atomization offsets are not comparable between
molecules. Policy features use only cheap-energy differences within a pool;
reference-relative normalization belongs exclusively to evaluation.

Independent verification found that every available within-molecule reference
difference computed from the CSV agrees with the sign-reversed raw-Hartree
difference to 0.000001 kcal/mol. All 6,995 GFN2 CSV values exactly match their
raw rounded-kcal values. Rounded cheap scores can tie; stable candidate IDs
provide the deterministic tie break.

## Source audit and exclusions

The source audit is independent of policy performance.

| Check at the pinned revision | Count |
| --- | ---: |
| Raw GFN2 rows, all geometry variants | 28,481 |
| Raw GFN2 `-opt` rows | 6,995 |
| Other GFN2 geometry variants, excluded | 21,486 |
| Raw reference rows, all `-opt` | 6,755 |
| Exact GFN2/reference pairs | 6,755 |
| Molecules among those pairs | 702 |
| GFN2 `-opt` keys missing a reference output | 240 |
| Reference keys missing a GFN2 output | 0 |
| Duplicate eligible keys in either raw energy table | 0 |
| Malformed/nonnumeric rows in the two raw energy extracts | 0 |
| Compiled CSV rows / molecules | 6,995 / 708 |
| `.mol` files / `.xyz` files | 6,995 / 6,995 |
| Supplied SMILES records | 708 |

The 240 missing `dlpno` CSV values are empty cells, not numerical zeros. Every
raw reference key appears in the CSV, and all CSV/reference missingness agrees
with the raw extracts.

Define the initial candidate set from the published optimized geometries of
each molecule. Keep a molecule only if its whole set has valid cheap and
reference scores. Do not silently delete individual unlabelled conformers and
then claim to have evaluated the original whole pool.

| Pool eligibility outcome | Molecules | Candidates retained |
| --- | ---: | ---: |
| Complete reference pools, before excluding trivial tasks | 647 | 6,385 |
| Partial reference pools, excluded wholesale | 55 | 0 |
| No reference labels, excluded wholesale | 6 | 0 |
| Complete singleton pools, excluded as trivial selections | 7 | 0 |
| **Complete nontrivial pools** | **640** | **6,378** |

Of the retained pools, 632 contain ten conformers, four contain six, two
contain eight, and two contain nine. The seven singleton molecule IDs are
`omegapdb_1lww`, `omegacsd_CDBMPI10`, `omegapdb_1z1r`, `astex_1q41`,
`omegacsd_PEXFED`, `astex_1w1p`, and `astex_1u4d`.

The original paper's approximately 6,500 comparisons across 681 molecules use
different restrictions, including availability of other conventional methods.
Those historical counts are not this two-method replay's denominator.

Complete-case selection can favor molecules whose expensive jobs completed.
Conclusions therefore apply to these retained pools; they do not characterize
the unobserved outcomes of excluded jobs.

## Geometry and molecular-identity audit

All 6,995 published MOL/XYZ pairs have matching atom counts, atom element
ordering, and coordinates within 0.000051 angstrom. Every geometry's explicit
element composition matches the supplied molecular SMILES after explicit
hydrogen expansion. Atom element order and composition remain unchanged within
every molecule's pool. No exact duplicate atom-and-coordinate geometry was
found within a molecule. Geometry identities and source file digests are
recorded by the loader; this verification does not merge geometrically similar
conformers or optimize any structures.

All 708 supplied SMILES parse under RDKit 2025.09.6. There are no repeated
molecule names or duplicate canonical nonstereochemical molecular structures
in that list. All 86 entries in `geometries/CHG-charges.txt` agree with the
SMILES net formal charges; none of the charged SMILES lacks an entry. Eight
directories under `CHG_jobs` describe net-neutral species, so directory names
must not be interpreted as the net molecular charge.

**The MOL bond/charge annotations are not an independently verified chemical
graph.** Under RDKit's default sanitization, 2,240 MOL files fail to sanitize.
Of the 4,755 that parse, 717 produce a nonstereochemical graph different from
the supplied SMILES. Coordinate-derived bond perception, formal-charge
annotations, and implicit-hydrogen handling are not interchangeable with the
authors' molecular identity list. These observations are recorded as a
limitation, not silently “fixed” by changing a geometry. Supplied SMILES are
used for family assignment, while published elements and coordinates are used
for geometry identity.

The repository contains coordinate files, energy extracts, and atomic
reference-calculation input/output files under `atoms/`. It does not contain
the original full per-conformer ORCA/xTB inputs and outputs needed to recheck
every molecular calculation's coordinate block, convergence status, charge,
multiplicity, or threshold settings. Thus the supported assertion is **a source-keyed replay
of the authors' documented same-geometry single-point comparison**, not an
independent regeneration or full quantum-job audit. Program/method metadata
are paper-level metadata rather than newly recovered per-job metadata.

## Chemical-family split

No supplied family IDs were found. Families are inferred without using any
energy values, using the supplied SMILES and pinned RDKit 2025.09.6:

1. Parse the molecule and compute its Bemis–Murcko scaffold.
2. Make the scaffold generic (atom identity and bond order generalized), and
   serialize a canonical nonstereochemical scaffold SMILES.
3. Assign all empty-scaffold/acyclic structures to one conservative shared
   family.
4. Keep canonical duplicate molecular structures together through the same
   deterministic scaffold rule; reject conflicting family assignments. The
   source list has no canonical duplicate structures.

The 640 eligible molecules yield **411 families**. The acyclic family contains
24 molecules; the largest cyclic generic-scaffold family contains 27.
Family keys, member molecule IDs, and the final development/evaluation
assignment are written to the split manifest. Families are ordered by a
seeded SHA-256 rule, and 70% are assigned to development with the remainder
held out. The manifest, rather than rounded percentages, is authoritative for
the exact group and molecule counts.

This inferred scaffold definition prevents exact generic-scaffold overlap
under the documented rule. It does not establish that every possible chemical
analogue is separated. Some closely related molecules can have different
scaffolds. All conformers of every molecule remain in the same group, and the
held-out family count is included in statistical reports. Family-resampled
uncertainty reflects this grouping rather than treating conformers as
independent observations.

## Interpretation boundary

The labels already exist; a charged query is a replay accounting event. Calls
saved are not measured wall-clock or financial savings. No reference labels
are available to a policy except through its charged oracle queries. The
results do not demonstrate the value of shape probes, which have not been
implemented in this milestone. They establish the simple-policy cost/risk
baseline that a later acquisition method must improve on untouched families.
