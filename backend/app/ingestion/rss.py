import calendar
import logging
import re
from datetime import UTC, datetime
from urllib.parse import urlparse

import feedparser
import httpx

from app.ingestion.base import RawArticle

log = logging.getLogger(__name__)
TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", text or "")).strip()


class RssSource:
    name = "rss"

    def __init__(self, feeds: list[str], client: httpx.Client | None = None):
        self.feeds = feeds
        self.client = client or httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "newsalpha/0.1"})

    def parse(self, content: bytes | str, feed_url: str) -> list[RawArticle]:
        parsed = feedparser.parse(content)
        domain = urlparse(feed_url).netloc.removeprefix("www.")
        out = []
        for e in parsed.entries:
            link = e.get("link")
            title = strip_html(e.get("title", ""))
            if not link or not title:
                continue
            ts = e.get("published_parsed") or e.get("updated_parsed")
            published = datetime.fromtimestamp(calendar.timegm(ts), tz=UTC) if ts else datetime.now(UTC)
            out.append(
                RawArticle(
                    url=link,
                    title=title,
                    summary=strip_html(e.get("summary", ""))[:1000],
                    published_at=published,
                    source=domain,
                    feed=self.name,
                )
            )
        return out

    def fetch(self) -> list[RawArticle]:
        articles: list[RawArticle] = []
        for url in self.feeds:
            try:
                resp = self.client.get(url)
                resp.raise_for_status()
                articles.extend(self.parse(resp.content, url))
            except httpx.HTTPError as exc:
                log.warning("rss fetch failed for %s: %s", url, exc)
        return articles
