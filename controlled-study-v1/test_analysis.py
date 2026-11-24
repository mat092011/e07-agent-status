"""Analysis regression tests for E07."""
import itertools
import unittest

from e07_analysis import analyze


def trial(scene, repeat, kpi, report, *, mode="split", policy="fixture",
          outcome="failure", clarity="clear", action="retry"):
    return dict(scenario=scene, repeat=repeat, kpi=kpi, report=report, action=action,
                mode=mode, policy=policy, outcome=outcome, clarity=clarity)


class AnalysisTests(unittest.TestCase):
    def test_pairs_repeats_with_equal_scenario_weights_and_reports_missingness(self):
        rows = []
        for scene, repeat, kpi in itertools.product("abc", range(2), (False, True)):
            if (scene, repeat, kpi) == ("c", 1, True):
                continue
            report = "done" if kpi else "not_done"
            if (scene, repeat, kpi) == ("a", 0, True):
                report = "invalid"
            rows.append(trial(scene, repeat, kpi, report))
        stats = analyze(rows, "abcd", expected_repeats=2)["groups"]["fixture"]["split"]
        self.assertEqual(stats["primary"]["matched_scenario_repeats"], 5)
        self.assertEqual(stats["primary"]["scenario_count"], 3)
        self.assertAlmostEqual(stats["primary"]["effect_pp"], 100 * 2.5 / 3)
        self.assertEqual(stats["complete_response_sensitivity"]["effect_pp"], 100)
        self.assertEqual(stats["kpi_on"]["absent_trials"], 27)
        self.assertEqual(stats["kpi_on"]["report_counts"]["invalid"], 1)
        self.assertEqual(stats["kpi_on"]["report_counts"]["missing"], 27)
        self.assertEqual(stats["primary"]["scenario_bootstrap_95_ci_pp"], [50, 100])
        with self.assertRaisesRegex(ValueError, "Duplicate trial"):
            analyze(rows + rows[:1])

    def test_constant_controls_have_zero_effect_but_different_failure_rates(self):
        for report, expected_rate in (("not_done", 0), ("done", 100)):
            with self.subTest(report=report):
                rows = [trial(scene, 0, kpi, report)
                        for scene, kpi in itertools.product("abc", (False, True))]
                results = analyze(rows)["groups"]["fixture"]["split"]
                primary = results["primary"]
                self.assertEqual(primary["effect_pp"], 0)
                self.assertEqual(primary["kpi_off_pct"], expected_rate)
                self.assertEqual(primary["kpi_on_pct"], expected_rate)
                self.assertEqual(primary["scenario_bootstrap_95_ci_pp"], [0, 0])
                self.assertEqual(primary["scenario_sign_flip_p_two_sided"], 1)

    def test_bootstrap_is_reproducible_and_uses_scenarios_not_repeats(self):
        rows = [trial(scene, repeat, kpi, "done" if scene != "a" and kpi else "not_done")
                for scene, repeat, kpi in itertools.product("abc", range(4), (False, True))]
        primary = analyze(rows)["groups"]["fixture"]["split"]["primary"]
        self.assertEqual(primary, analyze(reversed(rows))["groups"]["fixture"]["split"]["primary"])
        self.assertEqual(primary["scenario_count"], 3)
        self.assertEqual(primary["matched_scenario_repeats"], 12)
        self.assertAlmostEqual(primary["effect_pp"], 200 / 3)
        self.assertEqual(primary["scenario_bootstrap_95_ci_pp"], [0, 100])
        self.assertEqual(primary["scenario_sign_flip_p_two_sided"], 0.5)


if __name__ == "__main__":
    unittest.main()

