"""Explicitly synthetic engineering fixture; never evidence about molecules."""
from pathlib import Path

from .data import canonical_json, make_split, sha256_file, write_json


def prepare_fixture(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    scenarios = {
        "easy": ([0, 2, 3, 4, 5, 6], [0, 2, 3, 4, 5, 6]),
        "escalation_helps": ([0, .12, .25, 2, 3, 4], [2.1, 1.4, 0, 3, 4, 5]),
        "escalation_wastes": ([0, .06, .18, .30, .44, .49], [0, 1.2, 1.4, 1.6, 1.8, 2]),
        "confidently_wrong": ([0, 2, 3, 4, 5, 6], [1.5, 1.2, 0, 3, 4, 5]),
    }
    molecules = []
    for group in range(24):
        for name, (cheap, reference) in scenarios.items():
            # A tiny deterministic family-specific change keeps the deliberately
            # repeated structural cases visible. All family IDs are invented.
            scale = 1 + (group % 5) * .01
            candidates = [{"candidate_id": f"c{i}", "cheap_kcal": e * scale} for i, e in enumerate(cheap)]
            molecules.append({"molecule_id": f"synthetic_{group:02}_{name}",
                              "family_id": f"synthetic_family_{group:02}",
                              "candidates": candidates,
                              "references": {f"c{i}": e for i, e in enumerate(reference)}})
    manifest = make_split(molecules)
    manifest["family_rule"] = "24 explicitly invented synthetic groups, four engineering scenarios per group"
    from .data import digest
    manifest.pop("split_sha256")
    manifest["split_sha256"] = digest(manifest)
    assignment = {a["molecule_id"]: a["split"] for a in manifest["assignments"]}
    for split in ("development", "evaluation"):
        selected = [m for m in molecules if assignment[m["molecule_id"]] == split]
        with (out / f"{split}_features.jsonl").open("w") as f, (out / f"{split}_references.jsonl").open("w") as r:
            for m in selected:
                f.write(canonical_json({k: m[k] for k in ("molecule_id", "family_id", "candidates")}) + "\n")
                r.write(canonical_json({"molecule_id": m["molecule_id"], "references": m["references"]}) + "\n")
    write_json(out / "split_manifest.json", manifest)
    audit = {"dataset_kind": "synthetic", "source": "Hand-authored regression fixture; no real chemical results",
             "included_molecules": len(molecules), "included_candidates": sum(len(m["candidates"]) for m in molecules),
             "split_counts": manifest["counts"], "scenarios": list(scenarios),
             "source_limits": ["Synthetic labels are designed to exercise mechanics, not chemistry or statistical generalization."]}
    audit["prepared_files_sha256"] = {p.name: sha256_file(p) for p in sorted(out.glob("*.jsonl"))}
    write_json(out / "audit.json", audit)
    return audit
