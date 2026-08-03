"""Byte-for-byte regression pin on analyze.compute()'s DAILY output.

WHY THIS FILE EXISTS
--------------------
`stock_analyser/analyze.py` is imported by THREE skills -- stock_analyser,
watchlist_analyser and stock_screener -- and only stock_screener has tests. Any
change to compute() can therefore regress two skills silently. This file is the
safety net that makes such a change reviewable: it pins the COMPLETE dict
compute() returns, for ten liquid Nifty names across ten sectors, and fails on
any difference anywhere in it.

WHAT "COMPLETE" MEANS HERE
--------------------------
Not a hand-picked subset of keys. `_diff` walks the whole structure -- every
nested dict, every list element, every float -- and reports the first path that
differs, and `test_canonical_json_is_byte_identical` additionally compares the
canonical serialisation of the entire result as bytes. A regression anywhere in
the twenty top-level keys, the eight volume nodes, the ten swing highs or the
seven pivots fails at least one of those two tests. Floats are compared with
`==` at full precision: no assertAlmostEqual, no places=, no tolerance. JSON
round-trips a Python float exactly (repr-based), so the recorded fixture holds
the same bits compute() produced.

WHY A RECORDED FIXTURE AND NOT A LIVE FETCH
-------------------------------------------
Scores move as the market does, so a fixture frozen from live *outputs* while
the test re-fetches live *inputs* would rot within a day and be deleted by the
first person it annoyed. The raw bars are snapshotted instead: `_BARS` holds the
exact `(rows, meta)` pairs Yahoo returned for each request compute() made on the
recording date, and the test drives compute() from those through a stub `fetch`.
Input and expected output are frozen together, so this test is deterministic
forever, needs no network, and answers exactly one question -- given identical
bars, does compute() still produce identical numbers.

The stub also RECORDS the requests. `test_daily_fetches_exactly_two_series`
asserts compute() asked for `2y/1d` and `5y/1wk`, in that order, and nothing
else; an unknown request raises rather than falling back, so a compute() that
started fetching a different range fails loudly instead of quietly serving
whatever the cache happened to hold.

REGENERATING
------------
Only ever when a change to compute()'s output is INTENDED, and never to make a
failing test pass:

    python3 tests/test_analyze_daily_regression.py --record

That hits the live Yahoo API, rewrites both fixture files, and the diff of
`fixtures_analyze_daily_expected.json` is then the reviewable statement of what
changed.
"""
import datetime as dt
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_HERE = os.path.dirname(os.path.abspath(__file__))
BARS_PATH = os.path.join(_HERE, "fixtures_analyze_daily_bars.json")
EXPECTED_PATH = os.path.join(_HERE, "fixtures_analyze_daily_expected.json")

# Ten liquid Nifty names, one per sector, chosen so the sample cannot be uniform
# in the way that has already produced a dozen unfailable assertions in this
# project: an oil major, a private bank, an IT major, a carmaker, a pharma name,
# an FMCG name, a metals cyclical, a capital-goods name, a telco and a utility
# trade on different volumes, different volatilities and different trends, so
# they exercise different arms of score_trend, score_volume and band().
SYMBOLS = ["RELIANCE", "HDFCBANK", "TCS", "MARUTI", "SUNPHARMA",
           "HINDUNILVR", "TATASTEEL", "LT", "BHARTIARTL", "NTPC"]

# The two requests today's compute() makes for one symbol, in the order it makes
# them. Stated here as data so the fetch-call test asserts against a declaration
# rather than against whatever the code did on the day.
DAILY_REQUESTS = [("2y", "1d"), ("5y", "1wk")]


def _key(symbol, rng, interval, suffix):
    return "|".join((symbol, rng, interval, suffix))


def _rows_to_json(rows):
    """Bar dicts -> compact arrays. The date becomes its ISO string."""
    return [[str(r["t"]), r["o"], r["h"], r["l"], r["c"], r["v"]] for r in rows]


def _rows_from_json(raw):
    return [{"t": dt.date(*(int(p) for p in row[0].split("-"))),
             "o": row[1], "h": row[2], "l": row[3], "c": row[4], "v": row[5]}
            for row in raw]


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


_BARS = _load(BARS_PATH) if os.path.exists(BARS_PATH) else {}
_EXPECTED = _load(EXPECTED_PATH) if os.path.exists(EXPECTED_PATH) else {}


class _StubFetch:
    """Serves the recorded bars and records what was asked for.

    An unrecorded request is an AssertionError, never a live fetch and never a
    fallback: the point of the fixture is that the INPUT is pinned too, and a
    silent fallback would let a compute() that changed its request keep passing
    against bars it never asked for.
    """

    def __init__(self, bars):
        self.bars = bars
        self.calls = []

    def __call__(self, symbol, rng, interval, suffix=".NS"):
        self.calls.append((symbol, rng, interval, suffix))
        key = _key(symbol, rng, interval, suffix)
        if key not in self.bars:
            raise AssertionError(
                "compute() requested %r, which the fixture does not hold. The "
                "recorded requests are %s. If this request is intended, "
                "re-record with --record; do not add a fallback." %
                (key, sorted(self.bars)))
        entry = self.bars[key]
        return _rows_from_json(entry["rows"]), entry["meta"]


