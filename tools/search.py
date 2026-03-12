import re
import html
import json
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


async def _tool_image_search(query: str, max_results: int = 3) -> str:
    max_results = max(3, min(max_results, 5))
    url = "https://duckduckgo.com/"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # First get the vqd token
            resp = await client.get(
                url,
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (compatible; PiAiLot/1.0)"},
            )
            # Extract vqd token from page
            vqd_match = re.search(r'vqd=["\']([^"\']+)', resp.text)
            if not vqd_match:
                return json.dumps({"__piailot_widget__": "images", "data": {"query": query, "images": [], "error": "Could not get search token"}})

            vqd = vqd_match.group(1)

            # Fetch images
            img_resp = await client.get(
                "https://duckduckgo.com/i.js",
                params={"q": query, "vqd": vqd, "l": "us-en", "o": "json"},
                headers={"User-Agent": "Mozilla/5.0 (compatible; PiAiLot/1.0)"},
            )
            img_data = img_resp.json()
            results = []
            for item in img_data.get("results", [])[:max_results]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("image", ""),
                    "thumbnail_url": item.get("thumbnail", ""),
                    "source": item.get("source", ""),
                })

            widget = {"__piailot_widget__": "images", "data": {"query": query, "images": results}}
            return json.dumps(widget)
    except Exception as e:
        return json.dumps({"__piailot_widget__": "images", "data": {"query": query, "images": [], "error": str(e)}})
