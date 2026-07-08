import json
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import RLock
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from performance_monitor import performance_span

from .metadata import DiagramCandidate, attribution_text, reusable_license


COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
COMMONS_FILE_URL = "https://commons.wikimedia.org/wiki/File:"
COMMONS_QUERY_CACHE_LIMIT = 128

_COMMONS_QUERY_CACHE = OrderedDict()
_COMMONS_QUERY_CACHE_LOCK = RLock()


class WikimediaCommonsProvider:
    name = "wikimedia"

    def __init__(self, timeout=8, user_agent="AI-Study-Buddy/1.0"):
        self.timeout = timeout
        self.user_agent = user_agent

    def _get_json(self, params):
        cache_key = json.dumps(params, sort_keys=True, ensure_ascii=True)
        with _COMMONS_QUERY_CACHE_LOCK:
            cached = _COMMONS_QUERY_CACHE.get(cache_key)
            if cached is not None:
                _COMMONS_QUERY_CACHE.move_to_end(cache_key)
                return cached

        with performance_span("Diagram search", detail=params.get("gsrsearch", "")):
            url = f"{COMMONS_API_URL}?{urlencode(params)}"
            request = Request(url, headers={"User-Agent": self.user_agent})
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))

        with _COMMONS_QUERY_CACHE_LOCK:
            _COMMONS_QUERY_CACHE[cache_key] = payload
            _COMMONS_QUERY_CACHE.move_to_end(cache_key)
            while len(_COMMONS_QUERY_CACHE) > COMMONS_QUERY_CACHE_LIMIT:
                _COMMONS_QUERY_CACHE.popitem(last=False)
        return payload

    def find(self, queries, *, topic="", subject="", limit_per_query=8):
        queries = list(queries or [])
        if len(queries) <= 1:
            for query in queries:
                yield from self.search(query, limit=limit_per_query)
            return

        max_workers = min(4, len(queries))
        results_by_index = {}
        with performance_span("Diagram search", detail=f"wikimedia_parallel queries={len(queries)}"):
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_index = {
                    executor.submit(lambda q=query: list(self.search(q, limit=limit_per_query))): index
                    for index, query in enumerate(queries)
                }
                for future in as_completed(future_to_index):
                    index = future_to_index[future]
                    try:
                        results_by_index[index] = future.result()
                    except Exception:
                        results_by_index[index] = []
        for index in range(len(queries)):
            yield from results_by_index.get(index, [])

    def search(self, query, *, limit=8):
        search_payload = self._get_json(
            {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": 6,
                "gsrlimit": limit,
                "prop": "imageinfo|categories",
                "iiprop": "url|mime|extmetadata|size",
                "iiurlwidth": 1400,
                "iiurlheight": 900,
                "cllimit": 20,
            }
        )
        pages = (search_payload.get("query") or {}).get("pages") or {}
        for page in pages.values():
            title = page.get("title", "")
            imageinfo = (page.get("imageinfo") or [{}])[0]
            metadata = imageinfo.get("extmetadata") or {}
            license_text = (metadata.get("LicenseShortName") or {}).get("value") or ""
            if not reusable_license(license_text):
                continue
            mime_type = imageinfo.get("mime") or ""
            image_url = imageinfo.get("thumburl") or imageinfo.get("url") or ""
            if not image_url or not _is_direct_image_url(image_url) or not mime_type.startswith("image/"):
                continue
            author = (metadata.get("Artist") or {}).get("value") or "Wikimedia Commons contributor"
            author = _strip_html(author)
            page_title = title.replace("File:", "", 1)
            description = _metadata_value(metadata, "ImageDescription") or _metadata_value(metadata, "ObjectName")
            categories = tuple(
                category.get("title", "").replace("Category:", "", 1)
                for category in page.get("categories") or []
                if category.get("title")
            )
            commons_metadata = {
                key: _strip_html(value.get("value", ""))
                for key, value in metadata.items()
                if isinstance(value, dict) and value.get("value")
            }
            source_url = COMMONS_FILE_URL + page_title.replace(" ", "_")
            yield DiagramCandidate(
                provider=self.name,
                title=page_title,
                image_url=image_url,
                source_url=source_url,
                author=author,
                license=license_text,
                attribution=attribution_text(page_title, author, license_text, source_url),
                mime_type=mime_type,
                width=_safe_int(imageinfo.get("thumbwidth") or imageinfo.get("width")),
                height=_safe_int(imageinfo.get("thumbheight") or imageinfo.get("height")),
                description=_strip_html(description),
                categories=categories,
                commons_metadata=commons_metadata,
            )


def _metadata_value(metadata, key):
    return (metadata.get(key) or {}).get("value") or ""


def _strip_html(value):
    import re

    return re.sub(r"<[^>]+>", "", str(value or "")).strip()


def _is_direct_image_url(value):
    parsed = urlsplit(str(value or ""))
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if not parsed.scheme.startswith("http"):
        return False
    if "commons.wikimedia.org/wiki/file:" in str(value or "").lower():
        return False
    return (
        host.endswith("wikimedia.org")
        and "/wikipedia/commons/" in path
        and bool(path.rsplit("/", 1)[-1])
    )


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
