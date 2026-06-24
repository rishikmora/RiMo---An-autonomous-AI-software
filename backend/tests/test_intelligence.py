"""Tests for the Tier 1–4 intelligence subsystems.

Pure-logic tests (no DB, no external APIs) covering: model routing, prompt
bandit selection, the debate engine, the benchmark harness, and the knowledge
graph extractor. DB-backed behavior is exercised by test_api / integration.
"""
from __future__ import annotations

import asyncio

from app.models.enums import AgentRole, ModelProvider, TaskComplexityTier
from app.orchestration.benchmark import BenchmarkHarness, Metric
from app.orchestration.debate import DEBATE_ORDER, DebateEngine
from app.orchestration.graph import GraphExtractor
from app.orchestration.utils import parse_json_output
from app.services.prompts import _beta_sample
from app.services.router import ModelRouter, classify_complexity, model_router


class TestModelRouting:
    def test_architect_always_complex(self) -> None:
        tier = classify_complexity(role=AgentRole.ARCHITECT, complexity_points=1)
        assert tier is TaskComplexityTier.COMPLEX

    def test_memory_always_trivial(self) -> None:
        tier = classify_complexity(role=AgentRole.MEMORY, complexity_points=13)
        assert tier is TaskComplexityTier.TRIVIAL

    def test_points_drive_tier(self) -> None:
        assert classify_complexity(role=AgentRole.BUILDER, complexity_points=8) is TaskComplexityTier.COMPLEX
        assert classify_complexity(role=AgentRole.BUILDER, complexity_points=5) is TaskComplexityTier.STANDARD
        assert classify_complexity(role=AgentRole.BUILDER, complexity_points=1, files_touched=1) is TaskComplexityTier.TRIVIAL

    def test_many_files_escalate(self) -> None:
        tier = classify_complexity(role=AgentRole.BUILDER, complexity_points=2, files_touched=6)
        assert tier is TaskComplexityTier.COMPLEX

    def test_route_returns_a_model(self) -> None:
        routed = model_router.route(TaskComplexityTier.STANDARD)
        assert routed.model
        assert isinstance(routed.provider, ModelProvider)

    def test_cost_estimate_scales_with_tokens(self) -> None:
        cheap = ModelRouter.estimate_cost("claude-haiku-4-5-20251001", 1000, 1000)
        dear = ModelRouter.estimate_cost("claude-opus-4-8", 1000, 1000)
        assert dear > cheap > 0

    def test_routing_fallback_without_provider_key(self) -> None:
        # OpenAI/Google not keyed in tests → complex tier must still resolve
        # to a runnable Anthropic model rather than blocking.
        routed = model_router.route(TaskComplexityTier.COMPLEX)
        assert routed.provider is ModelProvider.ANTHROPIC


class TestPromptBandit:
    def test_beta_sample_in_unit_interval(self) -> None:
        for _ in range(200):
            assert 0.0 <= _beta_sample(5, 3) <= 1.0

    def test_beta_favors_higher_success(self) -> None:
        # A variant with 90/100 should, on average, sample higher than 10/100.
        good = sum(_beta_sample(90, 10) for _ in range(500)) / 500
        bad = sum(_beta_sample(10, 90) for _ in range(500)) / 500
        assert good > bad


class TestDebateEngine:
    def _engine(self) -> DebateEngine:
        return DebateEngine(parse_json_output)

    def test_consensus_when_all_endorse(self) -> None:
        async def endorse(_p: str) -> str:
            return '{"stance":"endorse","severity":"minor","argument":"ok","required_changes":[]}'

        debaters = {r: endorse for r in DEBATE_ORDER}
        result = asyncio.run(self._engine().run(proposal="x", debaters=debaters))
        assert result.consensus is True
        assert result.verdict == "approved"
        assert result.blocking_count == 0

    def test_blocker_forces_changes(self) -> None:
        async def endorse(_p: str) -> str:
            return '{"stance":"endorse","severity":"minor","argument":"ok","required_changes":[]}'

        async def block(_p: str) -> str:
            return '{"stance":"challenge","severity":"blocker","argument":"unsafe","required_changes":["fix it"]}'

        debaters = {AgentRole.ARCHITECT: endorse, AgentRole.SECURITY: block}
        result = asyncio.run(
            self._engine().run(proposal="x", debaters=debaters, order=[AgentRole.ARCHITECT, AgentRole.SECURITY])
        )
        assert result.verdict == "changes_required"
        assert result.blocking_count == 1
        assert "fix it" in result.required_changes

    def test_required_changes_deduplicated(self) -> None:
        async def same(_p: str) -> str:
            return '{"stance":"challenge","severity":"major","argument":"a","required_changes":["dup"]}'

        debaters = {AgentRole.REVIEWER: same, AgentRole.SECURITY: same}
        result = asyncio.run(
            self._engine().run(proposal="x", debaters=debaters, order=[AgentRole.REVIEWER, AgentRole.SECURITY])
        )
        assert result.required_changes.count("dup") == 1


