# How NewsAlpha works

Read this before any interview where you show the project. Every section ends with questions you should be ready to answer.

---

## 1. Ingestion (`app/ingestion/`)

**Sources**
- `gdelt.py`: the GDELT 2.0 DOC API monitors news from around the world in ~100 languages and updates every 15 minutes. It's free and needs no key. We send one broad macro query ("stock market", "crude oil", "central bank", …) plus company-name queries in chunks of 6 (GDELT limits query length). GDELT asks for at most one request every 5 seconds, so we sleep between queries.
- `rss.py`: business RSS feeds parsed with `feedparser`. HTML is stripped from summaries.

**Pipeline (`pipeline.py`)**: fetch → canonicalise URL → exact URL dedup (DB unique constraint) → near-duplicate check → link to tickers → sentiment → store `Article` + `ArticleImpact` rows.

**SimHash dedup (`dedup.py`)**: one wire story gets republished by dozens of sites with tiny title edits. If we counted each copy, one event would look like overwhelming news.
- Split the title into tokens and 2-word shingles and hash each to 64 bits.
- For each bit position, add +1 if the hash has a 1 there and -1 if it has a 0. The sign of the total decides the output bit.
- Similar texts produce fingerprints that differ in only a few bits. We treat a Hamming distance ≤ 3 as a duplicate.
- Postgres `BIGINT` is signed, so we store the same 64 bits as a signed integer (`to_signed`).

> **Be ready for:** Why SimHash instead of comparing strings? (O(1) compare, robust to small edits.) Why title only? (Summaries differ wildly across outlets; titles are the stable part.) How would you scale it past millions of articles? (Split the 64 bits into bands and index them, i.e. LSH.)

---

## 2. Linking articles to stocks (`app/nlp/entity_linker.py`)

**Direct links** match each company's aliases from `universe.yaml` using word-boundary regex.
- A match in the title gets relevance 1.0; a match only in the summary gets 0.6.
- *Case rule:* an alias containing any uppercase letter is matched case-sensitively, so "Apple" matches the company but "apple harvest" doesn't. The same goes for "SBI" and "IndiGo".

**Theme links** handle macro events that move whole sectors. Each theme lists trigger phrases and signed impacts per sector:

```yaml
oil_up:
  phrases: [oil prices rise, opec cut, brent surges, ...]
  impacts: {energy: 0.5, aviation: -0.5, auto: -0.2}
```
`"*"` means the whole market. A sector-specific impact overrides `*` for that sector.

