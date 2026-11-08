from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class RawArticle:
    url: str
    title: str
    published_at: datetime
    source: str = ""
    summary: str = ""
    feed: str = ""
    country: str = ""

    @property
    def text(self) -> str:
        return f"{self.title}. {self.summary}".strip()


class NewsSource(Protocol):
    name: str

    def fetch(self) -> list[RawArticle]: ...
