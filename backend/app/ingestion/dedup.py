"""Near-duplicate detection with SimHash.

The same Reuters story gets syndicated to dozens of sites with tiny title changes.
Counting each copy would massively over-weight one event, so we fingerprint titles
with a 64-bit SimHash: similar texts -> fingerprints that differ in only a few bits.
"""

import hashlib
import re

WORD_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    """
a an the of to in on for and or is are was were be by at as with from its it this that
""".split()
)
MASK64 = (1 << 64) - 1


def tokens(text: str) -> list[str]:
    return [w for w in WORD_RE.findall(text.lower()) if w not in STOPWORDS]


def shingles(text: str, k: int = 2) -> list[str]:
    toks = tokens(text)
    if len(toks) < k:
        return toks
    return [" ".join(toks[i : i + k]) for i in range(len(toks) - k + 1)]


def _hash64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")


def simhash(text: str) -> int:
    """Return an unsigned 64-bit SimHash."""
    feats = shingles(text) + tokens(text)
    if not feats:
        return 0
    v = [0] * 64
    for f in feats:
        h = _hash64(f)
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if v[i] > 0:
            out |= 1 << i
    return out


def to_signed(x: int) -> int:
    """Postgres BIGINT is signed; store the same 64 bits as a signed integer."""
    return x - (1 << 64) if x >= (1 << 63) else x


def to_unsigned(x: int) -> int:
    return x & MASK64


def hamming(a: int, b: int) -> int:
    return bin(to_unsigned(a) ^ to_unsigned(b)).count("1")


class NearDuplicateIndex:
    """In-memory index of recent fingerprints. Linear scan is fine for a few thousand articles/day."""

    def __init__(self, threshold: int = 3, existing: list[int] | None = None):
        self.threshold = threshold
        self._hashes: list[int] = [to_unsigned(h) for h in (existing or [])]

    def is_duplicate(self, h: int) -> bool:
        h = to_unsigned(h)
        return any(hamming(h, other) <= self.threshold for other in self._hashes)

    def add(self, h: int) -> None:
        self._hashes.append(to_unsigned(h))
