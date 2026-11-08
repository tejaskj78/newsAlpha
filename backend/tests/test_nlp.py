import httpx

from app.nlp.sentiment import LexiconSentiment, LLMSentiment


def test_direct_link_in_title(linker):
    links = linker.direct_links("Infosys raises FY guidance after strong quarter")
    assert [lk.ticker for lk in links] == ["INFY.NS"]
    assert links[0].relevance == 1.0


def test_case_sensitive_alias_avoids_false_positive(linker):
    assert (
        linker.direct_links("Apple unveils new iPhone")
        and linker.direct_links("Apple unveils new iPhone")[0].ticker == "AAPL"
    )
    assert not linker.direct_links("Farmers expect a record apple harvest")


def test_body_mention_lower_relevance(linker):
    links = linker.direct_links("Indian IT stocks rally", "Gains led by Infosys and TCS.")
    assert {lk.ticker for lk in links} == {"INFY.NS", "TCS.NS"}
    assert all(lk.relevance == 0.6 for lk in links)


def test_theme_links_have_signed_sector_impacts(linker):
    links = {lk.ticker: lk for lk in linker.theme_links("Brent surges as OPEC+ cut deepens")}
    assert links["ONGC.NS"].impact > 0
    assert links["INDIGO.NS"].impact < 0  # airlines hurt by expensive fuel
    assert links["DAL"].impact < 0


def test_sector_impact_overrides_market_wide(linker):
    links = [lk for lk in linker.theme_links("Missile strike raises geopolitical tensions") if lk.ticker == "BEL.NS"]
    assert len(links) == 1 and links[0].impact == 0.5


def test_lexicon_polarity():
    m = LexiconSentiment()
    assert m.analyze("Shares surge after earnings beat", "", []).overall > 0.3
    assert m.analyze("Shares plunge after profit warning", "", []).overall < -0.3
    assert m.analyze("Company holds annual meeting", "", []).overall == 0


def test_lexicon_negation():
    m = LexiconSentiment()
    assert m.analyze("Results did not beat expectations", "", []).overall < 0


def _llm(handler, universe):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return LLMSentiment(universe, "https://llm.test/v1", "k", "m", client=client)


def test_llm_per_ticker_scores(universe):
    def handler(req):
        content = '{"overall": 0.2, "confidence": 0.8, "tickers": {"ONGC.NS": {"score": 0.6, "reason": "higher realisations"}, "INDIGO.NS": {"score": -0.7, "reason": "fuel costs"}}}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    r = _llm(handler, universe).analyze("Oil jumps 5%", "", ["ONGC.NS", "INDIGO.NS"])
    assert r.for_ticker("ONGC.NS") == 0.6 and r.for_ticker("INDIGO.NS") == -0.7
    assert r.reasons["INDIGO.NS"] == "fuel costs"


def test_llm_falls_back_to_lexicon_on_error(universe):
    r = _llm(lambda req: httpx.Response(500), universe).analyze("Shares surge", "", ["AAPL"])
    assert r.model == "lexicon" and r.overall > 0


def test_llm_garbage_falls_back(universe):
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": "I think it's bullish!"}}]})

    assert _llm(handler, universe).analyze("x", "", ["AAPL"]).model == "lexicon"
