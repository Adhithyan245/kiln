from __future__ import annotations

import types

import pytest

from kiln.agents import base
from kiln.agents.base import LLMUnavailable, llm_call, llm_choose, provider_for
from kiln.budget import Budget, BudgetExceeded
from kiln.schemas import RunConfig


def cfg(model: str = "offline", **limits) -> RunConfig:
    return RunConfig(run_id="t", condition="C4", seed=0, model=model, **limits)


@pytest.mark.parametrize("model, provider", [("offline", "offline"), ("gemini-3.8-flash", "gemini"),
                                             ("claude-sonnet-5-5", "anthropic"), ("gpt-5-mini", "openai"),
                                             ("o4-mini", "openai")])
def test_provider_from_model_name(model: str, provider: str) -> None:
    assert provider_for(model) == provider


def test_unknown_model_is_refused() -> None:
    with pytest.raises(LLMUnavailable):
        provider_for("llama-3")


def test_offline_choice_charges_tokens_and_no_dollars() -> None:
    b = Budget(cfg())
    assert llm_choose(["thermo", "kinetics"], "Which agents run?", b, cfg()) == ["thermo", "kinetics"]
    spent = b.spent
    assert spent.tokens_in > 0 and spent.tokens_out > 0 and spent.usd == 0.0


def test_choice_parser_keeps_only_valid_unique_options() -> None:
    assert base._parse_choice('Sure: ["kinetics", "bogus", "kinetics", "thermo"]', ["thermo", "kinetics"]) == ["kinetics", "thermo"]
    assert base._parse_choice("no json here", ["thermo"]) == []
    assert base._parse_choice('["thermo"', ["thermo"]) == []


def test_missing_key_is_an_error_not_a_silent_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for model in ("gemini-3.8-flash", "gpt-5-mini", "claude-sonnet-5-5"):
        with pytest.raises(LLMUnavailable):
            llm_call("hi", Budget(cfg(model)), cfg(model))


def test_dollars_use_the_price_table_including_thinking_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "_gemini", lambda prompt, system, config: ("ok", 1_000, 2_000))  # 2,000 = reply + thinking
    b = Budget(cfg("gemini-3.8-flash"))
    r = llm_call("hi", b, cfg("gemini-3.8-flash"))
    expected = (1_000 * 0.75 + 2_000 * 3.75) / 1_000_000
    assert r.usd == pytest.approx(expected) and b.spent.usd == pytest.approx(expected)
    assert (b.spent.tokens_in, b.spent.tokens_out) == (1_000, 2_000)


def test_unpriced_model_records_zero_dollars_with_a_note(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "_openai", lambda prompt, system, config: ("ok", 10, 5))
    r = llm_call("hi", Budget(cfg("gpt-4.1-mini")), cfg("gpt-4.1-mini"))
    assert r.usd == 0.0 and "no price" in r.notes


@pytest.mark.parametrize("model, provider, tin, tout, usd", [
    ("claude-haiku-5-5", "_anthropic", 10_000, 1_000, (10_000 * 0.10 + 1_000 * 0.50) / 1e6),
    ("gpt-5-mini", "_openai", 10_000, 1_000, (10_000 * 0.25 + 1_000 * 2.00) / 1e6),
])
def test_secondary_models_are_priced(monkeypatch: pytest.MonkeyPatch, model, provider, tin, tout, usd) -> None:
    monkeypatch.setattr(base, provider, lambda prompt, system, config: ("ok", tin, tout))
    b = Budget(cfg(model))
    assert llm_call("hi", b, cfg(model)).usd == pytest.approx(usd) and b.spent.usd == pytest.approx(usd)


def test_tokens_over_the_cap_are_recorded_then_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "_gemini", lambda prompt, system, config: ("ok", 900, 200))
    c = cfg("gemini-3.8-flash", max_tokens_per_item=1_000)
    b = Budget(c)
    with pytest.raises(BudgetExceeded):
        llm_call("hi", b, c)
    assert b.spent.tokens_in + b.spent.tokens_out == 1_100 and b.spent.usd > 0   # the call happened; it's billed


def test_gemini_counts_thinking_tokens_as_output(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = types.SimpleNamespace(prompt_token_count=12, candidates_token_count=3, thoughts_token_count=40)
    fake = types.SimpleNamespace(text="ok", usage_metadata=usage)

    class Client:
        def __init__(self, api_key: str) -> None:
            self.models = types.SimpleNamespace(generate_content=lambda **kw: fake)

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    monkeypatch.setattr(base, "_GEMINI_CLIENTS", {})
    import google.genai
    monkeypatch.setattr(google.genai, "Client", Client)
    assert base._gemini("hi", "", cfg("gemini-3.8-flash")) == ("ok", 12, 43)
    assert list(base._GEMINI_CLIENTS) == ["test-key"]      # the client is kept for the next call
