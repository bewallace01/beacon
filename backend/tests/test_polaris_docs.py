"""Phase 10.4: Polaris's doc-reading paths.

Tests live in the backend pytest tree (so we get the existing fixture
infrastructure for free) but exercise functions defined in
`polaris/bot.py` — pythonpath is extended in pytest.ini so `import bot`
resolves to the polaris module.

We don't touch `tick()` end-to-end here because it depends on the
Anthropic client + the lightsei SDK both being initialized, which is
out of scope for unit-level checks. The pieces under test:

  - _gh_config — env-var dispatch
  - _read_docs_from_disk — disk path
  - _read_docs_from_github — Contents API fetch + hashing
  - GitHubDocFetchError on non-2xx / transport error
  - hash stability (identical content → identical hashes)
"""
import base64
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

import bot as polaris_bot


# Capture the real httpx.Client at module import — same trick as the
# webhook tests. Lets nested patch.object work with the autouse fixture.
_REAL_HTTPX_CLIENT = httpx.Client


@contextmanager
def _mock_gh(handler):
    """Route polaris_bot._fetch_github_doc through a custom handler.
    `_fetch_github_doc` does `import httpx; httpx.Client(...)` inline
    — patch the module-global httpx.Client (not bot.httpx, since bot
    imports it lazily inside the function)."""
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return _REAL_HTTPX_CLIENT(transport=transport, **kwargs)

    with patch("httpx.Client", side_effect=factory):
        yield


@pytest.fixture(autouse=True)
def _clean_polaris_env(monkeypatch):
    """Strip any POLARIS_GITHUB_* vars that might leak in from the
    surrounding shell. Each test sets exactly the env it needs."""
    for k in list(polaris_bot.os.environ):
        if k.startswith("POLARIS_GITHUB_"):
            monkeypatch.delenv(k, raising=False)
    yield


# ---------- _gh_config ---------- #


def test_gh_config_returns_none_when_repo_unset():
    assert polaris_bot._gh_config() is None


def test_gh_config_returns_none_when_token_missing(monkeypatch):
    monkeypatch.setenv("POLARIS_GITHUB_REPO", "acme/widgets")
    # No token.
    assert polaris_bot._gh_config() is None


def test_gh_config_returns_none_for_malformed_repo(monkeypatch):
    monkeypatch.setenv("POLARIS_GITHUB_REPO", "no-slash-here")
    monkeypatch.setenv("POLARIS_GITHUB_TOKEN", "ghp_x")
    assert polaris_bot._gh_config() is None


def test_gh_config_defaults_branch_and_paths(monkeypatch):
    monkeypatch.setenv("POLARIS_GITHUB_REPO", "acme/widgets")
    monkeypatch.setenv("POLARIS_GITHUB_TOKEN", "ghp_x")
    cfg = polaris_bot._gh_config()
    assert cfg == {
        "owner": "acme",
        "name": "widgets",
        "branch": "main",
        "token": "ghp_x",
        "paths": ["MEMORY.md", "TASKS.md"],
    }


def test_gh_config_honors_custom_branch_and_paths(monkeypatch):
    monkeypatch.setenv("POLARIS_GITHUB_REPO", "acme/widgets")
    monkeypatch.setenv("POLARIS_GITHUB_TOKEN", "ghp_x")
    monkeypatch.setenv("POLARIS_GITHUB_BRANCH", "staging")
    monkeypatch.setenv(
        "POLARIS_GITHUB_DOCS_PATHS", "docs/MEMORY.md, README.md ,goals.md"
    )
    cfg = polaris_bot._gh_config()
    assert cfg["branch"] == "staging"
    assert cfg["paths"] == ["docs/MEMORY.md", "README.md", "goals.md"]


def test_gh_config_handles_empty_paths_csv(monkeypatch):
    """User accidentally sets POLARIS_GITHUB_DOCS_PATHS=,, — fall back
    to the default pair instead of fetching nothing."""
    monkeypatch.setenv("POLARIS_GITHUB_REPO", "acme/widgets")
    monkeypatch.setenv("POLARIS_GITHUB_TOKEN", "ghp_x")
    monkeypatch.setenv("POLARIS_GITHUB_DOCS_PATHS", ",,,")
    cfg = polaris_bot._gh_config()
    assert cfg["paths"] == ["MEMORY.md", "TASKS.md"]


# ---------- _fetch_github_doc + _read_docs_from_github ---------- #


def _contents_response(content: str, *, encoding: str = "base64") -> httpx.Response:
    body = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return httpx.Response(
        200,
        json={
            "type": "file",
            "encoding": encoding,
            "content": body,
            "name": "doc.md",
            "path": "doc.md",
        },
    )


def test_fetch_decodes_base64_content():
    handler = lambda req: _contents_response("hello from github\n")
    with _mock_gh(handler):
        text = polaris_bot._fetch_github_doc(
            owner="acme", name="widgets", branch="main",
            path="MEMORY.md", token="ghp_x",
        )
    assert text == "hello from github\n"


def test_fetch_passes_pat_and_ref_in_request():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["auth"] = req.headers.get("authorization")
        return _contents_response("ok")

    with _mock_gh(handler):
        polaris_bot._fetch_github_doc(
            owner="acme", name="widgets", branch="staging",
            path="docs/MEMORY.md", token="ghp_super",
        )
    assert "ref=staging" in captured["url"]
    assert "/repos/acme/widgets/contents/docs/MEMORY.md" in captured["url"]
    assert captured["auth"] == "Bearer ghp_super"


def test_fetch_raises_on_401():
    handler = lambda req: httpx.Response(401, json={"message": "Bad credentials"})
    with _mock_gh(handler):
        with pytest.raises(polaris_bot.GitHubDocFetchError) as ei:
            polaris_bot._fetch_github_doc(
                owner="acme", name="widgets", branch="main",
                path="MEMORY.md", token="ghp_bad",
            )
    assert "401" in str(ei.value) or "rejected" in str(ei.value).lower()