> **Be ready for:** What are the limits of keyword matching? (No negation: "oil prices *won't* rise" still matches. Ambiguous names. That's why the LLM provider exists.) How would you improve it? (A NER model plus an entity-disambiguation step, or let the LLM pick the tickers.)

---

## 3. Sentiment (`app/nlp/sentiment.py`)

There are two interchangeable providers behind one `SentimentModel` protocol (the strategy pattern):

| | Lexicon | LLM |
|---|---|---|
| Cost | free, offline | free tier (Groq/Gemini) or local Ollama |
| Output | one score per article | **a separate score and reason per stock** |
| Second-order effects | no | yes (oil up → airline down) |

**Lexicon**: counts positive and negative finance words in the style of Loughran-McDonald. A word preceded within 3 tokens by "not/no/never/fails" flips its polarity. Headline words count double. `score = (pos − neg) / (pos + neg + 1)`; the +1 keeps a single word from producing ±1.

**LLM**: asks for strict JSON with per-ticker `{score, reason}` at temperature 0 and `response_format=json_object`. Any HTTP error, timeout or malformed JSON **falls back to the lexicon** so the pipeline never stops. Results are cached in an LRU keyed by a hash of the input, so the same headline is never paid for twice.

> **Be ready for:** How do you stop the LLM hallucinating? (Constrained JSON, clamped values, only tickers we asked about are accepted, fallback on garbage.) Why not FinBERT? (Good option, listed on the roadmap. It's ~400MB, which is heavy for free hosting.)

---

## 4. The signal engine (`app/signals/engine.py`): the core of the project

### News score
For every article linked to a ticker within the last 72 hours:

```
w_i = relevance_i × confidence_i × 0.5^(age_hours_i / half_life)       (half_life = 18h)
news_score = Σ(w_i × s_i) / (Σ w_i + prior_mass)                        (prior_mass = 1.0)
```

- **Exponential time decay**: a 3-hour-old headline matters more than a 2-day-old one, and markets price news in quickly.
- **Shrinkage (`prior_mass`)**: this acts like a Bayesian prior centred on 0. One article can't produce a strong score; ten consistent ones can. Without it, a single random headline would cause a BUY.
- **Theme cap**: the total weight per macro theme is capped at 1.0. Otherwise 30 generic "tariff" headlines would drown out two specific, important company headlines. A unit test checks this.
- **Future articles are ignored** (`age < 0`). This is what makes the backtest honest.

### Technical score (`app/market/indicators.py`), each part in [-1, 1]
- **RSI(14)** (Wilder smoothing), read as mean reversion: below 30 → positive, above 70 → negative.
- **Trend**: price vs. the 20-day SMA (±0.5) plus the 20-day SMA vs. the 50-day SMA (±0.5).
- **Momentum**: the 5-day return divided by the expected 5-day volatility, through `tanh`. A 3% move in a calm stock means more than in a volatile one.
- Weighted 0.3 / 0.4 / 0.3.

### Decision
```
composite = 0.6 × news_score + 0.4 × technical_score
BUY if composite > 0.25, SELL if composite < −0.25, else HOLD
```
- If annualised volatility is above 55%, the thresholds are widened 1.5×. A volatile stock needs a stronger signal.
- **Confidence** = signal strength × news coverage (`1 − e^(−mass)`) × agreement (0.7 if news and technicals disagree).
- **Explanation**: the top 5 contributing articles with their exact contribution to the score, the theme totals, the technical factors and the thresholds used. You can audit every suggestion.

> **Be ready for:** Why combine news with technicals? (News says *what* changed; technicals say whether the market already reacted.) How did you choose the weights? (Hand-tuned. The honest next step is to fit them on backtest results with a train/test split by time.) What happens with no news? (The news score is 0, the decision is technicals only, and confidence is low because coverage ≈ 0.)

---

## 5. Backtesting (`app/backtest/backtester.py`)

This is a **walk-forward** replay. For each trading day *t*:
1. `as_of` = that market's close (NSE 10:00 UTC, US 20:00 UTC).
2. The news score uses only articles published ≤ `as_of`.
3. Technicals use only bars 0..t.
4. The position (BUY = 1, HOLD = 0, SELL = 0, or −1 with `allow_short`) is held from close(t) to close(t+1).
5. 10 basis points of cost per unit of position change.

Metrics:
- **Hit rate**: share of BUYs followed by a positive 5-day return, and of SELLs by a negative one.
- **Average forward return** per action.
- **Strategy return vs. buy-and-hold**.
- **Sharpe** (annualised) and **max drawdown**.

`test_no_lookahead` adds a hugely positive article on the last day and asserts that **no earlier decision changes**. This is the most important test in the repo.

> **Be ready for:** What is look-ahead bias? (Using information you wouldn't have had at the time. It's the #1 reason backtests lie.) Other biases? (Survivorship: the universe is today's large caps. Small sample: a few months of news. Overfitting the thresholds.) Is the strategy profitable? (Say what your backtest actually shows. "Not reliably, and here's why" is a strong answer.)

---

## 6. System design

- **API and worker are separate processes**, so a slow GDELT call never blocks HTTP requests. They share Postgres and Redis.
- **Redis pub/sub → SSE**: the worker publishes `signal`/`article`/`trade` events, and every API replica subscribes and streams them to browsers. SSE was chosen over WebSockets because the data flows one way and SSE reconnects automatically. nginx is configured with `proxy_buffering off` for it.
- **Distributed lock** (`jobs.py`): if you run two worker replicas, a Redis lock with a TTL makes sure only one runs each job.
- **Local mode**: SQLite + an in-memory event bus + the scheduler embedded in the API (`EMBEDDED_WORKER=true`), so one command runs everything.
- **Config**: every value is an env var through pydantic-settings (12-factor app).
- **Timezones**: everything is stored in UTC. SQLite drops tzinfo, so `as_utc()` normalises on read.

> **Be ready for:** How would you scale to 5,000 stocks? (Index aliases with Aho-Corasick instead of N regexes, batch LLM calls, partition the impacts table by date, compute signals only for tickers touched by new articles.) What if GDELT goes down? (Each source fails independently and is logged; RSS keeps working.)

---

## 7. Known limitations (being upfront about these impresses interviewers)

- Keyword theme matching has no negation handling.
- Daily bars only, so intraday reactions are invisible.
- Hand-tuned weights and thresholds.
- The paper portfolio mixes INR and USD without converting currency.
- Free data sources: yfinance is unofficial and can break; GDELT titles are sometimes machine-translated.
- **The project does not, and cannot, guarantee profits.** It is a decision-support and research tool.
