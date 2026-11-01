"""Total spend across runs, for the night's hard caps.

Tokens and USD come from runs/<run_id>/cost.json, GPU-seconds from compute_requests.jsonl.
cost.json may hold one Cost object, a mapping of item id to Cost, or a list of Costs (the
runner's exact layout is Adhi's call); all three are summed. Unreadable files count as a
breach-worthy problem, not as zero: they are reported in `errors`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kiln.night.plan import Caps

__all__ = ["Spend", "read_spend", "breach"]

_COST_KEYS = {"tool_calls", "tokens_in", "tokens_out", "compute_units", "gpu_seconds", "usd"}


@dataclass
class Spend:
    tokens: int = 0
    usd: float = 0.0
    gpu_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def gpu_hours(self) -> float:
        return self.gpu_seconds / 3600.0

    def summary(self, caps: Caps) -> str:
        return (f"tokens {self.tokens}/{caps.max_tokens}, usd {self.usd:.2f}/{caps.max_usd}, "
                f"gpu_h {self.gpu_hours:.2f}/{caps.max_gpu_hours}")


def _costs(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and data.keys() & _COST_KEYS:
        return [data]
    if isinstance(data, dict):
        return [c for v in data.values() for c in _costs(v)]
    if isinstance(data, list):
        return [c for v in data for c in _costs(v)]
    return []


def read_spend(runs_dir: str | Path) -> Spend:
    spend = Spend()
    root = Path(runs_dir)
    if not root.exists():
        return spend
    for cost_file in sorted(root.glob("*/cost.json")):
        try:
            for c in _costs(json.loads(cost_file.read_text(encoding="utf-8"))):
                spend.tokens += int(c.get("tokens_in", 0)) + int(c.get("tokens_out", 0))
                spend.usd += float(c.get("usd", 0.0))
        except (OSError, ValueError, TypeError) as exc:
            spend.errors.append(f"{cost_file}: {type(exc).__name__}")
    for log in sorted(root.glob("*/compute_requests.jsonl")):
        try:
            with log.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        spend.gpu_seconds += float(json.loads(line).get("gpu_seconds", 0.0))
        except (OSError, ValueError, TypeError) as exc:
            spend.errors.append(f"{log}: {type(exc).__name__}")
    return spend


def breach(spend: Spend, caps: Caps) -> str | None:
    """The first cap reached, or None. Missing caps never pass silently: they are a breach."""
    if not caps.complete():
        return "caps not set (OPEN-02)"
    if spend.errors:
        return f"spend unreadable: {spend.errors[0]}"
    if spend.tokens >= caps.max_tokens:  # type: ignore[operator]
        return f"token cap reached ({spend.tokens} >= {caps.max_tokens})"
    if spend.usd >= caps.max_usd:  # type: ignore[operator]
        return f"USD cap reached ({spend.usd:.2f} >= {caps.max_usd})"
    if spend.gpu_hours >= caps.max_gpu_hours:  # type: ignore[operator]
        return f"GPU-hour cap reached ({spend.gpu_hours:.2f} >= {caps.max_gpu_hours})"
    return None
