"""Embeddings, JSON output parsing, and the agent registry."""
from __future__ import annotations

import math

import pytest

from app.agents.registry import ALL_ROLES, get_agent
from app.core.config import settings
from app.models.enums import AgentRole
from app.orchestration.utils import parse_json_output
from app.services.embeddings import DeterministicEmbeddingProvider


class TestDeterministicEmbeddings:
    @pytest.mark.asyncio
    async def test_dimension_matches_settings(self) -> None:
        provider = DeterministicEmbeddingProvider(settings.embedding_dimensions)
        vec = await provider.embed("autonomous software engineering")
        assert len(vec) == settings.embedding_dimensions

    @pytest.mark.asyncio
    async def test_is_unit_normalised(self) -> None:
        provider = DeterministicEmbeddingProvider(settings.embedding_dimensions)
        vec = await provider.embed("vector memory recall")
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_is_deterministic(self) -> None:
        provider = DeterministicEmbeddingProvider(64)
        a = await provider.embed("same input")
        b = await provider.embed("same input")
        assert a == b

    @pytest.mark.asyncio
    async def test_different_text_differs(self) -> None:
        provider = DeterministicEmbeddingProvider(256)
        a = await provider.embed("alpha")
        b = await provider.embed("beta")
        assert a != b


class TestJsonParsing:
    def test_plain_json(self) -> None:
        assert parse_json_output('{"a": 1}') == {"a": 1}

    def test_fenced_json(self) -> None:
        assert parse_json_output('```json\n{"a": 1}\n```') == {"a": 1}

    def test_json_embedded_in_prose(self) -> None:
        text = 'Here is the result:\n{"mission": "ship"}\nThanks!'
        assert parse_json_output(text) == {"mission": "ship"}

    def test_empty_returns_none(self) -> None:
        assert parse_json_output("") is None

    def test_garbage_returns_none(self) -> None:
        assert parse_json_output("not json at all") is None


class TestAgentRegistry:
    def test_all_ten_roles_present(self) -> None:
        assert len(ALL_ROLES) == 10
        assert set(ALL_ROLES) == set(AgentRole)

    @pytest.mark.parametrize("role", list(AgentRole))
    def test_every_agent_has_substantive_prompt(self, role: AgentRole) -> None:
        agent = get_agent(role)
        assert agent.role is role
        assert len(agent.system_prompt) > 100

    def test_memory_agent_uses_fast_model(self) -> None:
        agent = get_agent(AgentRole.MEMORY)
        assert agent.model == settings.fast_model

    def test_strategy_agents_emit_json_contract(self) -> None:
        for role in (AgentRole.CEO, AgentRole.PLANNER, AgentRole.ARCHITECT):
            assert "JSON" in get_agent(role).system_prompt