class TestBenchmarkHarness:
    def test_detects_regression_beyond_tolerance(self) -> None:
        async def slow(ref: str) -> float:
            return 100.0 if ref == "baseline" else 130.0  # +30%

        h = BenchmarkHarness()
        h.add(Metric("latency", slow, lower_is_better=True, tolerance=0.05))
        report = asyncio.run(h.run())
        assert report.passed is False
        assert report.regressions

    def test_tolerates_small_change(self) -> None:
        async def stable(ref: str) -> float:
            return 100.0 if ref == "baseline" else 103.0  # +3%, within 5%

        h = BenchmarkHarness()
        h.add(Metric("latency", stable, lower_is_better=True, tolerance=0.05))
        report = asyncio.run(h.run())
        assert report.passed is True

    def test_higher_is_better_regression(self) -> None:
        async def throughput(ref: str) -> float:
            return 1000.0 if ref == "baseline" else 800.0  # dropped 20%

        h = BenchmarkHarness()
        h.add(Metric("throughput", throughput, lower_is_better=False, tolerance=0.05))
        report = asyncio.run(h.run())
        assert report.passed is False


class TestKnowledgeGraph:
    def test_extracts_python_structure(self) -> None:
        files = {
            "app/models.py": (
                "from sqlalchemy import Column\n"
                "class User:\n"
                "    __tablename__ = 'users'\n"
                "def helper():\n"
                "    return 1\n"
            ),
        }
        nodes, edges = GraphExtractor().extract(files)
        kinds = {n.kind.value for n in nodes}
        assert "class" in kinds
        assert "function" in kinds
        assert "db_table" in kinds
        # the users table node should exist
        assert any(n.name == "users" and n.kind.value == "db_table" for n in nodes)

    def test_extracts_api_routes(self) -> None:
        files = {
            "api.py": (
                "@router.get('/health')\n"
                "async def health():\n"
                "    return {}\n"
            )
        }
        nodes, _ = GraphExtractor().extract(files)
        routes = [n for n in nodes if n.kind.value == "api_route"]
        assert routes and routes[0].meta.get("method") == "GET"

    def test_extracts_external_dependencies(self) -> None:
        files = {"app.py": "import httpx\nimport os\n"}
        nodes, edges = GraphExtractor().extract(files)
        ext = {n.name for n in nodes if n.kind.value == "external"}
        assert "httpx" in ext

    def test_skips_vendor_dirs(self) -> None:
        files = {"node_modules/react/index.js": "export const x = 1;"}
        nodes, _ = GraphExtractor().extract(files)
        assert nodes == []


class TestAgentMarketplace:
    def test_default_catalog_populated(self) -> None:
        from app.orchestration.fleet import agent_marketplace

        slugs = {s.slug for s in agent_marketplace.all()}
        assert {"flutter", "ml", "nextjs", "data"}.issubset(slugs)

    def test_match_by_stack(self) -> None:
        from app.orchestration.fleet import agent_marketplace

        class FakeProject:
            id = "p"
            primary_language = "Dart"
            mission = "A Flutter mobile app"
            description = ""
            objectives: dict = {}

        matched = {s.slug for s in agent_marketplace.match(FakeProject())}
        assert "flutter" in matched

    def test_no_match_returns_empty(self) -> None:
        from app.orchestration.fleet import agent_marketplace

        class FakeProject:
            id = "p"
            primary_language = "COBOL"
            mission = "mainframe batch jobs"
            description = ""
            objectives: dict = {}

        assert agent_marketplace.match(FakeProject()) == []


class TestFleetAttention:
    def test_blocked_with_approvals_ranks_highest(self) -> None:
        from app.models.enums import ProjectStatus
        from app.orchestration.fleet import FleetManager

        class Blocked:
            status = ProjectStatus.BLOCKED
            is_running = True

        class Healthy:
            status = ProjectStatus.ACTIVE
            is_running = True

        fm = FleetManager()
        assert fm._attention(Blocked(), 5, 2) > fm._attention(Healthy(), 5, 0)

    def test_archived_decays(self) -> None:
        from app.models.enums import ProjectStatus
        from app.orchestration.fleet import FleetManager

        class Archived:
            status = ProjectStatus.ARCHIVED
            is_running = False

        class Active:
            status = ProjectStatus.ACTIVE
            is_running = True

        fm = FleetManager()
        assert fm._attention(Archived(), 10, 1) < fm._attention(Active(), 10, 1)
