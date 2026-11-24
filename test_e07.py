import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout

import e07
from e07_analysis import analyze

class Tests(unittest.TestCase):
    def cell(self, mode="split",kpi=True,clarity="clear",outcome="failure"):
        return e07.CONF["scenarios"][0],outcome,clarity,kpi,mode,"kpi_reports_only",0

    def test_ambiguous_truth_hidden_in_all_requests(self):
        for s in e07.CONF["scenarios"]:
            for mode in e07.MODES:
                for k in [False,True]:
                    rows = [e07.trial((s,x,"ambiguous",k,mode,"evidence_correct",0),
                                      e07.Control("evidence_correct")) for x in ["success","failure"]]
                    self.assertEqual(rows[0]["branches"],rows[1]["branches"])
                    self.assertNotEqual(rows[0]["executed"]["observed"],rows[1]["executed"]["observed"])

    def test_split_no_branch_leakage_even_when_adapter_mutates_inputs(self):
        seen=[]
        class Probe:
            def complete(self,ms):
                seen.append(json.loads(json.dumps(ms)))
                ms[0]["content"]="SECRET_PRIOR_MUTATION"
                return '{"action":"retry"}' if ms[-1]["content"]==e07.P["action"] else '{"status":"done"}'
        row=e07.trial(self.cell(),Probe())
        self.assertEqual(len(seen),2)
        self.assertEqual(seen[0][:-1],seen[1][:-1])
        self.assertEqual(len(seen[1]),3)
        self.assertFalse(any("SECRET_PRIOR_MUTATION" in str(m) for m in seen))
        self.assertEqual(row["executed"]["after_ready"],True)

    def test_commit_action_first_no_execution_result(self):
        row=e07.trial(self.cell(mode="committed"),e07.Control("kpi_reports_only"))
        self.assertEqual(list(row["branches"]),["action","report"])
        a,r=(row["branches"][p] for p in ("action","report"))
        self.assertEqual(r["request"][:-2],a["request"])
        self.assertEqual(r["request"][-2],{"role":"assistant","content":a["raw"]})
        self.assertNotIn("retry_succeeded",str(r["request"]))
        self.assertEqual([row["outcome"],row["report"],row["action"]],["failure","done","retry"])

    def test_retry_after_success_costs_work(self):
        self.assertGreater(e07.execute("retry","success")["cost_units"],e07.execute("close","success")["cost_units"])

    def test_handoff_requires_ready_target(self):
        for truth, delivered in [("failure",False),("success",True)]:
            result=e07.execute("close", truth)
            self.assertEqual(result["delivered"], delivered)
            self.assertEqual(result["observed"], "handoff_accepted" if delivered else "handoff_blocked")
            self.assertEqual(result["after_ready"], result["before_ready"])

    def test_resume_after_interrupt_between_branches(self):
        from unittest.mock import patch
        original=e07.Control.complete
        count=0
        def interrupt(client, messages):
            nonlocal count
            count+=1
            if count==8:
                raise KeyboardInterrupt
            return original(client, messages)
        with tempfile.TemporaryDirectory() as t, redirect_stdout(io.StringIO()) as out:
            argv=["pilot","--out",t,"--policy","kpi_reports_only","--mode","committed"]
            with patch.object(e07.Control,"complete",interrupt), self.assertRaises(KeyboardInterrupt):
                e07.main(argv)
            self.assertFalse((Path(t)/"trials.jsonl").exists())
            e07.main(argv)
            result=json.loads(out.getvalue().splitlines()[-1])
            self.assertEqual((result["cached_completions"], result["new_completions"]), (7,185))

    def test_invalid_commit_and_unknown_remain_distinct(self):
        class Bad:
            def complete(self,_): return '{"action":"delete"}'
        row=e07.trial(self.cell(mode="committed"),Bad())
        self.assertEqual((row["report"],row["action"]),("missing","invalid"))
        self.assertFalse(row["executed"]["performed"])
        for raw,val in [(None,"missing"),("","missing"),("not json","invalid"),
                        ('{"status":"done","status":"done"}',"invalid"),('{"status":"unknown"}',"unknown")]:
            self.assertEqual(e07.parse(raw,"report"),val)

    def test_recover_controls(self):
        cells=e07.make_cells(["split"],e07.POLICIES,1,31)
        rows=[e07.trial(c,e07.Control(c[5])) for c in cells]
        for p,off,on in [("evidence_correct",0,0),("always_success",100,100),("kpi_reports_only",0,100)]:
            pair=analyze(r for r in rows if r["policy"]==p)["groups"][p]["split"]
            self.assertEqual((pair["primary"]["kpi_off_pct"],pair["primary"]["kpi_on_pct"]),(off,on))
            self.assertEqual(pair["primary"]["effect_pp"],on-off)
            self.assertEqual(pair["primary"]["matched_scenario_repeats"],12)
            self.assertEqual(pair["kpi_on"]["actionable_accuracy_pct"],100)

    def test_cli_pilot_resume_and_reanalysis(self):
        with tempfile.TemporaryDirectory() as t, redirect_stdout(io.StringIO()) as capture:
            root=Path(t)
            argv=["pilot","--out",t,"--policy","kpi_reports_only"]
            e07.main(argv)
            a=json.loads(capture.getvalue().splitlines()[-1])
            self.assertEqual([a["trials"],a["new_completions"]],[96,192])
            before=(root/"trials.jsonl").read_bytes()
            e07.main(argv)
            b=json.loads(capture.getvalue().splitlines()[-1])
            self.assertEqual([b["cached_completions"],b["new_completions"]],[192,0])
            self.assertEqual(before,(root/"trials.jsonl").read_bytes())
            e07.main(["analyze",str(root/"trials.jsonl"),"--out",str(root/"again.json")])
            self.assertEqual((root/"analysis.json").read_bytes(),(root/"again.json").read_bytes())
            with self.assertRaisesRegex(ValueError,"manifest mismatch"): e07.main([*argv,"--seed","0"])

    def test_default_demo_and_pilot_need_no_endpoint(self):
        from unittest.mock import patch
        with patch("endpoint.Endpoint",side_effect=AssertionError("unexpected endpoint")):
            with redirect_stdout(io.StringIO()) as out: e07.main(["demo"])
            self.assertEqual(json.loads(out.getvalue())["report"],"done")
            with self.assertRaisesRegex(ValueError,"endpoint requires"): e07.main(["pilot","--policy","endpoint"])

if __name__=="__main__": unittest.main()