def test_fetch_raises_on_404():
    handler = lambda req: httpx.Response(404, json={"message": "Not Found"})
    with _mock_gh(handler):
        with pytest.raises(polaris_bot.GitHubDocFetchError):
            polaris_bot._fetch_github_doc(
                owner="acme", name="widgets", branch="main",
                path="missing.md", token="ghp_x",
            )


def test_fetch_raises_on_transport_error():
    def handler(req):
        raise httpx.ConnectError("simulated network failure")

    with _mock_gh(handler):
        with pytest.raises(polaris_bot.GitHubDocFetchError) as ei:
            polaris_bot._fetch_github_doc(
                owner="acme", name="widgets", branch="main",
                path="MEMORY.md", token="ghp_x",
            )
    assert "network error" in str(ei.value).lower()


def test_fetch_raises_on_directory_response():
    """GET /contents/{path} returns a list when path is a directory.
    Polaris docs are always files, so a list response means the user
    pointed POLARIS_GITHUB_DOCS_PATHS at a directory — error out."""
    handler = lambda req: httpx.Response(
        200, json=[{"type": "file", "name": "x"}]
    )
    with _mock_gh(handler):
        with pytest.raises(polaris_bot.GitHubDocFetchError):
            polaris_bot._fetch_github_doc(
                owner="acme", name="widgets", branch="main",
                path="some-dir", token="ghp_x",
            )


def test_read_docs_from_github_fetches_each_path():
    """Hits the API once per configured path. Hashes are computed from
    decoded text, not from GitHub's reported sha — so the cache lines
    up with disk-mode hashing."""
    cfg = {
        "owner": "acme",
        "name": "widgets",
        "branch": "main",
        "token": "ghp_x",
        "paths": ["MEMORY.md", "TASKS.md", "ROADMAP.md"],
    }
    fetched = []

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        # Echo the path back as the doc content so we can verify
        # path → content routing.
        if "MEMORY.md" in url:
            fetched.append("MEMORY.md")
            return _contents_response("memory content")
        if "TASKS.md" in url:
            fetched.append("TASKS.md")
            return _contents_response("tasks content")
        if "ROADMAP.md" in url:
            fetched.append("ROADMAP.md")
            return _contents_response("roadmap content")
        return httpx.Response(404)

    with _mock_gh(handler):
        out = polaris_bot._read_docs_from_github(cfg)

    assert out["docs"]["MEMORY.md"] == "memory content"
    assert out["docs"]["TASKS.md"] == "tasks content"
    assert out["docs"]["ROADMAP.md"] == "roadmap content"
    assert sorted(fetched) == ["MEMORY.md", "ROADMAP.md", "TASKS.md"]
    # Three independent hashes.
    assert len(set(out["hashes"].values())) == 3


def test_hashes_are_stable_across_identical_fetches():
    """Same content → same hash. This is the property that makes the
    Phase 6.2 hash-skip cache work for GitHub fetches: a push that
    doesn't change a doc's content is a no-op for Polaris."""
    cfg = {
        "owner": "acme", "name": "widgets", "branch": "main",
        "token": "ghp_x", "paths": ["MEMORY.md"],
    }
    handler = lambda req: _contents_response("identical content")
    with _mock_gh(handler):
        a = polaris_bot._read_docs_from_github(cfg)
        b = polaris_bot._read_docs_from_github(cfg)
    assert a["hashes"] == b["hashes"]


def test_hashes_match_disk_mode_hashes_for_identical_content(tmp_path, monkeypatch):
    """A user transitioning a workspace from disk to GitHub mode with
    the *same* MEMORY.md / TASKS.md content should NOT see a cache
    bust — hashes are computed identically in both code paths."""
    memory_text = "shared memory text\n"
    tasks_text = "shared tasks text\n"
    (tmp_path / "MEMORY.md").write_text(memory_text)
    (tmp_path / "TASKS.md").write_text(tasks_text)
    monkeypatch.setattr(polaris_bot, "DOCS_DIR", tmp_path)

    disk_out = polaris_bot._read_docs_from_disk()

    cfg = {
        "owner": "acme", "name": "widgets", "branch": "main",
        "token": "ghp_x", "paths": ["MEMORY.md", "TASKS.md"],
    }

    def handler(req: httpx.Request) -> httpx.Response:
        if "MEMORY.md" in str(req.url):
            return _contents_response(memory_text)
        return _contents_response(tasks_text)

    with _mock_gh(handler):
        gh_out = polaris_bot._read_docs_from_github(cfg)

    assert disk_out["hashes"] == gh_out["hashes"]


# ---------- _read_docs dispatch ---------- #


def test_read_docs_falls_back_to_disk_when_env_unset(tmp_path, monkeypatch):
    (tmp_path / "MEMORY.md").write_text("disk memory")
    (tmp_path / "TASKS.md").write_text("disk tasks")
    monkeypatch.setattr(polaris_bot, "DOCS_DIR", tmp_path)
    out = polaris_bot._read_docs()
    assert out["docs"]["MEMORY.md"] == "disk memory"
    assert out["docs"]["TASKS.md"] == "disk tasks"


def test_read_docs_uses_github_when_env_set(monkeypatch):
    monkeypatch.setenv("POLARIS_GITHUB_REPO", "acme/widgets")
    monkeypatch.setenv("POLARIS_GITHUB_TOKEN", "ghp_x")
    handler = lambda req: _contents_response("from github")
    with _mock_gh(handler):
        out = polaris_bot._read_docs()
    assert all(text == "from github" for text in out["docs"].values())
