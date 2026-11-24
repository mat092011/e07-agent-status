"""Opt-in OpenAI-compatible endpoint; never used by the offline pilot.

This is a local reservation limit, not a provider invoice guarantee. Only use a
provider that honors max_tokens and whose prompt tokenization uses at most one
token per UTF-8 payload byte plus 1024 tokens of framing/hidden overhead, with no
metered tools, fixed per-request charges or additional reasoning tokens beyond
max_tokens. Supply worst-case all-in token rates. No reservations are refunded.
"""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import ipaddress
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler, ProxyHandler, Request, build_opener,
)


class EndpointError(RuntimeError):
    """A redacted endpoint or request error."""


class BudgetLimit(EndpointError):
    """No outbound request was made for this attempt."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@contextmanager
def _locked(path):
    # Lock survives process interleaving but is released by the OS on process exit.
    with path.open("a+b") as lock:
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise BudgetLimit("Ledger busy or lock unavailable; no request sent.") from None
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise BudgetLimit("Ledger busy or lock unavailable; no request sent.") from None
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _decimal(value, name, *, positive=False):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid {name}.") from None
    if not amount.is_finite() or amount < 0 or (positive and amount == 0) or amount > 10**9 or amount.as_tuple().exponent < -12:
        raise ValueError(f"Invalid {name}.")
    return amount


def _positive_integer(value, name):
    if type(value) is not int or not 0 < value <= 10**9:
        raise ValueError(f"{name} must be a positive integer at most one billion.")
    return value


def _url(base_url):
    try:
        if not isinstance(base_url, str) or any(ord(ch) < 33 or ch == "\\" for ch in base_url):
            raise ValueError
        parts = urlsplit(base_url)
        host = parts.hostname
        if (parts.scheme not in {"http", "https"} or not host or
                parts.username is not None or parts.password is not None or
                parts.query or parts.fragment):
            raise ValueError
        _ = parts.port
        if parts.scheme == "http" and not ipaddress.ip_address(host).is_loopback:
            raise ValueError
    except ValueError:
        raise ValueError(
            "Use an HTTPS base URL or an HTTP URL with a literal loopback IP; "
            "credentials, query parameters and fragments are not accepted."
        ) from None
    return base_url.rstrip("/") + "/chat/completions"


class Endpoint:
    """OpenAI-compatible completion adapter with a persistent gross attempt limit."""

    def __init__(self, base_url, model, *, max_calls, budget_usd, input_per_million,
                 output_per_million, ledger_path, max_output_tokens=50,
                 input_cap_tokens=4096, api_key=None):
        self.url = _url(base_url)
        if not isinstance(model, str) or not model.strip() or len(model) > 256:
            raise ValueError("Provide a nonempty model identifier of at most 256 characters.")
        self.model = model
        self.max_calls = _positive_integer(max_calls, "max_calls")
        self.output_cap = _positive_integer(max_output_tokens, "max_output_tokens")
        self.input_cap = _positive_integer(input_cap_tokens, "input_cap_tokens")
        self.budget = _decimal(budget_usd, "budget_usd", positive=True)
        self.input_rate = _decimal(input_per_million, "input_per_million")
        self.output_rate = _decimal(output_per_million, "output_per_million")
        try:
            loopback = ipaddress.ip_address(urlsplit(self.url).hostname).is_loopback
        except ValueError:
            loopback = False
        if not loopback and (self.input_rate == 0 or self.output_rate == 0):
            raise ValueError("Both rates must be positive for a non-loopback endpoint.")
        if api_key is not None and (not isinstance(api_key, str) or not api_key
                                    or any(not 33 <= ord(c) < 127 for c in api_key)):
            raise ValueError("Invalid API credential.")
        self._key = api_key
        self.path = Path(ledger_path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._config = {
            "version": 1,
            "endpoint_model_hash": hashlib.sha256(
                json.dumps([self.url, model], ensure_ascii=True).encode("ascii")
            ).hexdigest(),
            "max_calls": max_calls,
            "budget_usd": format(self.budget.normalize(), "f"),
            "input_per_million": format(self.input_rate.normalize(), "f"),
            "output_per_million": format(self.output_rate.normalize(), "f"),
            "input_cap_tokens": input_cap_tokens,
            "max_output_tokens": max_output_tokens,
        }
        # Ignore configured HTTP proxies. Never follow redirects or retry failures.
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _charge(self, tokens):
        # Upward rounded to picodollars so a long sequence cannot round under.
        return ((tokens * self.input_rate + self.output_cap * self.output_rate)
                / 10**6).quantize(Decimal("0.000000000001"), rounding=ROUND_CEILING)

    def _reserve(self, bound):
        charge = self._charge(bound)
        try:
            with _locked(self.lock_path):
                with self.path.open("a+b") as ledger:
                    ledger.seek(0)
                    line = ledger.readline()
                    if line:
                        if not line.endswith(b"\n") or json.loads(line) != self._config:
                            raise BudgetLimit("Ledger settings differ or header is incomplete.")
                    count = 0
                    total = Decimal(0)
                    for line in ledger:
                        if not line.endswith(b"\n"):
                            raise BudgetLimit("Ledger has an incomplete reservation.")
                        old = json.loads(line)
                        old_bound = old["input_bound_tokens"]
                        count += 1
                        if (type(old_bound) is not int or not 1024 <= old_bound <= self.input_cap
                                or old != {"attempt": count, "input_bound_tokens": old_bound,
                                           "reserved_usd": str(self._charge(old_bound))}):
                            raise BudgetLimit("Ledger has an invalid reservation.")
                        total += self._charge(old_bound)
                    if count >= self.max_calls or total + charge > self.budget:
                        raise BudgetLimit("Attempt cap or reservation budget exhausted.")
                    if count == 0 and ledger.tell() == 0:
                        ledger.write(json.dumps(self._config, sort_keys=True).encode("ascii") + b"\n")
                    reservation = {"attempt": count + 1, "input_bound_tokens": bound,
                                   "reserved_usd": str(charge)}
                    ledger.write(json.dumps(reservation, sort_keys=True).encode("ascii") + b"\n")
                    ledger.flush()
                    os.fsync(ledger.fileno())
        except (OSError, ValueError, TypeError, KeyError) :
            raise BudgetLimit("Ledger cannot be safely read or reserved; no request sent.") from None

    def complete(self, messages):
        if not isinstance(messages, (list, tuple)) or not messages:
            raise ValueError("Provide a nonempty messages list.")
        for message in messages:
            if (not isinstance(message, dict) or set(message) != {"role", "content"}
                    or message["role"] not in ("system", "user", "assistant")
                    or not isinstance(message["content"], str)):
                raise ValueError("Only text system, user and assistant messages are allowed.")
        payload = json.dumps({"model": self.model, "messages": messages,
                              "max_tokens": self.output_cap, "temperature": 0,
                              "stream": False}, ensure_ascii=True).encode("ascii")
        bound = 1024 + len(payload)
        if bound > self.input_cap:
            raise BudgetLimit("Input bound exceeds the configured cap; no request sent.")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._key is not None:
            headers["Authorization"] = "Bearer " + self._key
        req = Request(self.url, data=payload, headers=headers, method="POST")
        self._reserve(bound)
        try:
            with self._opener.open(req, timeout=30) as response:
                body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise EndpointError("Endpoint response too large; attempt remains reserved.")
            data = json.loads(body)
            usage = data.get("usage")
            if isinstance(usage, dict):
                for field, ceiling in (("prompt_tokens", bound),
                                       ("completion_tokens", self.output_cap)):
                    reported = usage.get(field)
                    if reported is not None and (type(reported) is not int
                                                 or not 0 <= reported <= ceiling):
                        raise EndpointError(
                            "Endpoint usage violates the reservation assumptions; "
                            "stop this run and investigate before resuming."
                        )
            result = data["choices"][0]["message"]["content"]
            if not isinstance(result, str):
                raise ValueError
            return result
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise EndpointError(f"Endpoint returned HTTP {status}; attempt remains reserved.") from None
        except (URLError, OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
            raise EndpointError("Endpoint request or response failed; attempt remains reserved.") from None

