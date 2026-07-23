import os
from unittest.mock import patch

import pandas as pd

from sol_backtest.data import fetcher


def _candle(t, price):
    return {"time": t, "open": price, "high": price, "low": price, "close": price, "volume": 1}


def test_fetch_candles_paginates_across_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "CACHE_DIR", str(tmp_path))
    monkeypatch.setitem(fetcher.RESOLUTION_SECONDS, "1h", 3600)
    monkeypatch.setattr(fetcher, "MAX_CANDLES_PER_REQUEST", 2)

    # start=0, end=4*3600 with step = 3600*2 = 7200 -> two chunks: [0,7200), [7200,14400)
    calls = []

    def fake_fetch_chunk(base_url, symbol, resolution, start, end, retries=3, backoff=1.0):
        calls.append((start, end))
        if start == 0:
            return [_candle(0, 100), _candle(3600, 101)]
        return [_candle(7200, 102), _candle(10800, 103)]

    with patch.object(fetcher, "_fetch_chunk", side_effect=fake_fetch_chunk):
        df = fetcher.fetch_candles(
            base_url="https://example.test", symbol="SOLUSD", resolution="1h",
            start=0, end=4 * 3600, use_cache=True, request_pause_sec=0,
        )

    assert len(calls) == 2
    assert list(df["time"]) == [0, 3600, 7200, 10800]
    assert list(df["close"]) == [100.0, 101.0, 102.0, 103.0]


def test_fetch_candles_uses_cache_on_second_call(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "CACHE_DIR", str(tmp_path))

    call_count = {"n": 0}

    def fake_fetch_chunk(base_url, symbol, resolution, start, end, retries=3, backoff=1.0):
        call_count["n"] += 1
        return [_candle(0, 100), _candle(3600, 101)]

    with patch.object(fetcher, "_fetch_chunk", side_effect=fake_fetch_chunk):
        fetcher.fetch_candles("https://example.test", "SOLUSD", "1h", 0, 7200, use_cache=True, request_pause_sec=0)
        fetcher.fetch_candles("https://example.test", "SOLUSD", "1h", 0, 7200, use_cache=True, request_pause_sec=0)

    assert call_count["n"] == 1  # second call hit the cache


def test_fetch_candles_rejects_bad_range():
    import pytest
    with pytest.raises(ValueError):
        fetcher.fetch_candles("https://example.test", "SOLUSD", "1h", start=100, end=50)
