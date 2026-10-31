"""Tier prices and cache keys.

Prices are read from RunConfig.tier_prices and never defaulted: a tier without a frozen
price cannot be charged, so it cannot be run.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from kiln.schemas import ComputeTier, RunConfig

__all__ = ["MissingPrice", "price", "cache_key"]


class MissingPrice(Exception):
    """RunConfig.tier_prices has no usable price for a tier."""


def price(config: RunConfig, tier: ComputeTier) -> float:
    value = config.tier_prices.get(tier.value)
    if value is None:
        raise MissingPrice(f"no frozen price for tier {tier.value!r} in RunConfig.tier_prices")
    if not math.isfinite(value) or value < 0:
        raise MissingPrice(f"invalid price for tier {tier.value!r}: {value}")
    return float(value)


def cache_key(tier: ComputeTier, inputs: dict[str, Any], settings: dict[str, Any]) -> str:
    """sha256 of canonical JSON of (tier, inputs, settings); independent of dict order."""
    canonical = json.dumps(
        {"tier": tier.value, "inputs": inputs, "settings": settings},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
