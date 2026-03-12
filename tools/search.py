import re
import html
import logging
import httpx

log = logging.getLogger("piailot")


async def _tool_web_search(query: str) -> str:
    url = f"https://html.duckduckgo.com/html/?q={query}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; PiAiLot/1.0)"},
            )
            resp.raise_for_status()
            body = resp.text
            snippets = re.findall(
                r'class="result__snippet"[^>]*>(.*?)</(?:a|td|span)',
                body,
                re.DOTALL,
            )
            cleaned = []
            for s in snippets[:5]:
                text = re.sub(r"<[^>]+>", "", s)
                text = html.unescape(text).strip()
                if text:
                    cleaned.append(text)
            if not cleaned:
                return "No results found."
            return "\n\n".join(cleaned)
    except Exception as e:
        return f"Search error: {e}"


async def _tool_web_fetch(url_str: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                url_str,
                headers={"User-Agent": "Mozilla/5.0 (compatible; PiAiLot/1.0)"},
            )
            resp.raise_for_status()
            text = resp.text
            text = re.sub(
                r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE
            )
            text = re.sub(
                r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE
            )
            text = re.sub(r"<[^>]+>", " ", text)
            text = html.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:3000]
    except Exception as e:
        return f"Fetch error: {e}"
