"""Git cache lookup for a tree that has no ageval.yaml."""

from __future__ import annotations

import json
from pathlib import Path

from ageval.registry.cache import GIT_SOURCE_MARKER, PackageCache


def test_git_cache_hits_a_harbor_tree_without_ageval_yaml(tmp_path: Path) -> None:
    cache = PackageCache(tmp_path / "cache")
    commit = "a" * 40
    url = "https://example.com/harbor.git"
    entry = cache.git_entry_dir(url, commit, "tasks/demo")
    entry.mkdir(parents=True)
    (entry / "task.toml").write_text("", encoding="utf-8")
    (entry / GIT_SOURCE_MARKER).write_text(
        json.dumps(
            {
                "schema": "ageval.git-source/1",
                "git_url": url,
                "commit": commit,
                "git_ref": commit,
                "subdir": "tasks/demo",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    assert cache.lookup_git(url, commit, "tasks/demo") == entry
    bare = cache.git_entry_dir(url, commit, "empty")
    bare.mkdir(parents=True)
    (bare / GIT_SOURCE_MARKER).write_text("{}\n", encoding="utf-8")
    assert cache.lookup_git(url, commit, "empty") is None
