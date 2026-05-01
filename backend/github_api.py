"""Thin GitHub REST API client for Lightsei's Phase 10 integration.

We don't use the official `PyGithub` client — we only need three
things across the whole phase:

  - validate_pat(owner, name, pat) → ping GET /repos/{owner}/{name}
    on PUT /workspaces/me/github so wrong tokens fail at registration
    time instead of at first webhook.
  - fetch_file_content(...) → 10.4: Polaris reads MEMORY.md / TASKS.md
    from a repo path on every tick.
  - fetch_directory_tree(...) → 10.3: build a deploy zip from a
    pushed commit's view of an agent's bot dir.

A 200-line module is cheaper and easier to test than a wrapped SDK.

Tests mock httpx.Client at the module level via `github_api.httpx`,
following the same pattern Phase 9.2's notifications tests use.
"""
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger("lightsei.github")

GITHUB_API_BASE = "https://api.github.com"

# Interactive endpoints (PAT validation on PUT) get a tighter timeout
# than background fetches — we don't want a registration request to
# hang for 30s if GitHub is slow. Phase 10.3/10.4 background fetches
# can use a longer timeout.
INTERACTIVE_TIMEOUT_S = 5.0
BACKGROUND_TIMEOUT_S = 15.0


class GitHubAPIError(Exception):
    """Raised when GitHub returns a non-2xx response we can't recover
    from. Endpoint code translates this into HTTPException(400 or 502)
    depending on whether the cause is the user's bad input (token,
    repo) or a transient API failure."""

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        kind: str = "github_api_error",
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.kind = kind  # 'auth' | 'not_found' | 'transport' | 'github_api_error'


@dataclass
class RepoMetadata:
    full_name: str          # 'owner/name'
    default_branch: str
    private: bool


def validate_pat(*, repo_owner: str, repo_name: str, pat: str) -> RepoMetadata:
    """Ping `GET /repos/{owner}/{name}` with the PAT. On success returns
    metadata the caller can echo back to the user (default branch is
    a useful hint). On auth failure (401), repo-not-found-or-no-access
    (404), or scope failure (403) raises GitHubAPIError with `kind=auth`
    or `kind=not_found`. Transient failures raise `kind=transport`.

    GitHub returns 404 for both "repo doesn't exist" and "repo exists
    but this token can't see it" — by design, to avoid leaking
    private-repo existence. We don't try to disambiguate; the message
    just says "couldn't reach the repo with this token."
    """
    url = f"{GITHUB_API_BASE}/repos/{repo_owner}/{repo_name}"
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "lightsei-backend",
    }
    try:
        with httpx.Client(timeout=INTERACTIVE_TIMEOUT_S) as client:
            r = client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise GitHubAPIError(
            f"GitHub did not respond within {INTERACTIVE_TIMEOUT_S}s",
            kind="transport",
        ) from exc
    except httpx.HTTPError as exc:
        raise GitHubAPIError(
            f"network error reaching GitHub: {type(exc).__name__}",
            kind="transport",
        ) from exc

    if r.status_code == 401:
        raise GitHubAPIError(
            "GitHub rejected the personal access token (401). "
            "Generate a new fine-grained PAT with 'Contents: read' on this repo.",
            status=401,
            kind="auth",
        )
    if r.status_code == 403:
        # 403 typically means scope missing or rate-limited. Surface
        # the message so the user can debug.
        raise GitHubAPIError(
            "GitHub returned 403 — the PAT exists but lacks the required scope, "
            "or you've hit a rate limit. Make sure the token grants "
            "'Contents: read' on the target repo.",
            status=403,
            kind="auth",
        )
    if r.status_code == 404:
        raise GitHubAPIError(
            f"couldn't find repo {repo_owner}/{repo_name} with this token. "
            "Either the repo doesn't exist, or the PAT can't see it. "
            "Verify the owner/name spelling and the token's repo access.",
            status=404,
            kind="not_found",
        )
    if not (200 <= r.status_code < 300):
        raise GitHubAPIError(
            f"GitHub returned {r.status_code}: {(r.text or '')[:200]}",
            status=r.status_code,
            kind="github_api_error",
        )

    data = r.json()
    return RepoMetadata(
        full_name=data.get("full_name", f"{repo_owner}/{repo_name}"),
        default_branch=data.get("default_branch", "main"),
        private=bool(data.get("private", False)),
    )
