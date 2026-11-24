import unittest

from followup.analyze import paired_effect
from followup.study import parse


class FollowupTests(unittest.TestCase):
    def test_only_one_complete_fenced_object_is_accepted(self):
        payload = '{"action":"retry"}'
        for raw in (payload, f"```JSON\r\n{payload}\r\n```", f"```\n{payload}\n```"):
            self.assertEqual(parse(raw, "action"), "retry")
        fenced = f"```json\n{payload}\n```"
        for raw in (f"Answer: {fenced}", fenced+"\nDone", fenced+"\n"+fenced,
                    '```json\n{"action":"retry","action":"close"}\n```',
                    '```json\n{"action":"retry","why":"failed"}\n```',
                    '```python\n{"action":"retry"}\n```', '{"status":"done"}'):
            self.assertEqual(parse(raw, "action"), "invalid")
        self.assertEqual(parse(None, "report"), "missing")

    def test_exact_p_uses_only_discordant_pairs(self):
        pairs = [("retry","inspect")]*6 + [("inspect","inspect")]*6
        effect = paired_effect(pairs)
        self.assertEqual(effect["effect_pp"], -50)
        self.assertEqual((effect["gain"],effect["loss"]), (0,6))
        self.assertEqual(effect["p_two_sided"], 2/64)
        self.assertEqual(paired_effect([("retry","retry")])["p_two_sided"], 1)
