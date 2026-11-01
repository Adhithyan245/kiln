"""Alerts to Discord (KILN_ALERT_WEBHOOK), plus a local log that always gets every message.

A webhook failure is logged and never raised. The webhook URL is a secret: it is never logged,
and error text is scrubbed of it.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["Alerter", "Poster", "webhook_poster", "post_json"]

Poster = Callable[[str], None]
_DISCORD_LIMIT = 2000


def post_json(url: str, payload: dict, timeout_s: float = 10.0) -> bytes:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "kiln-night/1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 (URL from env)
        return resp.read()


def webhook_poster(env_var: str = "KILN_ALERT_WEBHOOK") -> Poster | None:
    url = os.environ.get(env_var)
    if not url:
        return None

    def post(content: str) -> None:
        post_json(url, {"content": content[:_DISCORD_LIMIT]})

    return post


class Alerter:
    def __init__(self, log_path: Path, poster: Poster | None, prefix: str = "kiln-night") -> None:
        self.log_path = log_path
        self.poster = poster
        self.prefix = prefix
        self._secret = os.environ.get("KILN_ALERT_WEBHOOK") or None

    def _scrub(self, text: str) -> str:
        return text.replace(self._secret, "<webhook>") if self._secret else text

    def _log(self, line: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def send(self, message: str) -> None:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        text = f"[{self.prefix}] {message}"
        self._log(f"{stamp} {text}")
        if self.poster is None:
            print(text, file=sys.stderr)
            return
        try:
            self.poster(text)
        except Exception as exc:  # never crash the night over an alert
            self._log(f"{stamp} alert delivery failed: {type(exc).__name__}: {self._scrub(str(exc))}")
