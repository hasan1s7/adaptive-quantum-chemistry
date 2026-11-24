# Independent v0.2 statistical and protocol review

**Review status:** no outstanding registration blockers identified. The review
was completed before the 1,020-configuration sweep was frozen. This note does
not assert a result for that sweep or independently certify population risk.

## Scope and method

Read-only review of `aqc/experiments.py`, `aqc/statistics.py`,
`aqc/integrity.py`, their integration with the paid oracle, and
`docs/EXPERIMENT_PROTOCOL_V02.md`. The reviewer did not edit those scientific
modules or any historical result files. Two targeted calculations used
temporary synthetic data and left no experiment outputs in the source tree.

The review examined registry construction; family assignments; training-only
configuration selection; matched-risk comparator selection; paired bootstrap
weights; trace catalog and ledger reconstruction; independent selected-policy
replays; saved decision consistency; and failure-path audit retention.

## Independent checks performed

Commands were executed from the repository root using Python 3:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import numpy as np
from aqc.experiments import (
    build_configurations, make_family_folds,
    training_statistics, choose_from_training,
)

configs = build_configurations(10)
print('registry_counts', len(configs),
      sum(c['generation'] == 'original' for c in configs),
      sum(c['kind'] == 'sequential' for c in configs))
pools = [
    {'molecule_id': f'm{i}', 'family_id': f'f{i//2}',
     'candidates': [{'candidate_id': 'a', 'cheap_kcal': 0},
                    {'candidate_id': 'b', 'cheap_kcal': 1}]}
    for i in range(20)
]
folds = make_family_folds(pools)
shape = (len(configs), len(pools))
outcomes = {'regrets': np.zeros(shape),
            'calls': np.full(shape, 2),
            'fallbacks': np.zeros(shape, dtype=bool)}
for i, c in enumerate(configs):
    if c['kind'] == 'diagnostic':
        outcomes['calls'][i] = 0
    if c['kind'] == 'fixed' and c['config']['k'] == 1:
        outcomes['calls'][i] = 1
before = choose_from_training(
    configs, training_statistics(configs, outcomes, pools, folds, 0))
fold_of = {r['molecule_id']: r['fold_id'] for r in folds['assignments']}
validation = [i for i, p in enumerate(pools)
              if fold_of[p['molecule_id']] == 0]
# Deliberately extreme values expose accidental validation-slice use.
outcomes['regrets'][:, validation] = 999
outcomes['calls'][:, validation] = 999
outcomes['fallbacks'][:, validation] = True
after = choose_from_training(
    configs, training_statistics(configs, outcomes, pools, folds, 0))
print('independent_validation_perturbation',
      {'validation_molecules_changed': len(validation),
       'selection_unchanged': before == after})
PY
```

Observed output:

```text
registry_counts 1020 204 816
independent_validation_perturbation {'validation_molecules_changed': 4, 'selection_unchanged': True}
```

A second temporary synthetic experiment supplied internally consistent
per-molecule and aggregate numbers with **50%** sequential success, but falsely
set `observed_95pct_success_met` and `observed_joint_target_met` to `true`.
Before the correction, `write_artifact_seal` followed by
`verify_artifact_seal(require_complete=True)` accepted the evidence. After the
correction, the same counterexample failed:

```text
{'false_target_claim_rejected': True,
 'reason': 'Evidence inconsistency: decision.observed_95pct_success_met'}
```

The independent prefreeze oracle verification also executed:

```bash
python3 -m unittest discover -s tests -p test_oracle.py -v
python3 -m unittest discover -s tests -p test_policy_v2.py -v
```

Those commands passed **18** original oracle tests and **30** v0.2 tests.
The latter launch actual child interpreters through `PolicySession.run` and
`benchmark.evaluate_logged` for decoding, pipe, ID/type, protocol, timeout,
blocked-write, stderr, and cleanup failures. They verify that charged attempts
survive the failure. These counts describe the reviewer-run subsets, not the
complete release test count.

## Findings resolved before registration

1. **Saved target flags could contradict the numerical evidence.** The generic
   integrity check verified numerical summaries but did not recompute all
   success, risk-matching, savings, and joint-target Boolean claims. The root
   implementation now validates those claims. The experiment verifier also
   recomputes the complete `decision.json` from audited out-of-fold outcomes.
   The reviewer independently reran the failing 50%-success counterexample and
   confirmed rejection after the change.

2. **The expanded execution paths initially dropped failure detail.** The
   registry sweep recorded charges but omitted observations, streamed policy
   decisions, original failure type/stage, stderr, and cleanup errors. The
   selected-policy replay path initially had no durable record of its current
   failed replay. The experiments author added full failure metadata and a
   failed replay record before aborting. The resulting records retain paid
   attempts instead of silently excluding failed cases.

## Selection and label-boundary assessment

`training_statistics` takes only the complement of the designated validation
fold into its metrics, and `choose_from_training` receives those metrics rather
than validation outcomes. The independent perturbation above confirms the
selection boundary on a controlled case. Families remain whole in the fold
assignments and folds are derived from identifiers rather than energies.

The primary comparator is the cheapest original fixed/window/full rule whose
**training** success is at least both 95% and the selected sequential rule's
training success. Validation outcomes do not repair or replace that comparator.
The resulting pooled comparison is a comparison of fold-selected procedures.

The expanded runner and verifier call `load_pools(..., 'development')` only.
`verify_prepared` still reads the evaluation reference file's **bytes** to check
its checksum; those bytes are not parsed as reference-label rows or used for
configuration selection. This is a code-path finding, not a claim that the
historical evaluation has never been observed. It has already been reported and
is explicitly excluded from the new evidence claim.

## Verification coverage and limits

The ledger audit resolves every configuration–pool record, reconstructs its
charged-query core and annotations, checks reference reveals and best verified
selection against the parent oracle, recomputes regret, verifies complete
configuration–pool coverage, and recomputes fold choices and summary statistics.
Trace deduplication reduces stored bytes; it does not reduce per-run charges.
Independent policy executions are repeated for the selected out-of-fold
configuration–pool outcomes. The verifier does not claim a second independent
policy execution for every one of the 487,560 registered grid decisions.

Family bootstrap draws use the same multiplicities for both policies and retain
whole families within fixed outer-fold strata. The intervals are descriptive,
conditional on the fixed folds and selected policies. They do not reselect
configurations, account for dependence from overlapping training folds, provide
a simultaneous confidence guarantee, or establish performance on new external
chemistry. The source's explicit conditional-interval note states these limits.

The sequential error envelope is an empirical stopping heuristic. Successful
reference feedback changes its acquisition decisions, but its formula is not a
bound on errors at unqueried candidates. One-query exits use cheap separation
alone and can be confidently wrong. A result for this development experiment
cannot establish that shape probes are useful; no shape probe was measured.

Content hashes and consistency checks protect against accidental modification
and mixed runs. They are not signatures or independent attestations. This
review involved no quantum jobs, paid compute, deployment, outreach, source
commits, or Git pushes.
