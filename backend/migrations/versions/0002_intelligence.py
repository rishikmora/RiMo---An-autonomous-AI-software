"""advanced intelligence layer: knowledge graph, prompts, cost ledger, incidents

Adds the Tier 1–4 capability tables:
  * graph_nodes / graph_edges      — the project knowledge graph
  * prompt_variants / prompt_executions — self-evolving prompts
  * model_calls                    — economic cost ledger
  * incidents                      — autonomous failure recovery

Creates only the new tables (the baseline 0001 migration created the rest).

Revision ID: 0002_intelligence
Revises: 0001_initial
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.db.session import Base
from app.models import (  # noqa: F401 - ensure models are registered on metadata
    GraphEdge,
    GraphNode,
    Incident,
    ModelCall,
    PromptExecution,
    PromptVariant,
)

revision: str = "0002_intelligence"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TABLES = [
    "graph_nodes",
    "graph_edges",
    "prompt_variants",
    "prompt_executions",
    "model_calls",
    "incidents",
]


def upgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in _NEW_TABLES]
    Base.metadata.create_all(bind=bind, tables=tables)


def downgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in reversed(_NEW_TABLES)]
    Base.metadata.drop_all(bind=bind, tables=tables)