def _canonical(obj):
    """One deterministic byte string for a whole result dict."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")


def _diff(got, want, path="$"):
    """First structural difference as a readable path, or None.

    Recursive and total: it descends every dict key and every list index, so
    there is no level of the result it does not reach. Floats compare with `==`
    -- exact bits, no tolerance, ever.
    """
    if isinstance(want, dict):
        if not isinstance(got, dict):
            return "%s: expected a dict, got %r" % (path, type(got).__name__)
        missing = sorted(set(want) - set(got))
        extra = sorted(set(got) - set(want))
        if missing:
            return "%s: keys missing from the result: %s" % (path, missing)
        if extra:
            return "%s: keys the pinned result does not have: %s" % (path, extra)
        for k in want:
            sub = _diff(got[k], want[k], "%s.%s" % (path, k))
            if sub:
                return sub
        return None
    if isinstance(want, list):
        if not isinstance(got, list):
            return "%s: expected a list, got %r" % (path, type(got).__name__)
        if len(got) != len(want):
            return "%s: length %d, pinned %d" % (path, len(got), len(want))
        for i, (g, w) in enumerate(zip(got, want)):
            sub = _diff(g, w, "%s[%d]" % (path, i))
            if sub:
                return sub
        return None
    if isinstance(want, bool) or isinstance(got, bool):
        # bool IS an int in Python: without this arm True would compare equal to
        # 1 and a flag that turned into a count would slip through.
        if type(got) is not type(want) or got != want:
            return "%s: %r, pinned %r" % (path, got, want)
        return None
    if got != want:
        return "%s: %r, pinned %r" % (path, got, want)
    return None


def _computed(symbol):
    """compute(symbol, catalyst=5.0) driven off the recorded bars.

    Returns (result, stub) so a caller can also inspect the requests made.
    """
    import engine
    analyze = engine.A
    stub = _StubFetch(_BARS)
    original = analyze.fetch
    analyze.fetch = stub
    try:
        return analyze.compute(symbol, catalyst=5.0), stub
    finally:
        analyze.fetch = original


class TestFixtureIntegrity(unittest.TestCase):
    """The net is only a net if it actually holds the whole sample."""

    def test_both_fixtures_exist_and_cover_every_symbol(self):
        self.assertTrue(_BARS, "bar fixture missing -- run with --record")
        self.assertTrue(_EXPECTED, "expected fixture missing -- run --record")
        self.assertEqual(sorted(_EXPECTED), sorted(SYMBOLS))
        for sym in SYMBOLS:
            for rng, interval in DAILY_REQUESTS:
                self.assertIn(_key(sym, rng, interval, ".NS"), _BARS)

    def test_sample_is_at_least_eight_names(self):
        self.assertGreaterEqual(len(SYMBOLS), 8)
        self.assertEqual(len(set(SYMBOLS)), len(SYMBOLS))

    def test_each_series_carries_real_history(self):
        """A fixture of ten bars would pin nothing: every 200-period average,
        every 250-bar 52-week window and every 126-bar ATR percentile would be
        None and the pin would assert that None stayed None."""
        for sym in SYMBOLS:
            daily = _BARS[_key(sym, "2y", "1d", ".NS")]["rows"]
            weekly = _BARS[_key(sym, "5y", "1wk", ".NS")]["rows"]
            self.assertGreaterEqual(len(daily), 250, sym)
            self.assertGreaterEqual(len(weekly), 200, sym)

    def test_the_sample_is_not_uniform(self):
        """Guards the failure mode this project has already shipped: a fixture
        so uniform that whole families of assertions cannot fail.

        Every one of these reads a DIFFERENT arm of compute(), and each is only
        satisfiable if the ten names genuinely disagree with each other."""
        pinned = [_EXPECTED[s] for s in SYMBOLS]
        self.assertGreater(len({p["score"]["verdict"] for p in pinned}), 1,
                           "every name lands in the same verdict band")
        self.assertGreater(len({round(p["score"]["trend"], 4) for p in pinned}), 1,
                           "score_trend returns one value for the whole sample")
        self.assertGreater(len({round(p["score"]["volume"], 4) for p in pinned}), 1,
                           "score_volume returns one value for the whole sample")
        self.assertGreater(len({round(p["score"]["momentum"], 4) for p in pinned}), 1,
                           "score_momentum returns one value for the whole sample")
        self.assertGreater(len({round(p["score"]["volatility"], 4) for p in pinned}), 1,
                           "score_volatility returns one value for the whole sample")
        self.assertTrue(any(p["volume"]["thrusts"] for p in pinned),
                        "no name in the sample has a volume thrust")
        self.assertTrue(any(p["rejection_zones"] for p in pinned),
                        "no name in the sample has a rejection zone")
        self.assertTrue(any(p["entry_gate"]["rr_at_current_price"] is not None
                            for p in pinned), "no name has a measurable R:R")


class TestDailyComputeIsPinned(unittest.TestCase):
    """compute(sym, catalyst=5.0) against the frozen bars, in full."""

    def test_every_symbol_matches_the_pin_structurally(self):
        for sym in SYMBOLS:
            with self.subTest(symbol=sym):
                got, _ = _computed(sym)
                # default=str only touches the datetime.date inside
                # last_closed_bar, which the pin already holds as a string.
                got = json.loads(json.dumps(got, default=str))
                diff = _diff(got, _EXPECTED[sym])
                self.assertIsNone(diff, "%s: %s" % (sym, diff))

    def test_canonical_json_is_byte_identical(self):
        """The byte-for-byte claim, made on bytes.

        _diff can only report the FIRST difference; this asserts the whole
        serialisation at once, so the two together mean "nothing anywhere
        changed" rather than "the thing I looked at did not change".
        """
        for sym in SYMBOLS:
            with self.subTest(symbol=sym):
                got, _ = _computed(sym)
                self.assertEqual(_canonical(got), _canonical(_EXPECTED[sym]))

    def test_floats_are_pinned_at_full_precision(self):
        """No rounding, no tolerance: the pinned total must be the exact float.

        Written as its own test because a tolerance introduced into _diff would
        otherwise be invisible -- this one compares a specific full-precision
        float with `==` and with repr, and dies if either loosens.
        """
        for sym in SYMBOLS:
            with self.subTest(symbol=sym):
                got, _ = _computed(sym)
                self.assertEqual(got["score"]["total"],
                                 _EXPECTED[sym]["score"]["total"])
                self.assertEqual(repr(got["score"]["total"]),
                                 repr(_EXPECTED[sym]["score"]["total"]))
                self.assertEqual(repr(got["price"]), repr(_EXPECTED[sym]["price"]))

    def test_daily_fetches_exactly_two_series(self):
        """2y/1d then 5y/1wk, in that order, and nothing else.

        The requests are as much of today's daily behaviour as the numbers are:
        a compute() that fetched a 10y weekly primary would produce different
        numbers, but one that fetched an EXTRA series would not, and this is the
        assertion that sees it.
        """
        for sym in SYMBOLS:
            with self.subTest(symbol=sym):
                _, stub = _computed(sym)
                self.assertEqual(stub.calls,
                                 [(sym, rng, interval, ".NS")
                                  for rng, interval in DAILY_REQUESTS])

    def test_an_unrecorded_request_fails_loudly(self):
        """The stub must not degrade to a fallback -- otherwise a compute() that
        changed its request would keep passing against bars it never asked for.
        """
        stub = _StubFetch(_BARS)
        with self.assertRaises(AssertionError):
            stub("RELIANCE", "10y", "1wk")

    def test_the_pin_would_notice_a_changed_number(self):
        """The net catches something. A pin nobody has ever seen fail is a pin
        nobody can trust: perturb one deep float and assert both comparisons
        report it."""
        import copy
        mutated = copy.deepcopy(_EXPECTED["RELIANCE"])
        mutated["pivots_next_session"]["R2"] += 1e-9
        self.assertIsNotNone(_diff(mutated, _EXPECTED["RELIANCE"]))
        self.assertNotEqual(_canonical(mutated),
                            _canonical(_EXPECTED["RELIANCE"]))


# ------------------------------------------------------------------ recording

def _record():                              # pragma: no cover - operator tool
    """Re-snapshot bars AND expected output together, from the live API."""
    sys.path.insert(0, os.path.dirname(_HERE))
    import engine
    analyze = engine.A

    bars, expected = {}, {}
    real = analyze.fetch

    def recording_fetch(symbol, rng, interval, suffix=".NS"):
        rows, meta = real(symbol, rng, interval, suffix)
        bars[_key(symbol, rng, interval, suffix)] = {
            "rows": _rows_to_json(rows), "meta": meta}
        return rows, meta

    analyze.fetch = recording_fetch
    try:
        for sym in SYMBOLS:
            expected[sym] = json.loads(
                json.dumps(analyze.compute(sym, catalyst=5.0), default=str))
            print("recorded %s" % sym)
    finally:
        analyze.fetch = real

    with open(BARS_PATH, "w", encoding="utf-8") as fh:
        json.dump(bars, fh, sort_keys=True, separators=(",", ":"))
        fh.write("\n")
    with open(EXPECTED_PATH, "w", encoding="utf-8") as fh:
        json.dump(expected, fh, sort_keys=True, indent=1)
        fh.write("\n")
    print("wrote %s and %s" % (BARS_PATH, EXPECTED_PATH))


if __name__ == "__main__":
    if "--record" in sys.argv:
        _record()
    else:
        unittest.main()
