"""
ARIA - Web Search Tool (Hardened)
==================================

Searches the web using DuckDuckGo.
Added: region, time_range filtering.
"""

import logging
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.web_search")


class WebSearchTool(ToolBase):
    """Search the web for information using DuckDuckGo."""

    name = "web_search"
    description = (
        "Search the web for current information. "
        "Returns titles, URLs, and snippets from search results. "
        "Use when you need up-to-date information that you don't already know. "
        "Supports region filtering and time range."
    )
    parameters = [
        ToolParam(
            name="query",
            type="string",
            description="The search query",
            required=True,
        ),
        ToolParam(
            name="num_results",
            type="integer",
            description="Number of results to return (default: 5, max: 20)",
            required=False,
            default=5,
        ),
        ToolParam(
            name="region",
            type="string",
            description="Region for results: us-en, es-es, fr-fr, de-de, etc. (default: wt-wt for global)",
            required=False,
            default="wt-wt",
        ),
        ToolParam(
            name="time_range",
            type="string",
            description="Time filter: d (day), w (week), m (month), y (year). Default: no filter",
            required=False,
            enum=["d", "w", "m", "y"],
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        query = kwargs["query"]
        num_results = min(kwargs.get("num_results", 5), 20)
        region = kwargs.get("region", "wt-wt")
        time_range = kwargs.get("time_range")

        results = self._search_ddgs(query, num_results, region, time_range)

        if results is None:
            return ToolResult(success=False, error="No search backend available")

        if not results:
            return ToolResult(
                success=True,
                output="No results found.",
                data={"results": [], "query": query},
            )

        # Check for error in results
        if len(results) == 1 and "error" in results[0]:
            return ToolResult(
                success=False,
                error=results[0]["error"],
                data={"query": query},
            )

        # Format output
        lines = [f"Search results for: {query}"]
        if region != "wt-wt":
            lines[0] += f" (region: {region})"
        if time_range:
            labels = {"d": "past day", "w": "past week", "m": "past month", "y": "past year"}
            lines[0] += f" ({labels.get(time_range, time_range)})"
        lines.append("")

        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            url = r.get("url", r.get("href", ""))
            snippet = r.get("snippet", r.get("body", ""))
            lines.append(f"{i}. {title}")
            if url:
                lines.append(f"   {url}")
            if snippet:
                lines.append(f"   {snippet}")
            lines.append("")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"results": results, "query": query, "count": len(results)},
        )

    def _search_ddgs(self, query, num_results, region, time_range):
        """Search directly with DDGS library (compatible with ddgs v6+ and v9+)."""
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                ddgs_kwargs = {
                    "max_results": num_results,
                    "region": region,
                }
                if time_range:
                    ddgs_kwargs["timelimit"] = time_range
                # ddgs v9+ uses positional 'query', older versions use 'keywords'
                try:
                    raw = list(ddgs.text(query, **ddgs_kwargs))
                except TypeError:
                    ddgs_kwargs["keywords"] = query
                    raw = list(ddgs.text(**ddgs_kwargs))

            # Normalize keys to match expected format
            results = []
            for r in raw:
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", r.get("url", "")),
                    "snippet": r.get("body", r.get("snippet", "")),
                })
            return results
        except ImportError:
            return None
        except Exception as e:
            logger.warning(f"DDGS search failed: {e}")
            return None

