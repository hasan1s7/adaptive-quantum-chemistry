# Decision engine release notes

## 28 November 2026 - presentation and source release

This release makes the completed experiment easier to inspect, explain and reproduce. Its scientific record is the frozen **27 November 2026** replay. Publication is scoped to a focused GitHub branch; deployment is outside this release.

### What readers get

- A short [entrypoint](../../README_DECISION_ENGINE.md) that leads with the decision and the three strongest comparison points.
- A focused result dashboard that explains the decision, the SnO₂ failure case, uncertainty and cost without requiring the reader to start with the full experiment ledger.
- A separate [runbook](RUNBOOK.md) containing the detailed commands, provider interface, input/scoring contract and reproducibility limitations.
- The full [technical memo](TECHNICAL_MEMO.md), physics and statistical reviews, source attribution, prepared inputs, recorded results and validation code.
- A small source/evidence distribution. The five raw numerical tables are restored with `python -m erkidu_decision fetch`; they are not committed as a new raw-data cache.

### Scientific result retained

At the 20 meV/atom endpoint, MACE top two succeeds on **29/30** test pools using **60** historical reference labels. Decision-aware acquisition reaches **30/30** at the same count. Frozen M3GNet also reaches **30/30**, using **zero** reference labels. The adaptive difference is one SnO₂ rescue, with a paired uncertainty interval that includes no improvement.

This presentation release does not choose a new operating point, refit uncertainty, alter a split or run a new scientific evaluation. Model-only results, paid acquisition, synthetic faults and geometry-only generation retain separate evidence labels. The verdict remains: keep the auditable evaluation workflow; a broad adaptive-compute-saving claim has not been earned.

### Source and evidence integrity

The frozen result, preparation and fit manifests describe the original experiment. Presentation changes are versioned separately. The original reporting source is retained at [`results/decision_engine/source_at_run/reporting.py`](../../results/decision_engine/source_at_run/reporting.py) so an audit can distinguish executed scientific source from a later presentation implementation. The sealed scientific manifests are not rewritten to conceal source changes.

The historical technical memo describes what happened on 27 November, including its local-only execution and browser-validation limits. Those dated statements are not a timeless description of the later source-publication workflow. Any release-specific implementation or visual checks should be read with their own scope; they do not become fresh physics validation.

### What remains unmeasured

No live MLIP inference, new DFT job, force validation, physical generation improvement, measured reference-runtime saving or dollar saving is introduced by this release. The measured geometry prototype consists of five proposals and five unchanged-input validations, with no energy or force model evaluated. The strongest simple model remains a mandatory comparator for a future customer evaluation.

### Public metadata extraction

Automatic publication review blocked an initial attempt because upstream metadata dumps included unrelated administrative and private-source records. Before publication, those dumps were replaced with explicit public-field extracts; the source registry now distinguishes original capture hashes from published extract hashes. Unrelated file listings and local cache paths were also removed from the ancillary registry. No scientific labels, traces or seals changed. The sanitized commit is based directly on the existing public repository commit, with no unsanitized local commit in its ancestry. [Metadata transformation](../../data/decision_engine/source_metadata/publication_manifest.json).

The [exact-tree metadata audit](../../results/decision_engine/release/metadata_publication_audit.json) found zero issues; all 32 scientific sealed files were independently reverified. An additional check found none of the 38 excluded account/private-source strings in the selected publication blobs.

### Release verification

The selected source tree passed a clean-checkout check with no raw-data cache: **51 scientific/contract tests, 10 historical replay tests and 103 dashboard assertions**. The canonical verifier checked 19 sealed files and 1,320 primary traces. A separate full audit checked 1,720 recorded runs and 3,423 query attempts with no failures. [Validation receipt](../../results/decision_engine/release/validation.json).

The dashboard assertions cover control coherence, reference visibility, embedded downloads, keyboard behavior and narrow-view chart logic. Real-browser visual QA was unavailable because this environment has no working browser executable. These checks validate the publication and presentation; they do not add a new scientific experiment.

## 27 November 2026 - frozen research snapshot

- Reproduced the earlier 956-call conformer comparison; inspected the completed 669-call records without rerunning those policies.
- Prepared 103 ordinary-oxide pools and fixed chemical-system splits before evaluation.
- Executed energy-only reference-relaxation replay, calibration comparisons, equal-budget acquisition, model-only baselines, seed repeats and explicitly synthetic failure tests.
- Preserved a preparation failure and an interval-trace wording repair, with separate accounting of the verification rerun.
- Produced the technical memo, local dashboard, per-query traces, physics/statistical review sheets and bounded geometry-only generation records.

The [runbook](RUNBOOK.md) gives exact commands and points to the deeper evidence for each item.
