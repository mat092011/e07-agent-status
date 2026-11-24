"""No network: tests replace the transport with an in-process mock."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError
from urllib.request import Request

from endpoint import BudgetLimit, Endpoint, EndpointError, _NoRedirect


class EndpointBudgetTests(unittest.TestCase):
    messages = [{"role": "user", "content": "example"}]
    local = "http://127.0.0.1:8000/v1"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.ledger = self.directory / "ledger.jsonl"
        self.calls = []
        self.config = dict(
            max_calls=2, budget_usd="0.05", input_per_million="3",
            output_per_million="15", ledger_path=self.ledger, api_key="mock-secret",
        )

    def endpoint(self, *, fail_first=False, url=None, **settings):
        outer = self
        class Opener:
            def open(self, request, timeout):
                outer.calls.append(request)
                ledger = settings.get("ledger_path", outer.ledger)
                # The write must be externally visible before transport starts.
                outer.assertEqual(len(ledger.read_text().splitlines()), len(outer.calls) + 1)
                if fail_first and len(outer.calls) == 1:
                    raise URLError("mock-secret should never reach consumers")
                return io.BytesIO(json.dumps({
                    "choices": [{"message": {"content": "done"}}],
                    "usage": {"prompt_tokens": 22, "completion_tokens": 1},
                }).encode())
        result = Endpoint(url or self.local, "unit-model", **(self.config | settings))
        result._opener = Opener()
        return result

    def test_failed_attempt_is_reserved_across_resume_and_redacted(self):
        with self.assertRaises(EndpointError) as context:
            self.endpoint(fail_first=True).complete(self.messages)
        self.assertNotIn("mock-secret", str(context.exception))
        resumed = self.endpoint()
        self.assertEqual(resumed.complete(self.messages), "done")
        with self.assertRaises(BudgetLimit):
            resumed.complete(self.messages)
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn("mock-secret", self.ledger.read_text())

    def test_budget_and_input_limits_block_transport(self):
        for settings in (
            {"budget_usd": "0.000001", "ledger_path": self.directory / "low.jsonl"},
            {"input_cap_tokens": 1025, "ledger_path": self.directory / "oversize.jsonl"},
        ):
            with self.subTest(settings=settings), self.assertRaises(BudgetLimit):
                self.endpoint(**settings).complete(self.messages)
        self.assertEqual(self.calls, [])

    def test_config_mismatch_and_truncated_ledger_fail_closed(self):
        self.endpoint().complete(self.messages)
        with self.assertRaises(BudgetLimit):
            self.endpoint(max_calls=3).complete(self.messages)
        with self.ledger.open("a") as file:
            file.write('{"attempt":')
        with self.assertRaises(BudgetLimit):
            self.endpoint().complete(self.messages)
        self.assertEqual(len(self.calls), 1)

    def test_reservation_price_matches_body_size(self):
        self.endpoint().complete(self.messages)
        line = json.loads(self.ledger.read_text().splitlines()[1])
        self.assertEqual(line["input_bound_tokens"], len(self.calls[0].data) + 1024)
        self.assertGreater(float(line["reserved_usd"]), 0.0)

    def test_unsafe_urls_and_redirects(self):
        for url in (
            "http://localhost/v1", "http://192.168.0.10/v1",
            "https://user:pass@example.com/v1", "https://example.com/v1?key=hi",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.endpoint(url=url)
        self.assertIsNone(_NoRedirect().redirect_request(
            Request(self.endpoint().url), None, 302, "", {}, "https://example.com",
        ))

    def test_zero_rates_only_for_literal_loopback(self):
        for rate in ("input_per_million", "output_per_million"):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                self.endpoint(url="https://example.com/v1", **{rate: 0})
        local = self.endpoint(input_per_million=0, output_per_million=0)
        self.assertEqual(local.complete(self.messages), "done")


if __name__ == "__main__":
    unittest.main()
