"""Evaluator-only decision tables and family-cluster uncertainty.

The rows accepted here are completed evaluator results, never policy features.
Every uncertainty draw resamples chemical *families*, retaining every molecule
and its paired policy outcomes.  Point estimates are molecule-weighted.  These
are descriptive percentile bootstrap intervals, not risk-control guarantees.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np


SUCCESS_KCAL = 1.0
SUCCESS_TOLERANCE = 1e-9
SUMMARY_INTERVAL_METRICS = (
    "success_rate", "mean_calls", "p95_regret_kcal", "fallback_rate"
)
PAIRED_METRICS = (
    "delta_success_rate", "delta_mean_regret_kcal", "delta_mean_calls",
    "delta_fallback_rate", "relative_call_savings"
)


def _boolean(value: Any, name: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.lower() in ("true", "false", "0", "1"):
        return value.lower() in ("true", "1")
    raise ValueError(f"{name} must be boolean, got {value!r}")


def _integer(value: Any, name: str, minimum: int) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be an integer")
    try:
        parsed = int(value)
        numeric = float(value)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f"{name} must be an integer") from error
    if not math.isfinite(numeric) or numeric != parsed or parsed < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return parsed


def _validated_groups(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    observed: set[tuple[str, str]] = set()
    molecule_metadata: dict[str, tuple[str, int]] = {}
    for original in rows:
        row = dict(original)
        for field in ("policy", "molecule_id", "family_id"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise ValueError(f"{field} must be a nonempty string")
        key = (row["policy"], row["molecule_id"])
        if key in observed:
            raise ValueError(f"duplicate molecule/policy result: {key}")
        observed.add(key)
        row["n_candidates"] = _integer(row.get("n_candidates"), "n_candidates", 1)
        row["expensive_calls"] = _integer(row.get("expensive_calls"), "expensive_calls", 0)
        if row["expensive_calls"] > row["n_candidates"]:
            raise ValueError("expensive_calls exceeds fixed candidate pool")
        if row["policy"] != "cheap_only" and row["expensive_calls"] == 0:
            raise ValueError("a paid policy must make at least one expensive call")
        if row["policy"] == "cheap_only" and row["expensive_calls"] != 0:
            raise ValueError("cheap_only is the unverified zero-call diagnostic")
        try:
            regret = float(row["regret_kcal"])
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError("regret_kcal must be a finite number") from error
        if not math.isfinite(regret) or regret < -SUCCESS_TOLERANCE:
            raise ValueError("regret_kcal must be finite and nonnegative")
        row["regret_kcal"] = max(0.0, regret)
        row["fallback"] = _boolean(row.get("fallback"), "fallback")
        metadata = (row["family_id"], row["n_candidates"])
        previous = molecule_metadata.setdefault(row["molecule_id"], metadata)
        if metadata != previous:
            raise ValueError(f"family or pool size mismatch for {row['molecule_id']}")
        grouped.setdefault(row["policy"], []).append(row)
    if not grouped:
        raise ValueError("cannot summarize an empty evaluation")
    return {
        policy: sorted(group, key=lambda row: row["molecule_id"])
        for policy, group in sorted(grouped.items())
    }


def _arrays(rows: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    regret = np.asarray([row["regret_kcal"] for row in rows], dtype=float)
    calls = np.asarray([row["expensive_calls"] for row in rows], dtype=float)
    return {
        "regret": regret,
        "success": (regret <= SUCCESS_KCAL + SUCCESS_TOLERANCE).astype(float),
        "calls": calls,
        "fraction": calls / np.asarray([row["n_candidates"] for row in rows], dtype=float),
        "fallback": np.asarray([row["fallback"] for row in rows], dtype=float),
    }


def _family_weights(rows: list[dict[str, Any]], bootstrap: int, seed: int) -> np.ndarray:
    """Multiplicity of each molecule under bootstrap draws of whole families."""
    families = sorted({row["family_id"] for row in rows})
    family_index = {family: i for i, family in enumerate(families)}
    indexes = np.asarray([family_index[row["family_id"]] for row in rows], dtype=int)
    generator = np.random.default_rng(seed)
    family_multiplicities = generator.multinomial(
        len(families), np.repeat(1.0 / len(families), len(families)), size=bootstrap
    )
    return family_multiplicities[:, indexes]


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> np.ndarray:
    """NumPy's linear quantile on integer-repeated observations, without repeats."""
    order = np.argsort(values, kind="stable")
    values = values[order]
    weights = weights[:, order]
    cumulative = np.cumsum(weights, axis=1)
    positions = quantile * (cumulative[:, -1] - 1)
    low = np.floor(positions).astype(int)
    high = np.ceil(positions).astype(int)
    low_indexes = np.sum(cumulative <= low[:, None], axis=1)
    high_indexes = np.sum(cumulative <= high[:, None], axis=1)
    fraction = positions - low
    return values[low_indexes] * (1.0 - fraction) + values[high_indexes] * fraction


