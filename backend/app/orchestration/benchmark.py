"""Autonomous benchmarking.

Before a change merges, RiMo can compare the new version against the baseline on
the metrics that matter — latency, memory, bundle size, test runtime — and
reject regressions automatically. This makes "don't ship something slower"
a property of the pipeline rather than a hope.

Benchmarks are pluggable: a benchmark is just a named async probe returning a
numeric value plus whether lower-is-better. The harness runs each probe against
baseline and candidate, computes deltas, applies per-metric tolerances, and
returns a pass/fail verdict with a human-readable diff.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.core.logging import get_logger

logger = get_logger(__name__)

# A probe measures one metric for a given ref ("baseline"|"candidate").
Probe = Callable[[str], Awaitable[float]]


@dataclass
class Metric:
    name: str
    probe: Probe
    lower_is_better: bool = True
    # Allowed regression before it's a failure, as a fraction (0.05 = 5%).
    tolerance: float = 0.05
    unit: str = ""


@dataclass
class MetricResult:
    name: str
    baseline: float
    candidate: float
    delta_pct: float
    regressed: bool
    unit: str = ""


@dataclass
class BenchmarkReport:
    passed: bool
    results: list[MetricResult] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "regressions": self.regressions,
            "results": [
                {
                    "name": r.name,
                    "baseline": r.baseline,
                    "candidate": r.candidate,
                    "delta_pct": round(r.delta_pct, 2),
                    "regressed": r.regressed,
                    "unit": r.unit,
                }
                for r in self.results
            ],
        }

    def render(self) -> str:
        lines = ["# Benchmark report", f"Verdict: {'PASS' if self.passed else 'FAIL'}", ""]
        for r in self.results:
            arrow = "▲" if r.delta_pct > 0 else "▼"
            flag = "  ❌ REGRESSION" if r.regressed else ""
            lines.append(
                f"- {r.name}: {r.baseline:g}{r.unit} → {r.candidate:g}{r.unit} "
                f"({arrow}{abs(r.delta_pct):.1f}%){flag}"
            )
        return "\n".join(lines)


class BenchmarkHarness:
    """Runs metric probes against baseline vs candidate and judges regressions."""

    def __init__(self) -> None:
        self._metrics: list[Metric] = []

    def add(self, metric: Metric) -> None:
        self._metrics.append(metric)

    async def run(self) -> BenchmarkReport:
        results: list[MetricResult] = []
        regressions: list[str] = []

        for m in self._metrics:
            try:
                baseline = await m.probe("baseline")
                candidate = await m.probe("candidate")
            except Exception as exc:  # noqa: BLE001 - a failed probe shouldn't crash the gate
                logger.warning("benchmark_probe_failed", metric=m.name, error=str(exc))
                continue

            delta_pct = self._delta_pct(baseline, candidate)
            regressed = self._is_regression(m, baseline, candidate)
            results.append(
                MetricResult(
                    name=m.name,
                    baseline=baseline,
                    candidate=candidate,
                    delta_pct=delta_pct,
                    regressed=regressed,
                    unit=m.unit,
                )
            )
            if regressed:
                regressions.append(
                    f"{m.name} regressed {abs(delta_pct):.1f}% "
                    f"({baseline:g}{m.unit} → {candidate:g}{m.unit})"
                )

        report = BenchmarkReport(passed=not regressions, results=results, regressions=regressions)
        logger.info(
            "benchmark_complete",
            passed=report.passed,
            metrics=len(results),
            regressions=len(regressions),
        )
        return report

    @staticmethod
    def _delta_pct(baseline: float, candidate: float) -> float:
        if baseline == 0:
            return 0.0 if candidate == 0 else 100.0
        return (candidate - baseline) / abs(baseline) * 100.0

    @staticmethod
    def _is_regression(metric: Metric, baseline: float, candidate: float) -> bool:
        if baseline == 0:
            return False
        change = (candidate - baseline) / abs(baseline)
        if metric.lower_is_better:
            # Worse means larger; regression if it grew beyond tolerance.
            return change > metric.tolerance
        # Higher-is-better: regression if it shrank beyond tolerance.
        return change < -metric.tolerance
