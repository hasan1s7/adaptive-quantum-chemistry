"""Standalone label-blind policy process; import no evaluator/data modules.

Input contains candidate IDs, cheap energies, and a frozen policy config.
Reference energies arrive exclusively as individual paid-query responses.
"""

import json
import sys


def send(value):
    sys.stdout.write(json.dumps(value, allow_nan=False) + "\n")
    sys.stdout.flush()


def run(message):
    # These are local variables and are discarded after every case.
    candidates = sorted(
        message["candidates"], key=lambda row: (row["cheap_kcal"], row["candidate_id"])
    )
    config = message["config"]
    observations = {}
    attempted = set()
    policy_events = []
    fallback = False
    failure_seen = False

    def query(row):
        nonlocal failure_seen
        cid = row["candidate_id"]
        if cid in attempted:
            return cid in observations
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
        policy_events.append({"event": "query_failure", "candidate_id": cid,
                              "reason": response["error"]})
        return False

    def complete(reason):
        nonlocal fallback
        fallback = True
        policy_events.append({"event": "fallback", "reason": reason,
                              "after_attempts": len(attempted)})
        for row in candidates:
            query(row)
        return "full_rerank_fallback_" + reason

    kind = config["kind"]
    if kind == "full":
        for row in candidates:
            query(row)
        stop_reason = "full_rerank_complete"
        if failure_seen:
            stop_reason = "full_rerank_with_failed_outputs"
    else:
        count = min(config["k"], len(candidates))
        for row in candidates[:count]:
            query(row)
        if failure_seen:
            stop_reason = complete("failed_output")
        elif kind == "fixed":
            stop_reason = "fixed_k_complete" if count < len(candidates) else "all_candidates_queried"
        else:
            minimum = candidates[0]["cheap_kcal"]
            stop_reason = "cheap_gap_exceeds_threshold"
            while count < len(candidates):
                next_row = candidates[count]
                if next_row["cheap_kcal"] - minimum > config["gap"]:
                    break
                if count >= config["cap"]:
                    stop_reason = complete("crowded_at_cap")
                    break
                policy_events.append({"event": "escalation", "candidate_id": next_row["candidate_id"],
                                      "cheap_gap_kcal": next_row["cheap_kcal"] - minimum})
                count += 1
                if not query(next_row):
                    stop_reason = complete("failed_output")
                    break
            else:
                stop_reason = "all_candidates_queried"

    selected = min(observations, key=lambda cid: (observations[cid], cid)) if observations else None
    if selected is None:
        stop_reason = "no_reference_verified_candidate"
    send({"type": "done", "selected_candidate": selected, "fallback": fallback,
          "stop_reason": stop_reason, "policy_events": policy_events})


def main():
    for line in sys.stdin:
        message = json.loads(line)
        if message.get("type") != "run":
            raise RuntimeError("expected run message")
        run(message)


if __name__ == "__main__":
    main()
