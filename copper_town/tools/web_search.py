"""Web search tool using DuckDuckGo."""

from __future__ import annotations

import json

from . import tool


@tool
def web_search(
    query: str,
    max_results: int = 5,
) -> str:
    """Search the web using DuckDuckGo and return titles, URLs, and snippets.

    - query: The search query
    - max_results: Number of results to return (default: 5, max: 10)
    """
    try:
        from ddgs import DDGS
    except ImportError:
        return json.dumps({
            "error": "ddgs not installed. Run: pip install ddgs"
        })

    max_results = min(max_results, 10)
    try:
        with DDGS() as ddgs:
            results = [
                {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
                for r in ddgs.text(query, max_results=max_results)
            ]
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})

    if not results:
        return json.dumps({"results": [], "hint": "No results found."})

    return json.dumps({"results": results})
