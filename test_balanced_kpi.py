import importlib
import unittest

analysis = importlib.import_module("followup.balanced-kpi.analyze")


class BalancedKpiTests(unittest.TestCase):
    def test_opposing_order_effects_cancel_within_each_resampled_scenario(self):
        cells = {}
        for scenario in range(12):
            for arm in ("off","on"):
                for rotation in range(3):
                    done = (rotation,arm) in ((0,"on"),(1,"off"))
                    cells["fixture",scenario,arm,rotation] = {
                        "report":"done" if done else "not_done",
                        "action":"retry" if rotation < 2 else "inspect",
                    }
        balanced = analysis.contrast(cells,"fixture","done_retry",range(3))
        self.assertEqual((balanced["off"], balanced["on"], balanced["n_per_arm"]), (12,12,36))
        self.assertEqual((balanced["gain"], balanced["loss"]), (12,12))
        self.assertEqual(balanced["interval95_pp"], [0,0])
        by_order = [analysis.contrast(cells,"fixture","done_retry",[r])["effect_pp"] for r in range(3)]
        self.assertEqual(by_order, [100,-100,0])
        self.assertEqual(analysis.contrast(cells,"fixture","retry",range(3))["off"], 24)
