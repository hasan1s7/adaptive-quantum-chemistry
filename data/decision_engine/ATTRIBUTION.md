# Data attribution and redistribution scope

The numerical source tables and initial-geometry subset are derived from **Matbench Discovery** and the **Wang–Botti–Marques (WBM)** dataset. Preserve the following attribution when redistributing them:

- Wang, Botti and Marques, “Predicting stable crystalline compounds using chemical similarity” (2021): https://www.nature.com/articles/s41524-020-00481-6
- Riebesell et al., “A framework to evaluate machine learning crystal stability predictions” (2025): https://doi.org/10.1038/s42256-025-01055-1
- Matbench Discovery data files, Figshare article **22715158 version 42**: https://api.figshare.com/v2/articles/22715158/versions/42
- Matbench Discovery model predictions, Figshare article **28187990 version 31**: https://api.figshare.com/v2/articles/28187990/versions/31
- Pinned source metadata: https://github.com/janosh/matbench-discovery/tree/58b3bd5b95c1165c5208150203007cea0031c64c

Both consumed Figshare articles identify the data licence as **Creative Commons Attribution 4.0**: https://creativecommons.org/licenses/by/4.0/ . The retrieved licence fields are retained in public metadata extracts at `source_metadata/22715158_metadata.json` and `source_metadata/28187990_metadata.json`. The pinned model cards identify the authors and original prediction workflows for MACE-MP-0, CHGNet and M3GNet.

Changes made for this experiment: formula-based subset selection, composition reduction, initial-prototype deduplication, chemical-system splitting, model-only energy anchoring, uncertainty fitting and calibration, policy replay, and extraction of eligible initial geometries. Original raw table bytes remain unchanged and have pinned checksums. Generated geometry perturbations are separately identified as generated and unvalidated physically.

The public Materials Project support table is a proxy for model support. It is not an exact reconstruction of all pretrained model training sets. Model weights, proprietary/licensed pseudopotential files and fresh quantum outputs are not included. The M3GNet card's checkpoint-licence label differs from the licence file to which it links; that discrepancy does not license or redistribute a checkpoint here. The consumed prediction data are covered by the Figshare data terms.

Historical molecular development inputs retain the upstream licence in `data/UPSTREAM_LICENSE` and the attribution/source pins in `docs/decision_engine/RECOVERY.md`. Their original protocols and units must remain separate from the oxide experiment.

## Public metadata scope

The published source records are filtered public extracts, not complete upstream administrative responses. Only article attribution, licence fields, public source URLs and consumed-file metadata are retained; file names are normalized to basenames. The [metadata publication manifest](source_metadata/publication_manifest.json) distinguishes original source-capture checksums from public-extract checksums. Unrelated administrative/private-source records and uploader-local file listings are omitted. This transformation does not alter scientific labels, split assignments or result seals.