def _set_interval(result: dict[str, Any], metric: str, samples: np.ndarray | None) -> None:
    if samples is None:
        result[f"{metric}_ci_low"] = None
        result[f"{metric}_ci_high"] = None
    else:
        low, high = np.quantile(samples, [0.025, 0.975], method="linear")
        result[f"{metric}_ci_low"] = float(low)
        result[f"{metric}_ci_high"] = float(high)


def summarize(
    rows: Iterable[dict[str, Any]], bootstrap: int = 2000, seed: int = 1729
) -> list[dict[str, Any]]:
    """Return one decision-table record per policy.

    A zero ``bootstrap`` is useful for development grid searches; interval fields
    are then ``None``.  ``total_calls`` and ``mean_call_fraction`` have different
    denominators: the latter weights molecules equally, not conformers.
    """
    bootstrap = _integer(bootstrap, "bootstrap", 0)
    grouped = _validated_groups(rows)
    records: list[dict[str, Any]] = []
    for policy, group in grouped.items():
        arrays = _arrays(group)
        n_families = len({row["family_id"] for row in group})
        result: dict[str, Any] = {
            "policy": policy,
            "n_molecules": len(group),
            "n_families": n_families,
            "success_rate": float(np.mean(arrays["success"])),
            "median_regret_kcal": float(np.median(arrays["regret"])),
            "p95_regret_kcal": float(np.quantile(arrays["regret"], 0.95, method="linear")),
            "max_regret_kcal": float(np.max(arrays["regret"])),
            "mean_calls": float(np.mean(arrays["calls"])),
            "total_calls": int(np.sum(arrays["calls"])),
            "mean_call_fraction": float(np.mean(arrays["fraction"])),
            "fallback_rate": float(np.mean(arrays["fallback"])),
            "bootstrap_replicates": bootstrap,
            "interval_method": "family-cluster percentile bootstrap; molecule-weighted",
            "uncertainty_warning": (
                "one family: no between-family uncertainty can be estimated" if n_families == 1 else ""
            ),
        }
        if bootstrap:
            weights = _family_weights(group, bootstrap, seed)
            denominators = np.sum(weights, axis=1)
            samples = {
                "success_rate": (weights @ arrays["success"]) / denominators,
                "mean_calls": (weights @ arrays["calls"]) / denominators,
                "p95_regret_kcal": _weighted_quantile(arrays["regret"], weights, 0.95),
                "fallback_rate": (weights @ arrays["fallback"]) / denominators,
            }
        else:
            samples = {}
        for metric in SUMMARY_INTERVAL_METRICS:
            _set_interval(result, metric, samples.get(metric))
        records.append(result)
    return records


def paired_comparisons(
    rows: Iterable[dict[str, Any]], bootstrap: int = 2000, seed: int = 1729
) -> list[dict[str, Any]]:
    """Compare every paid policy with fixed_top_k and full_rerank.

    Deltas are policy minus comparator; a positive ``relative_call_savings`` is
    a reduction in calls.  Self comparisons and the unverified diagnostic are
    omitted.  All supplied paid policies must cover exactly the same molecules,
    with the same family assignments and fixed candidate-pool sizes.
    """
    bootstrap = _integer(bootstrap, "bootstrap", 0)
    grouped = _validated_groups(rows)
    paid = {name: group for name, group in grouped.items() if name != "cheap_only"}
    if not paid:
        return []
    first = next(iter(paid.values()))
    expected = [row["molecule_id"] for row in first]
    for name, group in paid.items():
        if [row["molecule_id"] for row in group] != expected:
            raise ValueError(f"paired comparison requires identical molecule pools: {name}")
    arrays = {name: _arrays(group) for name, group in paid.items()}
    weights = _family_weights(first, bootstrap, seed) if bootstrap else None
    denominators = np.sum(weights, axis=1) if bootstrap else None
    comparisons: list[dict[str, Any]] = []
    for policy in paid:
        for comparator in ("fixed_top_k", "full_rerank"):
            if comparator not in paid or comparator == policy:
                continue
            left, right = arrays[policy], arrays[comparator]
            differences = {
                "delta_success_rate": left["success"] - right["success"],
                "delta_mean_regret_kcal": left["regret"] - right["regret"],
                "delta_mean_calls": left["calls"] - right["calls"],
                "delta_fallback_rate": left["fallback"] - right["fallback"],
            }
            result: dict[str, Any] = {
                "policy": policy,
                "comparator": comparator,
                "n_molecules": len(first),
                "n_families": len({row["family_id"] for row in first}),
                "bootstrap_replicates": bootstrap,
                "interval_method": "paired family-cluster percentile bootstrap; molecule-weighted",
                "relative_call_savings": float(1.0 - np.sum(left["calls"]) / np.sum(right["calls"])),
            }
            for metric, values in differences.items():
                result[metric] = float(np.mean(values))
                samples = (weights @ values) / denominators if bootstrap else None
                _set_interval(result, metric, samples)
            savings = (
                1.0 - (weights @ left["calls"]) / (weights @ right["calls"])
                if bootstrap else None
            )
            _set_interval(result, "relative_call_savings", savings)
            comparisons.append(result)
    return comparisons


