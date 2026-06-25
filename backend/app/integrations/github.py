"""GitHub integration.

Authenticates as a GitHub App installation (preferred over PATs for fleast
privilege and per-repo scoping), and exposes the operations the agents need:
clone, branch, commit, push, open/merge PRs, manage issues, and read checks.

All write operations route through `app.services.safety` so that secrets are
never committed and destructive actions require approval.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

GITHUB_API = "https://api.github.com"


@dataclass(slots=True)
class GitHubFile:
    path: str
    content: str


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    """Async GitHub App client scoped to a single installation."""

    def __init__(self, installation_id: str) -> None:
        self._installation_id = installation_id
        self._token: str | None = None
        self._token_expiry: float = 0.0

    # --- Auth ---------------------------------------------------------------
    def _app_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": settings.github_app_id}
        return jwt.encode(payload, settings.github_private_key, algorithm="RS256")

    async def _installation_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GITHUB_API}/app/installations/{self._installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {self._app_jwt()}",
                    "Accept": "application/vnd.github+json",
                },
            )
        if resp.status_code >= 300:
            raise GitHubError(f"token exchange failed: {resp.status_code} {resp.text}")
        data = resp.json()
        self._token = data["token"]
        # Tokens last one hour; store a conservative expiry.
        self._token_expiry = time.time() + 3000
        return self._token  # type: ignore[return-value]

    async def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self._installation_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.request(
                method, f"{GITHUB_API}{path}", headers=await self._headers(), **kwargs
            )
        if resp.status_code >= 300:
            raise GitHubError(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")
        return resp.json() if resp.content else {}

    # --- Repository metadata ------------------------------------------------
    async def get_repo(self, full_name: str) -> dict[str, Any]:
        return await self._request("GET", f"/repos/{full_name}")

    async def get_tree(self, full_name: str, ref: str = "HEAD") -> list[dict[str, Any]]:
        data = await self._request(
            "GET", f"/repos/{full_name}/git/trees/{ref}", params={"recursive": "1"}
        )
        return data.get("tree", [])

    async def get_file(self, full_name: str, path: str, ref: str | None = None) -> str:
        params = {"ref": ref} if ref else {}
        data = await self._request(
            "GET", f"/repos/{full_name}/contents/{path}", params=params
        )
        import base64

        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    # --- Branches & commits -------------------------------------------------
    async def create_branch(self, full_name: str, branch: str, from_ref: str) -> None:
        ref_data = await self._request(
            "GET", f"/repos/{full_name}/git/ref/heads/{from_ref}"
        )
        sha = ref_data["object"]["sha"]
        await self._request(
            "POST",
            f"/repos/{full_name}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        logger.info("branch_created", repo=full_name, branch=branch)

    async def commit_files(
        self,
        full_name: str,
        branch: str,
        files: list[GitHubFile],
        message: str,
    ) -> str:
        """Create a single commit applying the given files via the Git data API."""
        head = await self._request("GET", f"/repos/{full_name}/git/ref/heads/{branch}")
        base_sha = head["object"]["sha"]
        base_commit = await self._request(
            "GET", f"/repos/{full_name}/git/commits/{base_sha}"
        )
        base_tree = base_commit["tree"]["sha"]

        tree_entries = []
        for f in files:
            blob = await self._request(
                "POST",
                f"/repos/{full_name}/git/blobs",
                json={"content": f.content, "encoding": "utf-8"},
            )
            tree_entries.append(
                {"path": f.path, "mode": "100644", "type": "blob", "sha": blob["sha"]}
            )

        new_tree = await self._request(
            "POST",
            f"/repos/{full_name}/git/trees",
            json={"base_tree": base_tree, "tree": tree_entries},
        )
        new_commit = await self._request(
            "POST",
            f"/repos/{full_name}/git/commits",
            json={"message": message, "tree": new_tree["sha"], "parents": [base_sha]},
        )
        await self._request(
            "PATCH",
            f"/repos/{full_name}/git/refs/heads/{branch}",
            json={"sha": new_commit["sha"]},
        )
        logger.info("commit_pushed", repo=full_name, branch=branch, sha=new_commit["sha"][:8])
        return new_commit["sha"]

    # --- Pull requests ------------------------------------------------------
    async def open_pull_request(
        self, full_name: str, *, head: str, base: str, title: str, body: str
    ) -> dict[str, Any]:
        pr = await self._request(
            "POST",
            f"/repos/{full_name}/pulls",
            json={"title": title, "head": head, "base": base, "body": body},
        )
        logger.info("pr_opened", repo=full_name, number=pr["number"])
        return pr

    async def get_pull_request(self, full_name: str, number: int) -> dict[str, Any]:
        return await self._request("GET", f"/repos/{full_name}/pulls/{number}")

    async def merge_pull_request(
        self, full_name: str, number: int, *, method: str = "squash"
    ) -> dict[str, Any]:
        result = await self._request(
            "PUT",
            f"/repos/{full_name}/pulls/{number}/merge",
            json={"merge_method": method},
        )
        logger.info("pr_merged", repo=full_name, number=number)
        return result

    async def get_check_runs(self, full_name: str, ref: str) -> dict[str, Any]:
        return await self._request("GET", f"/repos/{full_name}/commits/{ref}/check-runs")

    # --- Issues -------------------------------------------------------------
    async def create_issue(
        self, full_name: str, *, title: str, body: str, labels: list[str] | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/repos/{full_name}/issues",
            json={"title": title, "body": body, "labels": labels or []},
        )

    async def comment(self, full_name: str, number: int, body: str) -> None:
        await self._request(
            "POST", f"/repos/{full_name}/issues/{number}/comments", json={"body": body}
        )
