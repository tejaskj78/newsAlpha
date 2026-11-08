"""GDELT 2.0 DOC API: free, keyless, global news monitoring (~100 languages, updated every 15 min).

Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
"""

import logging
import time
from datetime import UTC, datetime

import httpx

from app.ingestion.base import RawArticle
from app.universe import Universe

log = logging.getLogger(__name__)

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MARKET_QUERY = (
    '("stock market" OR "shares" OR "sensex" OR "nifty" OR "wall street" OR "crude oil" '
    'OR "interest rates" OR "central bank" OR "tariffs")'
)


def parse_seendate(value: str) -> datetime:
    # GDELT format: 20261108T093000Z
    return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def build_queries(universe: Universe, chunk: int = 6) -> list[str]:
    """One broad macro query + company-name queries chunked to stay under GDELT's query length limit."""
    names = sorted({t.name.split(" (")[0] for t in universe.tickers.values()})
    queries = [MARKET_QUERY]
    for i in range(0, len(names), chunk):
        group = " OR ".join(f'"{n}"' for n in names[i : i + chunk])
        queries.append(f"({group})")
    return [f"{q} sourcelang:english" for q in queries]


class GdeltSource:
    name = "gdelt"

    def __init__(
        self,
        universe: Universe,
        timespan: str = "6h",
        max_records: int = 100,
        client: httpx.Client | None = None,
        pause_seconds: float = 5.5,  # GDELT asks for <= 1 request / 5s
    ):
        self.universe = universe
        self.timespan = timespan
        self.max_records = max_records
        self.client = client or httpx.Client(timeout=30, headers={"User-Agent": "newsalpha/0.1"})
        self.pause_seconds = pause_seconds

    def _query(self, q: str, start: datetime | None = None, end: datetime | None = None) -> list[RawArticle]:
        params = {
            "query": q,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": str(self.max_records),
            "sort": "DateDesc",
        }
        if start and end:
            params["startdatetime"] = start.strftime("%Y%m%d%H%M%S")
            params["enddatetime"] = end.strftime("%Y%m%d%H%M%S")
        else:
            params["timespan"] = self.timespan
        resp = self.client.get(GDELT_URL, params=params)
        resp.raise_for_status()
        if not resp.text.strip().startswith("{"):
            # GDELT returns plain-text errors (e.g. "query too short") with HTTP 200
            log.warning("gdelt non-json response: %s", resp.text[:200])
            return []
        out = []
        for item in resp.json().get("articles", []):
            try:
                out.append(
                    RawArticle(
                        url=item["url"],
                        title=item.get("title", "").strip(),
                        published_at=parse_seendate(item["seendate"]),
                        source=item.get("domain", ""),
                        country=item.get("sourcecountry", ""),
                        feed=self.name,
                    )
                )
            except (KeyError, ValueError):
                continue
        return out

    def fetch(self, start: datetime | None = None, end: datetime | None = None) -> list[RawArticle]:
        articles: list[RawArticle] = []
        for i, q in enumerate(build_queries(self.universe)):
            if i:
                time.sleep(self.pause_seconds)
            try:
                articles.extend(self._query(q, start, end))
            except httpx.HTTPError as exc:
                log.warning("gdelt query failed: %s", exc)
        return articles
