"""Link understanding — extract URLs from messages and fetch content summaries."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.tools.web import WebFetchTool


# ============================================================================
# URL Pattern and Safety
# ============================================================================

_URL_PATTERN = re.compile(
    r'https?://[^\s<>\[\](){}"\',;。，！？、；：]+',
    re.IGNORECASE,
)

# SSRF protection: blocked hosts and private IP ranges
_BLOCKED_HOSTS = frozenset({
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "[::1]",
    "169.254.169.254",           # AWS metadata
    "metadata.google.internal",  # GCP metadata
})

_PRIVATE_PREFIXES = (
    "10.",
    "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.",
    "172.24.", "172.25.", "172.26.", "172.27.",
    "172.28.", "172.29.", "172.30.", "172.31.",
    "192.168.",
    "fd",   # IPv6 ULA
    "fe80", # IPv6 link-local
)


# ============================================================================
# Link Understanding
# ============================================================================

class LinkUnderstanding:
    """Extract URLs from user messages and fetch content summaries.

    The summaries are injected into the user message context so the LLM
    can reference the linked content in its response.
    """

    def __init__(
        self,
        web_fetch_tool: WebFetchTool,
        max_urls: int = 3,
        max_content_chars: int = 2000,
    ):
        self.web_fetch = web_fetch_tool
        self.max_urls = max_urls
        self.max_content_chars = max_content_chars

    def extract_urls(self, text: str) -> list[str]:
        """Extract safe URLs from text.

        Filters out private/internal addresses for SSRF protection.
        Returns at most ``max_urls`` URLs.
        """
        raw_urls = _URL_PATTERN.findall(text)
        # Deduplicate while preserving order
        seen: set[str] = set()
        safe: list[str] = []
        for url in raw_urls:
            # Strip trailing punctuation that regex might capture
            url = url.rstrip(".,;:!?)")
            if url in seen:
                continue
            seen.add(url)
            if _is_safe_url(url):
                safe.append(url)
            else:
                logger.debug("Blocked unsafe URL: {}", url)
        return safe[: self.max_urls]

    def has_urls(self, text: str) -> bool:
        """Quick check whether the text contains any URLs."""
        return bool(_URL_PATTERN.search(text))

    async def summarize_links(self, text: str) -> str:
        """Extract URLs from text, fetch their content, and return a summary block.

        Returns an empty string if no URLs are found or all fetches fail.
        The returned string is meant to be appended to the user message.
        """
        urls = self.extract_urls(text)
        if not urls:
            return ""

        summaries: list[str] = []
        for url in urls:
            summary = await self._fetch_and_summarize(url)
            if summary:
                summaries.append(summary)

        if not summaries:
            return ""

        header = "[以下是消息中链接的内容摘要，供参考]"
        return f"\n\n---\n{header}\n\n" + "\n\n---\n\n".join(summaries)

    async def _fetch_and_summarize(self, url: str) -> str | None:
        """Fetch a single URL and return a formatted summary."""
        try:
            result = await self.web_fetch.execute(
                url=url,
                extractMode="text",
                maxChars=self.max_content_chars,
            )
            data = json.loads(result)

            if "error" in data:
                logger.debug("Link fetch failed for {}: {}", url, data["error"])
                return None

            text = data.get("text", "").strip()
            if not text:
                return None

            # Truncate if needed
            if len(text) > self.max_content_chars:
                text = text[: self.max_content_chars] + "..."

            final_url = data.get("finalUrl", url)
            return f"📎 {final_url}\n{text}"

        except Exception:
            logger.debug("Link fetch exception for {}", url, exc_info=True)
            return None


# ============================================================================
# Helpers
# ============================================================================

def _is_safe_url(url: str) -> bool:
    """Check if a URL is safe to fetch (SSRF protection)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False

        host = (parsed.hostname or "").lower()
        if not host:
            return False

        # Check blocked hosts
        if host in _BLOCKED_HOSTS:
            return False

        # Check private IP prefixes
        for prefix in _PRIVATE_PREFIXES:
            if host.startswith(prefix):
                return False

        return True
    except Exception:
        return False
