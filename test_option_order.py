import importlib
import unittest

import e07

analysis = importlib.import_module("followup.option-order.analyze")


class OptionOrderTests(unittest.TestCase):
    def test_pure_first_position_and_evidence_policies_have_distinct_signatures(self):
        rows = []
        for job in analysis.study.definition()["jobs"]:
            correct = {"success": {"report":"done", "action":"close"},
                       "failure": {"report":"not_done", "action":"retry"}}[job["truth"]][job["branch"]]
            value = job["options"][0] if job["model"] == "gemma3:1b" else correct
            rows.append({**job, "strict":value, "selected":value, "correct":value == correct,
                         "first":value == job["options"][0], "position":1+job["options"].index(value),
                         "correct_position":1+job["options"].index(correct),
                         "pilot_agreement":value == job["pilot_value"]})
        result = analysis.summarize(rows)
        for branch in e07.ALLOWED:
            first = result["gemma3:1b"][branch]
            evidence = result["gemma3:12b"][branch]
            self.assertEqual((first["first"],first["correct"],first["label_changed"]), (72,24,24))
            self.assertEqual((evidence["first"],evidence["correct"],evidence["label_stable"]), (24,72,24))
