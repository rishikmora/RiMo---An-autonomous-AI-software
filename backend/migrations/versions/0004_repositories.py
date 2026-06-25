"""multi-repository swarm: repositories table

Adds the repositories table so a project can coordinate several repos
(frontend, backend, AI, infra, mobile, shared) as one system.

Revision ID: 0004_repositories
Revises: 0003_refresh_tokens
"""
from collections.abc import Sequence

from alembic import op

from app.db.session import Base
from app.models import Repository  # noqa: F401 - register on metadata

revision: str = "0004_repositories"
down_revision: str | None = "0003_refresh_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["repositories"]])


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables["repositories"]])
