from app.ingestion.dedup import NearDuplicateIndex, hamming, simhash, to_signed, to_unsigned


def test_identical_text_same_hash():
    assert simhash("Infosys wins big deal") == simhash("Infosys wins big deal")


def test_near_duplicate_titles_are_close():
    a = simhash("Infosys bags record $2 billion deal, shares surge")
    b = simhash("Infosys bags record $2 billion deal; shares surge")
    c = simhash("Oil prices jump after OPEC+ cut announced")
    assert hamming(a, b) <= 3
    assert hamming(a, c) > 10


def test_signed_roundtrip():
    h = simhash("anything at all here")
    assert to_unsigned(to_signed(h)) == h
    assert -(1 << 63) <= to_signed(h) < (1 << 63)


def test_index():
    idx = NearDuplicateIndex(threshold=3)
    h = simhash("Fed holds rates steady as inflation cools")
    assert not idx.is_duplicate(h)
    idx.add(h)
    assert idx.is_duplicate(simhash("Fed holds rates steady as inflation cools"))