def plot_risk_calls(
    frontier_rows: Iterable[dict[str, Any]],
    output_path: str | Path,
    title: str,
    heldout_families: int,
) -> str:
    """Save an exact two-panel scientific plot of evaluator summaries.

    Repeated ``policy`` names may represent a preregistered operating-point grid.
    The plot does not choose an operating point.  Held-out results should only
    be used to report previously frozen policies.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    records = [dict(row) for row in frontier_rows]
    if not records:
        raise ValueError("cannot plot an empty decision table")
    heldout_families = _integer(heldout_families, "heldout_families", 1)
    for row in records:
        for field in ("success_rate", "mean_calls", "p95_regret_kcal"):
            if field not in row or not math.isfinite(float(row[field])):
                raise ValueError(f"plot needs finite {field}")
        if not 0 <= float(row["success_rate"]) <= 1 or float(row["mean_calls"]) < 0:
            raise ValueError("plot success/call values out of bounds")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        name = str(row["policy"])
        category = (
            "cheap_only" if name == "cheap_only"
            else "full_rerank" if name == "full_rerank"
            else "fixed_top_k" if name.startswith("fixed")
            else "adaptive" if name.startswith("adaptive")
            else name
        )
        grouped.setdefault(category, []).append(row)
    styles = {
        "cheap_only": ("#787c83", "X", "Cheap-only · unverified diagnostic"),
        "full_rerank": ("#222831", "s", "Full reference rerank"),
        "fixed_top_k": ("#2176ae", "o", "Fixed top-k"),
        "adaptive": ("#b44d20", "D", "Adaptive cheap-gap rule"),
    }
    with plt.rc_context({
        "font.size": 10, "axes.titlesize": 12, "axes.labelsize": 11,
        "figure.facecolor": "white", "axes.spines.top": False,
        "axes.spines.right": False, "savefig.facecolor": "white",
    }):
        figure, axes = plt.subplots(1, 2, figsize=(11.5, 4.9))
        for category, group in grouped.items():
            group.sort(key=lambda row: float(row["mean_calls"]))
            color, marker, label = styles.get(category, ("#7457a4", "o", category))
            x = np.asarray([float(row["mean_calls"]) for row in group])
            risk = np.asarray([1.0 - float(row["success_rate"]) for row in group])
            tail = np.asarray([float(row["p95_regret_kcal"]) for row in group])
            linestyle = "-" if len(group) > 1 and category == "fixed_top_k" else "none"
            axes[0].plot(x, risk * 100, color=color, marker=marker, linestyle=linestyle, label=label, markersize=7)
            axes[1].plot(x, tail, color=color, marker=marker, linestyle=linestyle, label=label, markersize=7)
            for row, xvalue, riskvalue, tailvalue in zip(group, x, risk, tail):
                if row.get("success_rate_ci_low") is not None and row.get("success_rate_ci_high") is not None:
                    low = 1.0 - float(row["success_rate_ci_high"])
                    high = 1.0 - float(row["success_rate_ci_low"])
                    axes[0].vlines(xvalue, 100 * low, 100 * high, color=color, alpha=0.45, linewidth=1.5)
                if row.get("mean_calls_ci_low") is not None and row.get("mean_calls_ci_high") is not None:
                    for axis, yvalue in ((axes[0], riskvalue * 100), (axes[1], tailvalue)):
                        axis.hlines(yvalue, row["mean_calls_ci_low"], row["mean_calls_ci_high"], color=color, alpha=0.45, linewidth=1.5)
                if row.get("p95_regret_kcal_ci_low") is not None and row.get("p95_regret_kcal_ci_high") is not None:
                    axes[1].vlines(xvalue, row["p95_regret_kcal_ci_low"], row["p95_regret_kcal_ci_high"], color=color, alpha=0.45, linewidth=1.5)
        axes[0].axhline(5.0, color="#a33c3c", linewidth=1, linestyle="--", label="Target: ≤5% above 1 kcal/mol")
        axes[1].axhline(1.0, color="#a33c3c", linewidth=1, linestyle="--")
        axes[0].set_title("Failure risk")
        axes[1].set_title("Tail of reference regret")
        axes[0].set_ylabel("Molecules above 1 kcal/mol regret (%)")
        axes[1].set_ylabel("95th percentile regret (kcal/mol)")
        for axis in axes:
            axis.set_xlabel("Mean expensive calls per molecule")
            axis.grid(axis="both", alpha=0.15)
            axis.set_xlim(left=-0.15)
            axis.set_ylim(bottom=-0.02 if axis is axes[1] else -0.5)
        handles, labels = axes[0].get_legend_handles_labels()
        figure.legend(handles, labels, loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, -0.005))
        figure.suptitle(f"{title}\nHeld-out chemical families: {heldout_families}", y=0.99, fontsize=13)
        figure.text(
            0.5, 0.135,
            "Intervals: 95% family-cluster bootstrap. Offline call counts are not wall-clock savings.",
            ha="center", fontsize=9, color="#4f5661",
        )
        figure.tight_layout(rect=(0, 0.18, 1, 0.90))
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, dpi=180, bbox_inches="tight")
        plt.close(figure)
    return str(output_path)
