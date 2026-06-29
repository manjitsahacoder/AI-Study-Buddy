import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .metadata import DiagramCandidate, attribution_text, reusable_license


COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
COMMONS_FILE_URL = "https://commons.wikimedia.org/wiki/File:"


class WikimediaCommonsProvider:
    name = "wikimedia"

    def __init__(self, timeout=8, user_agent="AI-Study-Buddy/1.0"):
        self.timeout = timeout
        self.user_agent = user_agent

    def _get_json(self, params):
        url = f"{COMMONS_API_URL}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def search(self, query, *, limit=8):
        search_payload = self._get_json(
            {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": 6,
                "gsrlimit": limit,
                "prop": "imageinfo",
                "iiprop": "url|mime|extmetadata",
                "iiurlwidth": 1400,
                "iiurlheight": 900,
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
            if not image_url or not mime_type.startswith("image/"):
                continue
            author = (metadata.get("Artist") or {}).get("value") or "Wikimedia Commons contributor"
            author = _strip_html(author)
            page_title = title.replace("File:", "", 1)
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
            )


def _strip_html(value):
    import re

    return re.sub(r"<[^>]+>", "", str(value or "")).strip()
