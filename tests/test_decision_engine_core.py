"""Meaningful contract tests for units, visibility, budgets, ties and failures."""
import math
import unittest

from erkidu_decision.core import Oracle, gaussian_ei, normalize_payload, run_policy

PROTOCOL = "pbe-relax-v1"


def candidates():
    return [
        {"candidate_id": "a", "mean_eV_atom": -1.0, "sigma_eV_atom": .1,
         "disagreement_eV_atom": .02, "support_distance": .1, "descriptor": [0., 0.]},
        {"candidate_id": "b", "mean_eV_atom": -.98, "sigma_eV_atom": .1,
         "disagreement_eV_atom": .05, "support_distance": .2, "descriptor": [.1, 0.]},
        {"candidate_id": "c", "mean_eV_atom": 10., "sigma_eV_atom": .3,
         "disagreement_eV_atom": .8, "support_distance": .3, "descriptor": [10., 0.]},
    ]


def payload(policy="fixed_top", budget=2, **kwargs):
    return dict(policy=policy, budget=budget, seed=37, candidates=candidates(),
                protocol_id=PROTOCOL, energy_unit="eV/atom", **kwargs)


def oracle(refs=None):
    return Oracle(["a", "b", "c"], refs or {"a": -1., "b": -1.2, "c": 9.}, PROTOCOL)


class CoreOracleTests(unittest.TestCase):
    def test_explicit_unit_and_protocol_validation(self):
        with self.assertRaises(ValueError):
            Oracle(["a"], {"a": 1}, PROTOCOL, unit="eV")
        with self.assertRaises(ValueError):
            Oracle(["a"], {"a": 1}, PROTOCOL, reference_protocol="different-functional")
        with self.assertRaises(ValueError):
            run_policy({**payload(), "energy_unit": "kcal/mol"}, oracle())
        with self.assertRaises(ValueError):
            run_policy({**payload(), "protocol_id": "other"}, oracle())

    def test_repeat_success_and_failure_are_cached_without_recharge(self):
        o = oracle({"a": -1., "b": None, "c": float("nan")})
        self.assertEqual(o.query("a")["energy_eV_atom"], -1.)
        self.assertTrue(o.query("a")["cached"])
        self.assertEqual(o.query("b")["error"], "missing_reference")
        self.assertEqual(o.query("b")["status"], "cached_failure")
        self.assertEqual(o.query("c")["error"], "nonfinite_reference")
        self.assertEqual(o.charged_calls, 3)
        self.assertEqual(o.observations, {"a": -1.})

    def test_invalid_and_unsupported_forces_do_not_fake_results(self):
        o = oracle()
        for response in [o.query("z"), o.query("a", "forces"),
                         o.query("a", protocol_id="other"), o.query("a", energy_unit="hartree")]:
            self.assertFalse(response["ok"])
            self.assertEqual(response["charged"], 0)
            self.assertNotIn("energy_eV_atom", response)
        self.assertEqual(o.events[1]["status"], "unsupported")
        self.assertEqual(o.charged_calls, 0)
        self.assertEqual(o.query("a")["charged"], 1)

    def test_absolute_value_not_hidden_min_normalized(self):
        o = oracle({"a": -101., "b": -104., "c": -98.})
        self.assertEqual(o.query("a")["energy_eV_atom"], -101.)
        self.assertEqual(o.observations, {"a": -101.})

    def test_mutating_returned_data_cannot_change_oracle(self):
        o = oracle()
        result = o.query("a")
        result["energy_eV_atom"] = -999.
        events = o.events
        events[0]["charged"] = 0
        self.assertEqual(o.query("a")["energy_eV_atom"], -1.)
        self.assertEqual(o.charged_calls, 1)


