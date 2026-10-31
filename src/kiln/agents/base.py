"""Base class every agent subclasses, and the one LLM entry point they all use.

llm_call() picks the provider from RunConfig.model, charges the tokens to the item's
budget and records the dollar cost. The main comparison runs on Gemini; Claude and
OpenAI are only for the secondary results and as backups (AGENTS.md rule 11,
docs/credits.md). Keys come from environment variables, never from files:

    GEMINI_API_KEY      Google account 1 (main experiment)
    GEMINI_API_KEY_2    Google account 2 (fallback and extra throughput)
    ANTHROPIC_API_KEY   Claude replication (secondary)
    OPENAI_API_KEY      N2 probe on OpenAI (secondary)

model="offline" is a deterministic stand-in for tests and dry runs. It is never chosen
automatically: a missing key is an error, not a silent fallback (AGENTS.md rule 9).
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from kiln.board import Board
from kiln.budget import Budget
from kiln.schemas import AgentName, Item, RunConfig

__all__ = ["Agent", "LLMResponse", "LLMUnavailable", "PRICES_USD_PER_MTOK", "llm_call", "llm_choose", "provider_for"]

# Dollar prices per million tokens, (input, output), keyed by exact model id.
# Fill these in from each provider's price page before the main run; a model with no
# entry is logged with usd = 0 and a warning in LLMResponse.notes.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    # "gemini-...": (input, output),
    # "claude-...": (input, output),
    # "gpt-...":    (input, output),
}

MAX_OUTPUT_TOKENS = 1024


class LLMUnavailable(RuntimeError):
    """The provider can't be used: missing key, missing SDK, or the API call failed."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    usd: float
    notes: str = ""


def provider_for(model: str) -> str:
    m = model.lower()
    if m == "offline":
        return "offline"
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    raise LLMUnavailable(f"no provider for model {model!r}; use gemini-*, claude-*, gpt-* or 'offline'")


def llm_call(prompt: str, budget: Budget, config: RunConfig, *, system: str = "") -> LLMResponse:
    """One LLM call at temperature 0 with the run's seed. Tokens are charged even if
    they push the item over its token cap (BudgetExceeded is raised after recording)."""
    provider = provider_for(config.model)
    call = {"offline": _offline, "gemini": _gemini, "anthropic": _anthropic, "openai": _openai}[provider]
    text, tokens_in, tokens_out = call(prompt, system, config)
    usd, notes = _usd(config.model, tokens_in, tokens_out)
    budget.record_usd(usd)
    budget.charge_tokens(tokens_in, tokens_out)
    return LLMResponse(text, provider, config.model, tokens_in, tokens_out, usd, notes)


def llm_choose(options: list[str], context: str, budget: Budget, config: RunConfig, *, system: str = "") -> list[str]:
    """Ask the LLM to pick and order actions from a fixed menu. Returns only valid,
    de-duplicated option names; the LLM never supplies numbers (AGENTS.md rule 7)."""
    prompt = (
        f"{context}\n\nChoose which of these actions to take, in order. "
        f"Reply with only a JSON array of action names from this list: {json.dumps(options)}"
    )
    reply = llm_call(prompt, budget, config, system=system)
    return _parse_choice(reply.text, options)


class Agent(ABC):
    name: AgentName

    @abstractmethod
    def step(self, item: Item, board: Board, budget: Budget) -> None:
        """One coordination round for one item.

        Read what's on the board, answer needs this agent can fulfil, post new needs and
        artifacts, and charge every tool call, token and compute unit to the budget.
        The runner calls step() once per agent per round, up to RunConfig.coordination_rounds.
        """


# ---------- providers ----------

def _offline(prompt: str, system: str, config: RunConfig) -> tuple[str, int, int]:
    """Deterministic stand-in: picks every offered action in the order given."""
    start = prompt.rfind("[")
    options = json.loads(prompt[start:]) if start != -1 and prompt.rstrip().endswith("]") else []
    text = json.dumps(options)
    return text, _rough_tokens(system + prompt), _rough_tokens(text)


def _key(*names: str) -> str:
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    raise LLMUnavailable(f"set {' or '.join(names)} in the environment")


def _gemini(prompt: str, system: str, config: RunConfig) -> tuple[str, int, int]:
    from google import genai
    from google.genai import types

    gen_config = types.GenerateContentConfig(
        temperature=0, seed=config.seed, max_output_tokens=MAX_OUTPUT_TOKENS,
        system_instruction=system or None,
    )
    errors = []
    for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_2"):  # account 2 is the fallback
        if not os.environ.get(name):
            continue
        try:
            r = genai.Client(api_key=os.environ[name]).models.generate_content(
                model=config.model, contents=prompt, config=gen_config)
            usage = r.usage_metadata
            return r.text or "", usage.prompt_token_count or 0, usage.candidates_token_count or 0
        except Exception as exc:  # try the other account, then report both failures
            errors.append(f"{name}: {exc}")
    raise LLMUnavailable("Gemini call failed: " + ("; ".join(errors) or "set GEMINI_API_KEY or GEMINI_API_KEY_2"))


def _anthropic(prompt: str, system: str, config: RunConfig) -> tuple[str, int, int]:
    import anthropic

    try:
        r = anthropic.Anthropic(api_key=_key("ANTHROPIC_API_KEY")).messages.create(
            model=config.model, max_tokens=MAX_OUTPUT_TOKENS, temperature=0,
            system=system or anthropic.NOT_GIVEN, messages=[{"role": "user", "content": prompt}])
    except LLMUnavailable:
        raise
    except Exception as exc:
        raise LLMUnavailable(f"Claude call failed: {exc}") from exc
    text = "".join(block.text for block in r.content if block.type == "text")
    return text, r.usage.input_tokens, r.usage.output_tokens


def _openai(prompt: str, system: str, config: RunConfig) -> tuple[str, int, int]:
    import openai

    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    try:
        r = openai.OpenAI(api_key=_key("OPENAI_API_KEY")).chat.completions.create(
            model=config.model, messages=messages, seed=config.seed, max_completion_tokens=MAX_OUTPUT_TOKENS)
    except LLMUnavailable:
        raise
    except Exception as exc:
        raise LLMUnavailable(f"OpenAI call failed: {exc}") from exc
    return r.choices[0].message.content or "", r.usage.prompt_tokens, r.usage.completion_tokens


# ---------- helpers ----------

def _usd(model: str, tokens_in: int, tokens_out: int) -> tuple[float, str]:
    if model == "offline":
        return 0.0, ""
    if model not in PRICES_USD_PER_MTOK:
        return 0.0, f"no price for {model} in PRICES_USD_PER_MTOK; usd recorded as 0"
    p_in, p_out = PRICES_USD_PER_MTOK[model]
    return (tokens_in * p_in + tokens_out * p_out) / 1_000_000, ""


def _rough_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _parse_choice(text: str, options: list[str]) -> list[str]:
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end < start:
        return []
    try:
        picked = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    out: list[str] = []
    for name in picked if isinstance(picked, list) else []:
        if isinstance(name, str) and name in options and name not in out:
            out.append(name)
    return out
