"""auth hardening: revocable refresh tokens

Adds the refresh_tokens table backing the access+refresh rotation flow. Only
the SHA-256 hash of each refresh token is stored, so a database leak does not
expose usable tokens, and rows can be revoked for logout.

Revision ID: 0003_refresh_tokens
Revises: 0002_intelligence
"""
from collections.abc import Sequence

from alembic import op

from app.db.session import Base
from app.models import RefreshToken  # noqa: F401 - register on metadata

revision: str = "0003_refresh_tokens"
down_revision: str | None = "0002_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["refresh_tokens"]])


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables["refresh_tokens"]])
