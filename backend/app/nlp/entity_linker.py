"""Map a news article to the tickers it affects.

Two kinds of links:
  * direct: the article names the company ("Infosys bags $1.5bn deal")
  * theme:  the article describes a macro event that moves a whole sector
            ("Brent surges after OPEC+ cut" -> energy up, airlines down)
"""

import re
from dataclasses import dataclass

from app.universe import Universe

TITLE_RELEVANCE = 1.0
BODY_RELEVANCE = 0.6
THEME_RELEVANCE = 0.5


@dataclass(frozen=True)
class Link:
    ticker: str
    kind: str  # direct | theme
    relevance: float
    theme: str = ""
    impact: float = 0.0  # only for theme links
    matched: str = ""


def _compile(alias: str) -> re.Pattern[str]:
    flags = 0 if any(c.isupper() for c in alias) else re.IGNORECASE
    return re.compile(rf"(?<![\w.]){re.escape(alias)}(?![\w])", flags)


class EntityLinker:
    def __init__(self, universe: Universe):
        self.universe = universe
        self._alias_patterns = {sym: [(a, _compile(a)) for a in info.aliases] for sym, info in universe.tickers.items()}
        self._theme_patterns = {
            key: [(p, _compile(p)) for p in theme.phrases] for key, theme in universe.themes.items()
        }

    def direct_links(self, title: str, summary: str = "") -> list[Link]:
        links = []
        for sym, patterns in self._alias_patterns.items():
            for alias, pat in patterns:
                if pat.search(title):
                    links.append(Link(sym, "direct", TITLE_RELEVANCE, matched=alias))
                    break
            else:
                for alias, pat in patterns:
                    if summary and pat.search(summary):
                        links.append(Link(sym, "direct", BODY_RELEVANCE, matched=alias))
                        break
        return links

    def theme_links(self, text: str) -> list[Link]:
        impacts: dict[tuple[str, str], Link] = {}
        for key, patterns in self._theme_patterns.items():
            hit = next((p for p, pat in patterns if pat.search(text)), None)
            if not hit:
                continue
            theme = self.universe.themes[key]
            for sector, impact in theme.impacts.items():
                for t in self.universe.by_sector(sector):
                    k = (t.symbol, key)
                    # a specific sector impact overrides the market-wide "*" impact
                    if k in impacts and sector == "*":
                        continue
                    impacts[k] = Link(t.symbol, "theme", THEME_RELEVANCE, key, impact, hit)
        return list(impacts.values())

    def link(self, title: str, summary: str = "") -> list[Link]:
        return self.direct_links(title, summary) + self.theme_links(f"{title}. {summary}")
