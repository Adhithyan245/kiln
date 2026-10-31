"""Compute service: the only way agents get energies (AGENTS.md rule 8).

`client` charges the budget, serves from `cache` or runs a `backends` tier, and logs every
request. Prices come from RunConfig.tier_prices (frozen in the protocol, OPEN-03); none live here.
"""