class CorePolicyTests(unittest.TestCase):
    def run_one(self, policy="fixed_top", budget=2, refs=None, **kwargs):
        return run_policy(payload(policy, budget, **kwargs), oracle(refs), isolated=False)

    def test_paid_selection_uses_only_successful_queried_labels(self):
        result = self.run_one(refs={"a": -1., "b": -1.2, "c": -100.})
        self.assertEqual(result["selected_id"], "b")
        self.assertEqual(result["charged_calls"], 2)
        self.assertNotIn("c", result["observations"])

    def test_each_fixed_arm_exact_attempt_budget_and_finite_pool(self):
        for name in ["fixed_top", "random", "diversity", "uncertainty", "disagreement", "decision_aware"]:
            with self.subTest(policy=name):
                r = self.run_one(name, 2, refs={"a": -1., "b": None, "c": 9.})
                self.assertEqual(r["charged_calls"], 2)
                self.assertEqual(len({q["candidate_id"] for q in r["queries"]}), 2)
                self.assertEqual(self.run_one(name, 9)["charged_calls"], 3)

    def test_frozen_and_full_reference_endpoints(self):
        mlip = self.run_one("mlip_only", 0)
        full = self.run_one("full_ref", 0)
        self.assertEqual((mlip["selected_id"], mlip["charged_calls"]), ("a", 0))
        self.assertEqual((full["selected_id"], full["charged_calls"]), ("b", 3))
        self.assertTrue(full["certified"])
        self.assertFalse(mlip["certified"])

    def test_deterministic_ties(self):
        p = payload("fixed_top", 2)
        p["candidates"] = list(reversed(p["candidates"]))
        p["candidates"][1]["mean_eV_atom"] = -1.
        r = run_policy(p, oracle({"a": -1., "b": -1., "c": 5.}), isolated=False)
        self.assertEqual([q["candidate_id"] for q in r["queries"]], ["a", "b"])
        self.assertEqual(r["selected_id"], "a")

    def test_no_hidden_reference_fields_allowed(self):
        p = payload()
        p["candidates"][0]["reference_energy"] = -7.
        with self.assertRaises(ValueError):
            normalize_payload(p)
        p = payload()
        p["reference_min"] = -100.
        with self.assertRaises(ValueError):
            normalize_payload(p)

    def test_hidden_unqueried_values_cannot_change_first_two_decisions(self):
        r1 = self.run_one("decision_aware", 2, refs={"a": -1., "b": -1.2, "c": -100.})
        r2 = self.run_one("decision_aware", 2, refs={"a": -1., "b": 100., "c": 10000.})
        q1 = [q["candidate_id"] for q in r1["queries"]]
        q2 = [q["candidate_id"] for q in r2["queries"]]
        self.assertEqual(q1, ["a", "b"])
        self.assertEqual(q1, q2)
        self.assertEqual(r1["queries"][0]["pre_query"]["available_observations"], [])
        self.assertEqual(r1["queries"][1]["pre_query"]["available_observations"],
                         [{"candidate_id": "a", "energy_eV_atom": -1.}])

    def test_decision_aware_avoids_high_uncertainty_hopeless_candidate(self):
        ei = self.run_one("decision_aware")
        uncertainty = self.run_one("uncertainty")
        self.assertEqual(ei["queries"][1]["candidate_id"], "b")
        self.assertEqual(uncertainty["queries"][1]["candidate_id"], "c")

    def test_ei_formula_zero_and_positive_variance(self):
        self.assertEqual(gaussian_ei(0., -1., 0.), 1.)
        self.assertEqual(gaussian_ei(0., 1., 0.), 0.)
        self.assertAlmostEqual(gaussian_ei(0., 0., 1.), 1 / math.sqrt(2*math.pi))

    def test_missing_reference_charged_and_not_silently_dropped(self):
        r = self.run_one(refs={"a": None, "b": -1., "c": 9.})
        self.assertEqual(r["charged_calls"], 2)
        self.assertEqual(r["status"], "incomplete_reference")
        self.assertEqual(r["selected_id"], "b")
        all_fail = self.run_one(refs={"a": None, "b": None, "c": None})
        self.assertEqual(all_fail["status"], "abstained")
        self.assertIsNone(all_fail["selected_id"])

    def test_infinite_interval_falls_back_to_full_pool(self):
        r = self.run_one("calibrated_interval", 3, interval_q=None)
        self.assertEqual(r["charged_calls"], 3)
        self.assertTrue(r["fallback"])
        self.assertEqual(r["reason"], "full_reference_complete")

    def test_interval_stop_certificate_and_anchor_offset(self):
        p = payload("calibrated_interval", 3, interval_q=.1, tolerance_eV_atom=.05)
        p["candidates"][1]["mean_eV_atom"] = -.8
        r = run_policy(p, oracle({"a": 9., "b": 10., "c": 20.}), isolated=False)
        self.assertEqual(r["charged_calls"], 1)
        self.assertTrue(r["certified"])
        check = next(e for e in r["decision_events"] if e["event"] == "interval_check")
        self.assertEqual(check["anchor_offset_eV_atom"], 10.)
        self.assertAlmostEqual(check["lower_bounds_eV_atom"]["b"], 9.19)
        self.assertLess(check["signed_unqueried_margin_eV_atom"], 0.)
        self.assertEqual(check["regret_upper_bound_eV_atom"], 0.)

    def test_interval_can_certify_at_the_exact_budget_boundary(self):
        p = payload("calibrated_interval", 1, interval_q=0., tolerance_eV_atom=.05)
        r = run_policy(p, oracle(), isolated=False)
        self.assertEqual(r["charged_calls"], 1)
        self.assertTrue(r["certified"])
        self.assertEqual(r["selected_id"], "a")
        self.assertEqual(r["status"], "ok")

    def test_interval_budget_or_reference_failure_abstains(self):
        r = self.run_one("calibrated_interval", 2, interval_q=None)
        self.assertEqual(r["status"], "abstained")
        self.assertIsNone(r["selected_id"])
        self.assertEqual(r["provisional_selected_id"], "b")
        f = self.run_one("calibrated_interval", 3, refs={"a": None, "b": -1., "c": 9.}, interval_q=.1)
        self.assertEqual(f["status"], "abstained")
        self.assertEqual(f["charged_calls"], 3)

    def test_out_of_support_fallback_frequency_is_observable(self):
        r = self.run_one("calibrated_interval", 3, interval_q=0., ood_cutoff=.2)
        self.assertEqual(r["charged_calls"], 3)
        self.assertTrue(r["fallback"])
        self.assertTrue(any(e.get("reason") == "outside_support_full_pool" for e in r["decision_events"]))

    def test_seeded_random_is_reproducible(self):
        self.assertEqual(self.run_one("random"), self.run_one("random"))

    def test_isolated_boundary_matches_reference_kernel(self):
        p = payload("decision_aware", 2)
        isolated = run_policy(p, oracle())
        direct = run_policy(p, oracle(), isolated=False)
        self.assertIn("isolated_interpreter", isolated.pop("visibility_boundary"))
        self.assertEqual(isolated, direct)

    def test_fresh_oracle_required_prevents_cost_reuse(self):
        o = oracle()
        o.query("a")
        with self.assertRaises(ValueError):
            run_policy(payload(), o)


if __name__ == "__main__":
    unittest.main()
