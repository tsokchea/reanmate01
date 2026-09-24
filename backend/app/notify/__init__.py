"""OTP and email delivery (server/src/notify).

No SMS or email provider is configured yet, so the mock notifier serves every
code: it prints the code to the console in development and keeps an in-memory
outbox that tests can read back. Adding a real provider means one more module
exposing ``send_sms``/``send_email`` and selecting it in ``_build`` — nothing
upstream changes.
"""

import logging
import threading
import time
from datetime import datetime, timezone

from ..config import config, is_development

log = logging.getLogger("reanmate")

MAX_OUTBOX = 50
BANNER_WIDTH = 44


class MockNotifier:
    name = "mock"

    def __init__(self):
        self._outbox = []
        self._lock = threading.Lock()

    def _record(self, entry):
        with self._lock:
            message = {
                "id": f"mock_{int(time.time() * 1000)}_{len(self._outbox)}",
                "sentAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                **entry,
            }
            self._outbox.insert(0, message)
            del self._outbox[MAX_OUTBOX:]
            return message

    @staticmethod
    def _banner(channel, to, code):
        # Loud on purpose: this is how a developer gets the code during signup.
        def line(text):
            return f"  │ {text.ljust(BANNER_WIDTH)[:BANNER_WIDTH]} │"

        rule = lambda left, right: f"  {left}{'─' * (BANNER_WIDTH + 2)}{right}"  # noqa: E731
        print("\n".join(["", rule("┌", "┐"), line(f"{channel.upper()} to {to}"), line(f"code: {code}"),
                         rule("└", "┘"), ""]), flush=True)

    def send_sms(self, *, to, body, code=None):
        if is_development and code:
            self._banner("sms", to, code)
        return {"ok": True, "providerMessageId": self._record({"channel": "sms", "to": to, "body": body, "code": code})["id"]}

    def send_email(self, *, to, subject, body, code=None):
        if is_development and code:
            self._banner("email", to, code)
        message = self._record({"channel": "email", "to": to, "subject": subject, "body": body, "code": code})
        return {"ok": True, "providerMessageId": message["id"]}

    # Test/dev helpers — not part of the provider contract.
    def outbox(self):
        with self._lock:
            return list(self._outbox)

    def latest_for(self, to):
        return next((m for m in self.outbox() if m["to"] == to), None)

    def clear(self):
        with self._lock:
            self._outbox.clear()


_notifier = None
_warned = False


def _build():
    global _warned
    if not (config.SMS_PROVIDER or config.EMAIL_PROVIDER):
        if not _warned:
            log.warning("[notify] No SMS or email provider configured — using the mock notifier. "
                        "Codes are printed to this console and kept in an in-memory outbox.")
            _warned = True
        return MockNotifier()
    if not _warned:
        log.warning('[notify] Provider "%s" is configured but not implemented yet — using the mock notifier',
                    config.SMS_PROVIDER or config.EMAIL_PROVIDER)
        _warned = True
    return MockNotifier()


def get_notifier():
    global _notifier
    if _notifier is None:
        _notifier = _build()
    return _notifier


def is_mock_notifier():
    return get_notifier().name == "mock"
