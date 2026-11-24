"""Protocol-v2 label-blind worker; import no evaluator, chemistry or data code.

Sequential stopping uses a calibrated cheap-separation gate then a reference-
feedback empirical error envelope. Neither is a certified risk bound. Decision
messages stream before completion so failures retain their history.
"""
import json
import sys

EPSILON = 1e-9
REGRET_TOLERANCE_KCAL = 1.0


def send(value):
    sys.stdout.write(json.dumps(value, allow_nan=False) + "\n")
    sys.stdout.flush()


def run(message):
    candidates = sorted(message["candidates"], key=lambda row: (row["cheap_kcal"], row["candidate_id"]))
    config = message["config"]
    observations, attempted, policy_events = {}, set(), []
    fallback = failure_seen = False

    def event(name, **fields):
        item = {"event": name, "event_order": len(policy_events) + 1, **fields}
        policy_events.append(item)
        send({"type": "event", "event": item})

    def query(row, reason):
        nonlocal failure_seen
        cid = row["candidate_id"]
        if cid in attempted:
            return cid in observations
        event("query_decision", candidate_id=cid, reason=reason, after_attempts=len(attempted), action="query")
        attempted.add(cid)
        send({"type": "query", "candidate_id": cid})
        line = sys.stdin.readline()
        if not line:
            raise RuntimeError("oracle closed before returning an observation")
        response = json.loads(line)
        if response.get("type") != "observation" or response.get("candidate_id") != cid:
            raise RuntimeError("unexpected oracle response")
        if response["ok"]:
            observations[cid] = response["reference_kcal"]
            return True
        failure_seen = True
        event("query_failure", candidate_id=cid, reason=response["error"], after_attempts=len(attempted))
        return False

    def complete(reason):
        nonlocal fallback
        fallback = True
        event("fallback", reason=reason, after_attempts=len(attempted), action="full_rerank")
        for row in candidates:
            query(row, "fallback_" + reason)
        return "full_rerank_fallback_" + reason

    def sequential():
        if not query(candidates[0], "initial_verification"):
            return complete("failed_output")
        if len(candidates) == 1:
            return "all_candidates_queried"
        cheap_first = candidates[0]["cheap_kcal"]
        gap12 = candidates[1]["cheap_kcal"] - cheap_first
        span = candidates[-1]["cheap_kcal"] - cheap_first
        ratio = gap12 / span if span > 0 else 0.0
        separated = (gap12 > 0 and gap12 + EPSILON >= config["one_gap"]
                     and ratio + EPSILON >= config["one_ratio"])
        event("cheap_separation", gap12_kcal=gap12, cheap_span_kcal=span, gap_ratio=ratio,
              one_gap=config["one_gap"], one_ratio=config["one_ratio"], numerical_tolerance=EPSILON,
              after_attempts=len(attempted), action="stop" if separated else "query_next")
        if separated:
            return "sequential_cheap_separation_heuristic"
        if not query(candidates[1], "one_query_gate_not_met"):
            return complete("failed_output")
        count = 2
        ref_first = observations[candidates[0]["candidate_id"]]
        while count < len(candidates):
            discrepancy = max(abs((observations[row["candidate_id"]] - ref_first)
                                  - (row["cheap_kcal"] - cheap_first)) for row in candidates[:count])
            error = config["error_scale"] * discrepancy + config["slack"]
            best = min(observations.values()) - ref_first
            next_cheap = candidates[count]["cheap_kcal"] - cheap_first
            tolerated_lower = next_cheap - error + REGRET_TOLERANCE_KCAL
            if any(value != value or abs(value) == float("inf")
                   for value in (discrepancy, error, best, next_cheap, tolerated_lower)):
                raise ArithmeticError("nonfinite empirical-envelope arithmetic")
            stop = best <= tolerated_lower + EPSILON
            action = "stop" if stop else ("fallback" if count >= config["cap"] else "query_next")
            event("empirical_envelope", max_observed_discrepancy_kcal=discrepancy,
                  envelope_error_kcal=error, best_observed_relative_kcal=best,
                  next_cheap_relative_kcal=next_cheap, tolerated_lower_envelope_kcal=tolerated_lower,
                  regret_tolerance_kcal=REGRET_TOLERANCE_KCAL, numerical_tolerance=EPSILON,
                  after_attempts=len(attempted), action=action)
            if stop:
                return "sequential_empirical_envelope"
            if count >= config["cap"]:
                return complete("empirical_unresolved_at_cap")
            if not query(candidates[count], "empirical_envelope_unresolved"):
                return complete("failed_output")
            count += 1
        return "all_candidates_queried"

    kind = config["kind"]
    if kind == "full":
        for row in candidates:
            query(row, "full_rerank")
        stop_reason = "full_rerank_with_failed_outputs" if failure_seen else "full_rerank_complete"
    elif kind == "sequential":
        stop_reason = sequential()
    else:
        count = min(config["k"], len(candidates))
        for row in candidates[:count]:
            query(row, "initial_k")
        if failure_seen:
            stop_reason = complete("failed_output")
        elif kind == "fixed":
            stop_reason = "fixed_k_complete" if count < len(candidates) else "all_candidates_queried"
        else:
            minimum = candidates[0]["cheap_kcal"]
            stop_reason = "cheap_gap_exceeds_threshold"
            while count < len(candidates):
                next_row = candidates[count]
                gap = next_row["cheap_kcal"] - minimum
                action = ("stop" if gap > config["gap"] else
                          "fallback" if count >= config["cap"] else "query_next")
                event("cheap_window", cheap_gap_kcal=gap, threshold_kcal=config["gap"], cap=config["cap"],
                      after_attempts=len(attempted), action=action)
                if action == "stop":
                    break
                if action == "fallback":
                    stop_reason = complete("crowded_at_cap")
                    break
                event("escalation", candidate_id=next_row["candidate_id"], cheap_gap_kcal=gap)
                count += 1
                if not query(next_row, "cheap_gap_within_threshold"):
                    stop_reason = complete("failed_output")
                    break
            else:
                stop_reason = "all_candidates_queried"

    selected = min(observations, key=lambda cid: (observations[cid], cid)) if observations else None
    if selected is None:
        stop_reason = "no_reference_verified_candidate"
    event("stop", reason=stop_reason, selected_candidate=selected, after_attempts=len(attempted))
    send({"type": "done", "protocol_version": 2, "selected_candidate": selected,
          "fallback": fallback, "stop_reason": stop_reason})


def main():
    for line in sys.stdin:
        message = json.loads(line)
        if message.get("type") != "run":
            raise RuntimeError("expected run message")
        run(message)


if __name__ == "__main__":
    main()
