from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings


@dataclass(frozen=True)
class TickerInfo:
    symbol: str
    name: str
    market: str
    sector: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class Theme:
    key: str
    description: str
    phrases: tuple[str, ...]
    impacts: dict[str, float] = field(default_factory=dict)  # sector -> signed impact


@dataclass(frozen=True)
class Universe:
    tickers: dict[str, TickerInfo]
    themes: dict[str, Theme]

    def by_sector(self, sector: str) -> list[TickerInfo]:
        if sector == "*":
            return list(self.tickers.values())
        return [t for t in self.tickers.values() if t.sector == sector]


def load_universe(path: Path) -> Universe:
    raw = yaml.safe_load(path.read_text())
    tickers = {
        sym: TickerInfo(
            symbol=sym,
            name=cfg["name"],
            market=cfg.get("market", ""),
            sector=cfg["sector"],
            aliases=tuple(cfg.get("aliases", [])) or (cfg["name"].lower(),),
        )
        for sym, cfg in raw["tickers"].items()
    }
    themes = {
        key: Theme(
            key=key,
            description=cfg.get("description", key),
            phrases=tuple(p.lower() for p in cfg["phrases"]),
            impacts={str(k): float(v) for k, v in cfg["impacts"].items()},
        )
        for key, cfg in (raw.get("themes") or {}).items()
    }
    return Universe(tickers=tickers, themes=themes)


@lru_cache
def get_universe() -> Universe:
    return load_universe(get_settings().universe_file)
