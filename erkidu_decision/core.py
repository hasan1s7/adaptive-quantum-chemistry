"""Label-blind acquisition policies for compatible-composition relaxed-energy replay.

All energies are eV/atom under one declared reference protocol. A query reveals
one historical relaxation energy, not a newly run single-point DFT calculation.
The default worker runs in a separate interpreter and receives public fields and
queried observations only. This is an accidental-leakage boundary for trusted
policies, not an operating-system security sandbox.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import random
import selectors
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping

ENERGY_UNIT = "eV/atom"
INTERFACE_VERSION = "erkidu-relaxed-energy-decision-v1"
_POLICIES = frozenset({"mlip_only", "full_ref", "fixed_top", "random", "diversity",
                      "uncertainty", "disagreement", "decision_aware",
                      "calibrated_interval", "gap_threshold"})
_CANDIDATE_KEYS = frozenset({"candidate_id", "mean_eV_atom", "sigma_eV_atom",
                           "disagreement_eV_atom", "support_distance", "descriptor"})
_PAYLOAD_KEYS = frozenset({"policy", "budget", "seed", "tolerance_eV_atom",
                         "interval_q", "ood_cutoff", "candidates", "group_id",
                         "pool_id", "protocol_id", "energy_unit", "gap_threshold_eV_atom"})


def _number(value, name, *, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _optional_bound(value, name):
    """JSON null is the canonical positive-infinity sentinel for bounds."""
    if value is None or value == float("inf"):
        return None
    return _number(value, name, minimum=0)


def normalize_payload(payload):
    """Copy an explicit public whitelist; hidden-reference fields are rejected."""
    if not isinstance(payload, dict) or set(payload) - _PAYLOAD_KEYS:
        raise ValueError("unknown or nonpublic policy payload field")
    policy = payload.get("policy")
    if policy not in _POLICIES:
        raise ValueError("unsupported policy")
    unit = payload.get("energy_unit", ENERGY_UNIT)
    if unit != ENERGY_UNIT:
        raise ValueError("energy unit must be eV/atom; convert before constructing payload")
    raw = payload.get("candidates")
    if not isinstance(raw, list) or not raw:
        raise ValueError("candidate pool must be a nonempty list")
    candidates = []
    lengths = set()
    for row in raw:
        if not isinstance(row, dict) or set(row) - _CANDIDATE_KEYS:
            raise ValueError("unknown or nonpublic candidate field")
        cid = row.get("candidate_id")
        if not isinstance(cid, str) or not cid:
            raise ValueError("candidate_id must be a nonempty string")
        descriptor = row.get("descriptor", [])
        if not isinstance(descriptor, (tuple, list)):
            raise ValueError("descriptor must be a numeric sequence")
        descriptor = [_number(x, "descriptor") for x in descriptor]
        lengths.add(len(descriptor))
        candidates.append({
            "candidate_id": cid,
            "mean_eV_atom": _number(row.get("mean_eV_atom"), "mean_eV_atom"),
            "sigma_eV_atom": _number(row.get("sigma_eV_atom", 0), "sigma_eV_atom", minimum=0),
            "disagreement_eV_atom": _number(row.get("disagreement_eV_atom", 0), "disagreement_eV_atom", minimum=0),
            "support_distance": _number(row.get("support_distance", 0), "support_distance", minimum=0),
            "descriptor": descriptor,
        })
    if len({r["candidate_id"] for r in candidates}) != len(candidates):
        raise ValueError("duplicate candidate IDs")
    if len(lengths) != 1:
        raise ValueError("descriptor dimensions disagree")
    if policy == "diversity" and lengths == {0}:
        raise ValueError("diversity policy requires a public descriptor")
    means = [r["mean_eV_atom"] for r in candidates]
    if not math.isfinite(max(means) - min(means)):
        raise ValueError("energy span overflows")
    budget = payload.get("budget", len(candidates))
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        raise ValueError("budget must be a nonnegative integer")
    seed = payload.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    result = {
        "policy": policy, "budget": budget, "seed": seed,
        "candidates": sorted(candidates, key=lambda row: row["candidate_id"]),
        "energy_unit": ENERGY_UNIT,
        "tolerance_eV_atom": _number(payload.get("tolerance_eV_atom", 0.05), "tolerance_eV_atom", minimum=0),
        "interval_q": _optional_bound(payload.get("interval_q"), "interval_q"),
        "ood_cutoff": _optional_bound(payload.get("ood_cutoff"), "ood_cutoff"),
        "gap_threshold_eV_atom": _number(payload.get("gap_threshold_eV_atom", 0.1), "gap_threshold_eV_atom", minimum=0),
    }
    for key in ("group_id", "pool_id", "protocol_id"):
        if key in payload:
            if not isinstance(payload[key], str) or not payload[key]:
                raise ValueError(f"{key} must be a nonempty string")
            result[key] = payload[key]
    return result


class Oracle:
    """Parent-only labels, charged once per valid energy request including failure.

    References map candidate IDs to compatible absolute energies in eV/atom.
    None/missing/nonfinite entries are failed jobs, not free exclusions. Repeats
    replay cached successes or failures for free. Unsupported force requests and
    invalid IDs/protocols/units are rejected before a reference job is attempted.
    """
    def __init__(self, candidate_ids, references: Mapping[str, float | None], expected_protocol,
                 reference_protocol=None, unit=ENERGY_UNIT):
        ids = list(candidate_ids)
        if not ids or any(not isinstance(x, str) or not x for x in ids):
            raise ValueError("candidate IDs must be nonempty strings")
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate candidate IDs")
        if set(references) - set(ids):
            raise ValueError("reference IDs outside candidate pool")
        if not isinstance(expected_protocol, str) or not expected_protocol:
            raise ValueError("expected_protocol must be explicit")
        if reference_protocol is not None and reference_protocol != expected_protocol:
            raise ValueError("reference protocol mismatch")
        if unit != ENERGY_UNIT:
            raise ValueError("reference energies must be in eV/atom")
        self.expected_protocol = expected_protocol
        self.unit = unit
        self.__ids = frozenset(ids)
        self.__references = dict(references)
        self.__cache = {}
        self.__observations = {}
        self.__events = []

    @property
    def events(self):
        return deepcopy(self.__events)

    @property
    def observations(self):
        return dict(self.__observations)

    @property
    def charged_calls(self):
        return sum(event["charged"] for event in self.__events)

    @property
    def expensive_calls(self):
        return self.charged_calls

    def query(self, candidate_id, kind="energy", *, protocol_id=None, energy_unit=ENERGY_UNIT):
        event = {"order": len(self.__events) + 1,
                 "candidate_id": candidate_id if isinstance(candidate_id, str) else None,
                 "kind": kind, "charged": 0, "cached": False,
                 "energy_unit": ENERGY_UNIT, "protocol_id": self.expected_protocol}
        self.__events.append(event)
        error = None
        if not isinstance(candidate_id, str) or candidate_id not in self.__ids:
            error = "unknown_candidate"
        elif energy_unit != ENERGY_UNIT:
            error = "unit_mismatch"
        elif protocol_id is not None and protocol_id != self.expected_protocol:
            error = "protocol_mismatch"
        elif kind != "energy":
            error = "unsupported_forces" if kind == "forces" else "unsupported_action"
        if error:
            event.update(ok=False, status="unsupported" if error.startswith("unsupported") else "rejected", error=error)
            return deepcopy(event)
        if candidate_id in self.__cache:
            cached = self.__cache[candidate_id]
            event.update(deepcopy(cached), order=event["order"], charged=0, cached=True,
                         status="cached" if cached["ok"] else "cached_failure")
            return deepcopy(event)
        event["charged"] = 1
        value = self.__references.get(candidate_id)
        if value is None:
            error = "missing_reference"
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            error = "invalid_reference"
        elif not math.isfinite(value):
            error = "nonfinite_reference"
        if error:
            event.update(ok=False, status="failed", error=error)
        else:
            event.update(ok=True, status="succeeded", energy_eV_atom=float(value))
            self.__observations[candidate_id] = float(value)
        self.__cache[candidate_id] = deepcopy(event)
        return deepcopy(event)

    def capability(self):
        """A query-only callable; no label enumeration API is exposed."""
        return self.query


ReferenceOracle = Oracle


def gaussian_ei(best, mean, sigma):
    """Expected positive energy improvement under a marginal Gaussian heuristic."""
    if sigma <= 0:
        return max(0.0, best - mean)
    z = (best - mean) / sigma
    cdf = 0.5 * math.erfc(-z / math.sqrt(2.0))
    density = math.exp(-0.5*z*z) / math.sqrt(2.0*math.pi)
    return max(0.0, (best - mean)*cdf + sigma*density)


def _policy_kernel(payload, query):
    """Trusted worker: only public payload and paid response capability enter."""
    p = normalize_payload(payload)
    rows = p["candidates"]
    by_id = {r["candidate_id"]: r for r in rows}
    order = sorted(by_id, key=lambda cid: (by_id[cid]["mean_eV_atom"], cid))
    policy = p["policy"]
    limit = len(rows) if policy == "full_ref" else min(p["budget"], len(rows))
    queried = []
    observed = {}
    events = []
    queries = []
    fallback = False
    reason = "frozen_mlip_minimum" if policy == "mlip_only" else "fixed_attempt_budget_exhausted"
    interval_certified = False
    incomplete = False
    force_full = False
    anchor = None
    random_order = sorted(by_id)
    random.Random(p["seed"]).shuffle(random_order)
    cutoff = p["ood_cutoff"]
    unsupported = cutoff is not None and any(r["support_distance"] > cutoff for r in rows)

    def best_id():
        return min(observed, key=lambda cid: (observed[cid], cid)) if observed else None

    def offset():
        # Fixed first successful anchor. No averaging changes the interval target.
        return observed[anchor] - by_id[anchor]["mean_eV_atom"] if anchor else 0.0

    def available_snapshot(scores=None):
        return {
            "attempted_candidate_ids": list(queried),
            "available_observations": [{"candidate_id": cid, "energy_eV_atom": observed[cid]}
                                       for cid in sorted(observed)],
            "remaining_attempt_budget": limit - len(queried),
            "anchor_id": anchor, "anchor_offset_eV_atom": offset() if anchor else None,
            "energy_unit": ENERGY_UNIT,
            "scores": scores or {},
            "public_predictions": [{key: r[key] for key in ("candidate_id", "mean_eV_atom", "sigma_eV_atom", "disagreement_eV_atom", "support_distance")}
                                   for r in rows],
        }

    if policy == "mlip_only":
        selected = order[0]
        events.append({"event": "stop", "reason": reason, "selected_id": selected, "available_observations": []})
        return {"interface_version": INTERFACE_VERSION, "selected_id": selected, "status": "ok",
                "queries": [], "charged_calls": 0, "fallback": False, "reason": reason,
                "decision_events": events, "observations": {}, "certified": False,
                "query_cost_unit": "historical_reference_relaxation_label_attempt", "energy_unit": ENERGY_UNIT}

    while True:
        remaining = [cid for cid in order if cid not in queried]
        if not remaining:
            break
        scores = {}
        if policy in {"calibrated_interval", "gap_threshold"} and queried and not force_full:
            bid = best_id()
            if incomplete or bid is None or anchor != order[0]:
                force_full, fallback, reason = True, True, "anchor_or_reference_failure_full_pool"
            elif unsupported:
                force_full, fallback, reason = True, True, "outside_support_full_pool"
            elif policy == "calibrated_interval":
                q = p["interval_q"]
                lower = {cid: (by_id[cid]["mean_eV_atom"] + offset() - q*by_id[cid]["sigma_eV_atom"])
                         for cid in remaining} if q is not None else {}
                margin = observed[bid] - min(lower.values()) if lower else None
                # Regret includes the already observed incumbent as a possible minimum.
                # A negative margin proves zero risk on the simultaneous-coverage event;
                # it is not itself a negative upper bound on a nonnegative loss.
                bound = max(0.0, margin) if margin is not None else None
                certificate = bound is not None and bound <= p["tolerance_eV_atom"]
                events.append({"event": "interval_check", **available_snapshot(),
                               "simultaneous_quantile": q, "regret_upper_bound_eV_atom": bound,
                               "signed_unqueried_margin_eV_atom": margin,
                               "certificate": certificate, "lower_bounds_eV_atom": lower})
                if certificate:
                    reason = "frozen_group_interval_certificate"
                    interval_certified = True
                    break
                force_full, fallback, reason = True, True, "interval_not_certified_full_pool"
            else:
                gap = by_id[order[1]]["mean_eV_atom"] - by_id[order[0]]["mean_eV_atom"] if len(order) > 1 else None
                if gap is not None and gap > p["gap_threshold_eV_atom"]:
                    reason = "uncalibrated_energy_gap_stop"
                    break
                force_full, fallback, reason = True, True, "energy_gap_small_full_pool"
            if force_full:
                events.append({"event": "fallback", "reason": reason, **available_snapshot()})

        if len(queried) >= limit:
            break
        if policy == "random":
            cid = next(cid for cid in random_order if cid not in queried)
        elif not queried or force_full or policy in {"fixed_top", "full_ref", "calibrated_interval", "gap_threshold"}:
            cid = remaining[0]
        elif policy == "diversity":
            for candidate in remaining:
                desc = by_id[candidate]["descriptor"]
                scores[candidate] = min(math.dist(desc, by_id[old]["descriptor"]) for old in queried)
            cid = min(remaining, key=lambda key: (-scores[key], key))
        elif policy in {"uncertainty", "disagreement"}:
            key = "sigma_eV_atom" if policy == "uncertainty" else "disagreement_eV_atom"
            scores = {cid: by_id[cid][key] for cid in remaining}
            cid = min(remaining, key=lambda key: (-scores[key], key))
        elif policy == "decision_aware":
            if not observed:
                cid = remaining[0]
            else:
                best = observed[best_id()]
                scores = {cid: gaussian_ei(best, by_id[cid]["mean_eV_atom"] + offset(), by_id[cid]["sigma_eV_atom"])
                          for cid in remaining}
                cid = min(remaining, key=lambda key: (-scores[key], by_id[key]["mean_eV_atom"], key))
        else:  # normalize_payload prevents reaching this branch.
            raise ValueError("unsupported policy")
        pre = {"event": "query_decision", "order": len(queried)+1, "candidate_id": cid,
               "policy": policy, **available_snapshot(scores)}
        events.append(pre)
        response = query(cid, pre)
        if not isinstance(response, dict) or response.get("candidate_id") != cid:
            raise ValueError("oracle returned the wrong candidate")
        if response.get("energy_unit") != ENERGY_UNIT:
            raise ValueError("oracle response unit mismatch")
        if "protocol_id" in p and response.get("protocol_id") != p["protocol_id"]:
            raise ValueError("oracle response protocol mismatch")
        queried.append(cid)
        queries.append({**deepcopy(response), "pre_query": deepcopy(pre)})
        if response.get("ok"):
            observed[cid] = _number(response.get("energy_eV_atom"), "oracle energy")
            if anchor is None:
                anchor = cid
        else:
            incomplete = True
            events.append({"event": "query_failure", "candidate_id": cid, "error": response.get("error", "unspecified_failure"),
                           "charged": response.get("charged", 0)})

    selected = best_id()
    all_succeeded = len(observed) == len(rows)
    if selected is None:
        status = "abstained"
        reason = "no_successful_reference" if queried else "zero_reference_budget"
    elif incomplete:
        status = "incomplete_reference"
    else:
        status = "ok"
    if all_succeeded:
        interval_certified = policy in {"full_ref", "calibrated_interval"}
        if policy in {"full_ref", "calibrated_interval"}:
            reason = "full_reference_complete"
    # Conservative policies must never accept an unfinished escalation.
    provisional = None
    if policy == "calibrated_interval" and not all_succeeded and not interval_certified:
        provisional = selected
        selected = None
        status = "abstained"
        if incomplete:
            reason = "reference_failure_prevents_certificate"
        elif len(queried) == limit:
            reason = "budget_exhausted_before_certificate"
    events.append({"event": "stop", "reason": reason, "selected_id": selected,
                   "provisional_selected_id": provisional, "status": status,
                   "certified": interval_certified, **available_snapshot()})
    return {"interface_version": INTERFACE_VERSION, "selected_id": selected,
            "provisional_selected_id": provisional, "status": status,
            "queries": queries, "charged_calls": sum(q.get("charged", 0) for q in queries),
            "fallback": fallback, "reason": reason, "decision_events": events,
            "observations": dict(observed), "certified": interval_certified,
            "query_cost_unit": "historical_reference_relaxation_label_attempt",
            "energy_unit": ENERGY_UNIT,
            "acquisition_model": "first-anchor-shifted marginal Gaussian EI; model-based heuristic" if policy == "decision_aware" else None}


class PolicyExecutionError(RuntimeError):
    def __init__(self, message, oracle, decision_events=()):
        super().__init__(message)
        self.queries = oracle.events
        self.charged_calls = oracle.charged_calls
        self.decision_events = list(decision_events)


def run_policy(payload, oracle, *, isolated=True, timeout_seconds=30):
    """Run one pool. Subprocess isolation is the default; no unqueried labels cross.

    The explicit in-process option is for small unit tests and instrumentation.
    A new Oracle is required for each run so costs cannot be accidentally reused.
    """
    p = normalize_payload(payload)
    if p.get("protocol_id", oracle.expected_protocol) != oracle.expected_protocol:
        raise ValueError("payload/reference protocol mismatch")
    p["protocol_id"] = oracle.expected_protocol
    if oracle.events:
        raise ValueError("each policy run requires a fresh oracle")
    if not isolated:
        return _policy_kernel(p, lambda cid, pre: oracle.query(cid, protocol_id=p["protocol_id"]))
    events = []
    started = time.monotonic()
    result = None
    with tempfile.TemporaryDirectory(prefix="erkidu-policy-") as cwd:
        process = subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "--worker"],
                                   cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, bufsize=1)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            process.stdin.write(json.dumps(p, allow_nan=False, separators=(",", ":")) + "\n")
            process.stdin.flush()
            while True:
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError("policy worker timed out")
                line = process.stdout.readline(4_000_001)
                if not line or len(line) > 4_000_000:
                    raise ValueError("policy worker ended or exceeded message bound")
                message = json.loads(line)
                if message.get("type") == "query":
                    if set(message) != {"type", "candidate_id", "pre_query"}:
                        raise ValueError("invalid query envelope")
                    if len(events) > len(p["candidates"]):
                        raise ValueError("policy exceeded finite pool query bound")
                    pre = message["pre_query"]
                    if not isinstance(pre, dict) or pre.get("candidate_id") != message["candidate_id"]:
                        raise ValueError("invalid pre-query evidence")
                    events.append(deepcopy(pre))
                    response = oracle.query(message["candidate_id"], protocol_id=p["protocol_id"])
                    process.stdin.write(json.dumps(response, allow_nan=False, separators=(",", ":")) + "\n")
                    process.stdin.flush()
                elif message.get("type") == "done" and set(message) == {"type", "result"}:
                    result = message["result"]
                    break
                else:
                    raise ValueError("invalid worker protocol")
            process.stdin.close()
            process.wait(timeout=max(0.1, timeout_seconds - (time.monotonic() - started)))
            if process.returncode:
                raise ValueError("policy worker exited unsuccessfully")
            if result["charged_calls"] != oracle.charged_calls:
                raise ValueError("worker cost ledger mismatch")
            paid = p["policy"] != "mlip_only"
            selected = result["selected_id"]
            if paid and selected is not None:
                observed = oracle.observations
                expected = min(observed, key=lambda cid: (observed[cid], cid)) if observed else None
                if selected != expected:
                    raise ValueError("paid policy selected an unqueried or suboptimal queried structure")
            if not paid and oracle.charged_calls:
                raise ValueError("frozen MLIP policy made a paid query")
            result["visibility_boundary"] = "isolated_interpreter_jsonl_public_payload_and_queried_responses"
            return result
        except Exception as exc:
            raise PolicyExecutionError(str(exc), oracle, events) from exc
        finally:
            selector.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed:
                    stream.close()


def _worker_main():
    p = json.loads(sys.stdin.readline())
    def query(cid, pre):
        print(json.dumps({"type": "query", "candidate_id": cid, "pre_query": pre}, allow_nan=False), flush=True)
        response = sys.stdin.readline()
        if not response:
            raise EOFError("parent oracle channel closed")
        return json.loads(response)
    result = _policy_kernel(p, query)
    print(json.dumps({"type": "done", "result": result}, allow_nan=False), flush=True)


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("This module is a worker; use the project CLI.")
    _worker_main()
