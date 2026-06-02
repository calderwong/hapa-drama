from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from hapa_drama_node.app import docs_readme


def test_docs_readme_serves_repo_readme_with_safe_markdown_metadata():
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    payload = docs_readme(cast(Any, request))
    assert payload["ok"] is True
    assert payload["document_id"] == "README.md"
    assert payload["source_path"].endswith("/README.md")
    assert payload["sha256"]
    assert "# Hapa Drama" in payload["content"]
    assert payload["provenance"]["served_from"] == "repo-root README.md"
    assert payload["safe_markdown"]["html_passthrough"] is False
    assert payload["safe_markdown"]["script_execution"] is False
