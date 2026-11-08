from fastapi.testclient import TestClient

from app.ingestion.pipeline import ingest_articles
from app.main import create_app
from app.portfolio.paper import TradeError, execute, get_account
from tests.conftest import recent_articles


def test_pipeline_dedups_and_filters(session, linker, lexicon):
    stats = ingest_articles(session, recent_articles(), linker, lexicon)
    assert stats.fetched == 4
    assert stats.stored == 2  # Infosys (once, copy deduped) + oil theme
    assert stats.duplicates == 1 and stats.irrelevant == 1
    assert {"INFY.NS", "ONGC.NS", "INDIGO.NS"} <= stats.tickers_touched
    # running again stores nothing new
    assert ingest_articles(session, recent_articles(), linker, lexicon).stored == 0


def test_end_to_end(jobs):
    with TestClient(create_app(jobs)) as client:
        r = client.post("/api/admin/run", params={"job": "all"})
        assert r.status_code == 200, r.text

        latest = client.get("/api/signals/latest").json()
        assert len(latest) == len(jobs.tickers)
        infy = next(s for s in latest if s["ticker"] == "INFY.NS")
        assert infy["news_score"] > 0
        assert infy["explanation"]["top_articles"]

        news = client.get("/api/news", params={"ticker": "INFY.NS"}).json()
        assert news and news[0]["impacts"][0]["ticker"] == "INFY.NS"

        detail = client.get("/api/tickers/INFY.NS").json()
        assert detail["prices"] and detail["signal"]["ticker"] == "INFY.NS"

        bt = client.post("/api/backtest", json={"ticker": "INFY.NS", "days": 60}).json()
        assert bt["days"] > 0

        assert client.get("/api/tickers/NOPE").status_code == 404

        p = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "BUY", "qty": 10}).json()
        assert p["positions"][0]["ticker"] == "AAPL" and p["cash"] < p["starting_cash"]
        assert (
            client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "SELL", "qty": 999}).status_code == 400
        )


def test_paper_long_only(session):
    acct = get_account(session, 1000)
    execute(session, acct, "AAPL", "BUY", 2, 100)
    assert acct.cash == 800
    try:
        execute(session, acct, "AAPL", "BUY", 100, 100)
        raise AssertionError("should fail")
    except TradeError:
        pass
    execute(session, acct, "AAPL", "SELL", 2, 110)
    assert acct.cash == 1020
