"""Sentiment analysis: a fast offline lexicon model and an LLM model with per-ticker reasoning."""

import hashlib
import json
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.universe import Universe

log = logging.getLogger(__name__)


@dataclass
class SentimentResult:
    overall: float  # [-1, 1]
    confidence: float  # [0, 1]
    model: str
    per_ticker: dict[str, float] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)

    def for_ticker(self, ticker: str) -> float:
        return self.per_ticker.get(ticker, self.overall)


class SentimentModel(Protocol):
    name: str

    def analyze(self, title: str, summary: str, tickers: list[str]) -> SentimentResult: ...


def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------- lexicon model

POSITIVE = frozenset(
    """
surge surges surged soar soars soared jump jumps jumped rally rallies rallied gain gains gained
rise rises rose climbs climbed beat beats upgrade upgraded upgrades outperform outperforms
growth strong robust wins win won bags secures secured approval approves approved expands
expansion boost boosts boosted bullish buyback dividend tops exceeds exceeded breakthrough
partnership profitable record rebound rebounds recovers optimism upbeat
""".split()
)

NEGATIVE = frozenset(
    """
fall falls fell plunge plunges plunged slump slumps slumped drop drops dropped decline declines
declined miss misses missed downgrade downgraded downgrades loss losses weak weaker layoffs
lawsuit probe fraud fined penalty recall recalls bearish warning default crash crashes tumble
tumbles tumbled sinks sank slashes halts ban banned resigns scandal investigation raid delays
shortfall underperform underperforms selloff sell-off slowdown concerns fears worries
""".split()
)

POSITIVE_PHRASES = ("record high", "raises guidance", "beats estimates", "profit rises", "order win")
NEGATIVE_PHRASES = ("record low", "cuts guidance", "misses estimates", "profit falls", "profit warning")
NEGATORS = frozenset(["not", "no", "never", "without", "fails", "failed"])
WORD_RE = re.compile(r"[a-z][a-z\-']*")


class LexiconSentiment:
    """Loughran-McDonald-style word counting with negation handling. Zero dependencies, offline."""

    name = "lexicon"

    def _count(self, text: str) -> tuple[float, float]:
        text = text.lower()
        words = WORD_RE.findall(text)
        pos = neg = 0.0
        for i, w in enumerate(words):
            polarity = 1 if w in POSITIVE else -1 if w in NEGATIVE else 0
            if not polarity:
                continue
            if any(x in NEGATORS for x in words[max(0, i - 3) : i]):
                polarity = -polarity
            if polarity > 0:
                pos += 1
            else:
                neg += 1
        pos += sum(1.5 for p in POSITIVE_PHRASES if p in text)
        neg += sum(1.5 for p in NEGATIVE_PHRASES if p in text)
        return pos, neg

    def analyze(self, title: str, summary: str, tickers: list[str]) -> SentimentResult:
        tp, tn = self._count(title)
        sp, sn = self._count(summary)
        pos, neg = 2 * tp + sp, 2 * tn + sn  # headline words count double
        hits = pos + neg
        score = (pos - neg) / (hits + 1) if hits else 0.0
        confidence = min(0.8, 0.25 + 0.1 * hits) if hits else 0.1
        return SentimentResult(overall=clamp(score), confidence=confidence, model=self.name)


# ---------------------------------------------------------------- LLM model

SYSTEM_PROMPT = """You are a sell-side equity analyst. Given a news article and a list of stocks
it was linked to, estimate the likely short-term (1-5 trading days) price impact on EACH stock.
Consider second-order effects (e.g. higher oil prices hurt airlines). If the article is irrelevant
to a stock, give it a score near 0 with low confidence.
Respond with ONLY a JSON object of the form:
{"overall": <float -1..1>, "confidence": <float 0..1>,
 "tickers": {"<SYMBOL>": {"score": <float -1..1>, "reason": "<max 20 words>"}}}"""


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in LLM response")
    return json.loads(text[start : end + 1])


class LLMSentiment:
    """Works with any OpenAI-compatible endpoint: Groq, Gemini, OpenRouter, Ollama, OpenAI."""

    name = "llm"

    def __init__(
        self,
        universe: Universe,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 20.0,
        fallback: SentimentModel | None = None,
        client: httpx.Client | None = None,
        cache_size: int = 2048,
    ):
        self.universe = universe
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.fallback = fallback or LexiconSentiment()
        self.client = client or httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {api_key}"})
        self._cache: OrderedDict[str, SentimentResult] = OrderedDict()
        self._cache_size = cache_size

    def _prompt(self, title: str, summary: str, tickers: list[str]) -> str:
        stocks = "\n".join(
            f"- {t}: {self.universe.tickers[t].name} ({self.universe.tickers[t].sector})"
            for t in tickers
            if t in self.universe.tickers
        )
        return f"HEADLINE: {title}\nSUMMARY: {summary or '(none)'}\n\nSTOCKS:\n{stocks}"

    def analyze(self, title: str, summary: str, tickers: list[str]) -> SentimentResult:
        key = hashlib.sha1(f"{title}|{summary}|{','.join(sorted(tickers))}".encode()).hexdigest()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        try:
            resp = self.client.post(
                self.url,
                json={
                    "model": self.model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": self._prompt(title, summary, tickers)},
                    ],
                },
            )
            resp.raise_for_status()
            data = _extract_json(resp.json()["choices"][0]["message"]["content"])
            per, reasons = {}, {}
            for sym, v in (data.get("tickers") or {}).items():
                if sym in tickers and isinstance(v, dict):
                    per[sym] = clamp(float(v.get("score", 0)))
                    reasons[sym] = str(v.get("reason", ""))[:200]
            result = SentimentResult(
                overall=clamp(float(data.get("overall", 0))),
                confidence=clamp(float(data.get("confidence", 0.5)), 0, 1),
                model=f"llm:{self.model}",
                per_ticker=per,
                reasons=reasons,
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.warning("LLM sentiment failed, using fallback: %s", exc)
            return self.fallback.analyze(title, summary, tickers)
        self._cache[key] = result
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return result


def build_sentiment_model(settings, universe: Universe) -> SentimentModel:
    if settings.sentiment_provider == "llm" and settings.llm_api_key:
        return LLMSentiment(
            universe,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout_seconds,
        )
    if settings.sentiment_provider == "llm":
        log.warning("SENTIMENT_PROVIDER=llm but LLM_API_KEY is empty; using lexicon model")
    return LexiconSentiment()
