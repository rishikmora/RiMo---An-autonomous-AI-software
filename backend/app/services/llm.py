"""Thin, well-typed wrapper around the Anthropic Messages API.

Provides:
  * `LLMClient` – streaming-aware completion with retry/backoff.
  * `AgentLoop`  – the canonical tool-calling reasoning loop shared by every
    specialist agent. The loop drives the model until it emits a final answer
    or the iteration budget is exhausted, dispatching tool calls to a
    `ToolRegistry` along the way.

The loop is provider-agnostic in shape, so swapping models (Opus for Haiku on
cheap tasks) is a single argument.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from anthropic import APIStatusError, AsyncAnthropic, RateLimitError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class ToolSpec:
    """A tool exposed to the model, with its JSON schema and async handler."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler

    def to_api(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    """Holds the set of tools available to a given agent run."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def add(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: ToolHandler,
    ) -> None:
        self.register(ToolSpec(name, description, input_schema, handler))

    @property
    def api_tools(self) -> list[dict[str, Any]]:
        return [t.to_api() for t in self._tools.values()]

    async def dispatch(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"unknown tool '{name}'"}
        try:
            return await tool.handler(payload)
        except Exception as exc:  # noqa: BLE001 - surface tool errors to model
            logger.warning("tool_error", tool=name, error=str(exc))
            return {"error": str(exc)}


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens


@dataclass(slots=True)
class AgentResult:
    final_text: str
    iterations: int
    usage: Usage
    transcript: list[dict[str, Any]] = field(default_factory=list)
    success: bool = True
    error: str | None = None


class LLMClient:
    """Resilient async wrapper around the Anthropic SDK."""

    def __init__(self, api_key: str | None = None) -> None:
        self._client = AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        max_retries: int = 4,
    ) -> Any:
        """Single completion call with exponential backoff on rate limits."""
        model = model or settings.default_model
        temperature = settings.agent_temperature if temperature is None else temperature

        attempt = 0
        while True:
            try:
                return await self._client.messages.create(
                    model=model,
                    system=system,
                    messages=messages,  # type: ignore[arg-type]
                    tools=tools or [],  # type: ignore[arg-type]
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except (RateLimitError, APIStatusError) as exc:
                attempt += 1
                if attempt > max_retries:
                    raise
                backoff = min(2**attempt, 30)
                logger.warning("llm_retry", attempt=attempt, backoff=backoff, error=str(exc))
                await asyncio.sleep(backoff)


class AgentLoop:
    """Canonical tool-using reasoning loop.

    Repeatedly calls the model; whenever the model requests tools, executes
    them and feeds results back, until the model returns a turn with no tool
    use (the final answer) or the iteration cap is hit.
    """

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        *,
        model: str | None = None,
        max_iterations: int | None = None,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._model = model
        self._max_iterations = max_iterations or settings.max_agent_iterations

    async def run(
        self,
        *,
        system: str,
        prompt: str,
        on_step: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> AgentResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        usage = Usage()
        transcript: list[dict[str, Any]] = []
        tools = self._registry.api_tools

        for iteration in range(1, self._max_iterations + 1):
            try:
                response = await self._llm.complete(
                    system=system,
                    messages=messages,
                    tools=tools,
                    model=self._model,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("agent_loop_failed", error=str(exc), iteration=iteration)
                return AgentResult(
                    final_text="",
                    iterations=iteration,
                    usage=usage,
                    transcript=transcript,
                    success=False,
                    error=str(exc),
                )

            usage.add(Usage(response.usage.input_tokens, response.usage.output_tokens))

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b.text for b in response.content if b.type == "text"]
            assistant_text = "\n".join(text_blocks).strip()

            step = {
                "iteration": iteration,
                "text": assistant_text,
                "tools": [{"name": t.name, "input": t.input} for t in tool_uses],
            }
            transcript.append(step)
            if on_step:
                await on_step(step)

            # No tools requested -> this is the final answer.
            if not tool_uses:
                return AgentResult(
                    final_text=assistant_text,
                    iterations=iteration,
                    usage=usage,
                    transcript=transcript,
                    success=True,
                )

            # Persist the assistant turn (text + tool_use blocks).
            messages.append({"role": "assistant", "content": response.content})

            # Execute every requested tool and collect results.
            tool_results = []
            for tu in tool_uses:
                result = await self._registry.dispatch(tu.name, tu.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": _stringify(result),
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        logger.warning("agent_loop_exhausted", max_iterations=self._max_iterations)
        return AgentResult(
            final_text=transcript[-1]["text"] if transcript else "",
            iterations=self._max_iterations,
            usage=usage,
            transcript=transcript,
            success=False,
            error="iteration budget exhausted",
        )


def _stringify(result: dict[str, Any]) -> str:
    import json

    try:
        return json.dumps(result, default=str)[:20_000]
    except (TypeError, ValueError):
        return str(result)[:20_000]
