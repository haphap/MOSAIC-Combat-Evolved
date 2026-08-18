"""Tests for ``mosaic.dataflows.fred``.

Two layers:

1. **Offline** — fast, deterministic. Mocks ``requests.get`` so the suite runs
   anywhere without network or API key. Covers input validation, JSON
   parsing, CSV serialisation, disk cache hit/miss, and rate-limiter
   sliding-window correctness.

2. **Live integration** — only runs when ``FRED_API_KEY`` is set in the
   environment. Pulls ``FEDFUNDS`` / ``DGS10`` / ``DTWEXBGS`` / ``VIXCLS``
   for a 30-day window and asserts non-empty CSV output. Also exercised
   by ``python -m pytest tests/test_fred.py -k live``.
"""

from __future__ import annotations

import json
import os
import time
from unittest import mock

import pandas as pd
import pytest
import requests

from mosaic.dataflows import fred
from mosaic.dataflows.config import set_config
from mosaic.dataflows.exceptions import DataVendorUnavailable


# --------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """Point FRED's data_cache_dir at a tmp dir + reset the limiter per-test."""
    set_config({"data_cache_dir": str(tmp_path)})
    # Reset the rate limiter state so test order doesn't matter.
    fred._rate_limiter = fred._SlidingWindowLimiter(
        fred.RATE_LIMIT_REQUESTS, fred.RATE_LIMIT_WINDOW_SECONDS
    )
    yield
    # Restore default config for downstream tests
    set_config({})


@pytest.fixture
def fake_payload():
    return {
        "observations": [
            {"date": "2024-01-01", "value": "5.33"},
            {"date": "2024-02-01", "value": "5.33"},
            {"date": "2024-03-01", "value": "."},          # missing -> None / NaN
            {"date": "2024-04-01", "value": "5.33"},
            {"date": "2024-05-01", "value": "5.33"},
            {"date": "2024-06-01", "value": "5.33"},
        ]
    }


@pytest.fixture
def mock_response_factory():
    """Build a ``mock.MagicMock`` shaped like a ``requests.Response``."""

    def _make(payload, status_code=200, raises=None):
        response = mock.MagicMock()
        response.status_code = status_code
        if raises is not None:
            response.raise_for_status.side_effect = raises
            response.json.return_value = payload
        else:
            response.raise_for_status.return_value = None
            response.json.return_value = payload
        return response

    return _make


# --------------------------------------------------------------------- input validation


class TestValidation:
    def test_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        with pytest.raises(DataVendorUnavailable, match="FRED_API_KEY"):
            fred.get_fred_series("FEDFUNDS", "2024-01-01", "2024-06-30")

    def test_empty_series_id(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        with pytest.raises(DataVendorUnavailable, match="non-empty string"):
            fred.get_fred_series("", "2024-01-01", "2024-06-30")

    @pytest.mark.parametrize(
        "bad_date",
        ["2024/01/01", "Jan 1 2024", "20240101"],
    )
    def test_invalid_date_format(self, monkeypatch, bad_date):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        with pytest.raises(DataVendorUnavailable, match="YYYY-MM-DD"):
            fred.get_fred_series("FEDFUNDS", bad_date, "2024-06-30")


# --------------------------------------------------------------------- HTTP / parsing


class TestFetch:
    def test_csv_output_shape(self, monkeypatch, fake_payload, mock_response_factory):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        with mock.patch.object(
            fred.requests, "get", return_value=mock_response_factory(fake_payload)
        ) as mocked:
            csv_text = fred.get_fred_series("FEDFUNDS", "2024-01-01", "2024-06-30")

        assert mocked.call_count == 1
        assert csv_text.startswith("# FRED series FEDFUNDS, 2024-01-01 to 2024-06-30")
        # 1 header line + 6 data rows + trailing newline
        lines = [ln for ln in csv_text.splitlines() if ln]
        assert lines[1] == "date,value"
        assert lines[2] == "2024-01-01,5.33"
        # Missing value emitted as empty cell
        assert any(ln == "2024-03-01," for ln in lines)

    def test_dataframe_output(self, monkeypatch, fake_payload, mock_response_factory):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        with mock.patch.object(
            fred.requests, "get", return_value=mock_response_factory(fake_payload)
        ):
            df = fred._fetch_series_dataframe("FEDFUNDS", "2024-01-01", "2024-06-30")

        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["date", "value"]
        assert len(df) == 6
        # Missing value parsed as NaN
        assert df.loc[df["date"] == "2024-03-01", "value"].isna().all()
        # Real values preserved
        assert (df.loc[df["date"] == "2024-01-01", "value"] == 5.33).all()

    def test_fred_returns_error_payload(self, monkeypatch, mock_response_factory):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        err_payload = {"error_code": 400, "error_message": "Bad Request. Series does not exist."}
        with mock.patch.object(
            fred.requests, "get", return_value=mock_response_factory(err_payload)
        ):
            out = fred.get_fred_series("NONSENSE", "2024-01-01", "2024-06-30")

        assert out.startswith("# FRED series NONSENSE, 2024-01-01 to 2024-06-30")
        assert "# FRED unavailable:" in out
        assert out.rstrip().endswith("date,value")

    def test_http_failure_wraps_to_data_vendor_unavailable(
        self, monkeypatch, mock_response_factory
    ):
        import requests as real_requests

        monkeypatch.setenv("FRED_API_KEY", "fake")
        with mock.patch.object(
            fred.requests,
            "get",
            return_value=mock_response_factory(
                None, status_code=500, raises=real_requests.HTTPError("500 Server Error")
            ),
        ):
            out = fred.get_fred_series("FEDFUNDS", "2024-01-01", "2024-06-30")

        assert out.startswith("# FRED series FEDFUNDS, 2024-01-01 to 2024-06-30")
        assert "# FRED unavailable:" in out
        assert out.rstrip().endswith("date,value")

    def test_http_400_returns_empty_csv_and_redacts_api_key(
        self, monkeypatch, mock_response_factory
    ):
        import requests as real_requests

        monkeypatch.setenv("FRED_API_KEY", "fake-secret")
        url = (
            "https://api.stlouisfed.org/fred/series/observations?"
            "series_id=BAD&api_key=fake-secret&file_type=json"
        )
        with mock.patch.object(
            fred.requests,
            "get",
            return_value=mock_response_factory(
                None,
                status_code=400,
                raises=real_requests.HTTPError(
                    f"400 Client Error: Bad Request for url: {url}"
                ),
            ),
        ):
            out = fred.get_fred_series("BAD", "2024-01-01", "2024-06-30")

        assert "fake-secret" not in out
        assert "api_key=<redacted>" in out
        assert out.rstrip().endswith("date,value")


# --------------------------------------------------------------------- exact ALFRED vintage


class TestExactAlfredVintage:
    def test_unregistered_series_is_rejected_without_network(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        with mock.patch.object(fred.requests, "get") as mocked:
            with pytest.raises(DataVendorUnavailable, match="unregistered ALFRED"):
                fred.get_alfred_vintage(
                    "INVENTED",
                    observation_start="2024-01-01",
                    observation_end="2024-06-30",
                    vintage_date="2024-06-30",
                )
        mocked.assert_not_called()

    def test_cutoff_selects_only_a_prior_complete_vintage_date(
        self, monkeypatch, mock_response_factory
    ):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        with mock.patch.object(
            fred.requests,
            "get",
            return_value=mock_response_factory({"vintage_dates": ["2024-06-30"]}),
        ) as mocked:
            selected = fred.select_alfred_vintage(
                "GDPC1", as_of_cutoff="2024-07-01T15:00:00+08:00"
            )

        assert selected == "2024-06-30"
        assert mocked.call_args.args[0].endswith("/series/vintagedates")
        params = mocked.call_args.kwargs["params"]
        assert params["series_id"] == "GDPC1"
        assert params["realtime_end"] == "2024-06-30"
        assert params["sort_order"] == "desc"
        assert params["limit"] == 1

    def test_exact_vintage_request_is_strict_and_metadata_preserving(
        self, monkeypatch, mock_response_factory
    ):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        payload = {
            "realtime_start": "2024-06-30",
            "realtime_end": "2024-06-30",
            "observations": [
                {
                    "realtime_start": "2024-06-30",
                    "realtime_end": "2024-06-30",
                    "date": "2024-01-01",
                    "value": "22960.6",
                }
            ],
        }
        with mock.patch.object(
            fred.requests, "get", return_value=mock_response_factory(payload)
        ) as mocked:
            result = fred.get_alfred_vintage(
                "GDPC1",
                observation_start="2024-01-01",
                observation_end="2024-06-30",
                vintage_date="2024-06-30",
            )

        assert result == payload
        params = mocked.call_args.kwargs["params"]
        assert "realtime_start" not in params
        assert "realtime_end" not in params
        assert params["vintage_dates"] == "2024-06-30"
        assert params["observation_start"] == "2024-01-01"
        assert params["observation_end"] == "2024-06-30"

    def test_exact_vintage_retries_one_transient_timeout(
        self, monkeypatch, mock_response_factory
    ):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        payload = {
            "observations": [
                {
                    "realtime_start": "2024-06-30",
                    "realtime_end": "2024-06-30",
                    "date": "2024-01-01",
                    "value": "22960.6",
                }
            ]
        }
        with mock.patch.object(
            fred.requests,
            "get",
            side_effect=[
                requests.ReadTimeout("private timeout detail"),
                mock_response_factory(payload),
            ],
        ) as mocked, mock.patch.object(fred.time, "sleep") as slept:
            result = fred.get_alfred_vintage(
                "GDPC1",
                observation_start="2024-01-01",
                observation_end="2024-06-30",
                vintage_date="2024-06-30",
            )

        assert result == payload
        assert mocked.call_count == 2
        slept.assert_called_once_with(fred.REQUEST_BACKOFF_SECONDS[0])

    def test_strict_path_rejects_provider_error_and_empty_observations(
        self, monkeypatch, mock_response_factory
    ):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        responses = [
            mock_response_factory(
                {"error_code": 400, "error_message": "series does not exist"}
            ),
            mock_response_factory({"observations": []}),
        ]
        with mock.patch.object(fred.requests, "get", side_effect=responses):
            with pytest.raises(DataVendorUnavailable, match="returned error"):
                fred.get_alfred_vintage(
                    "GDPC1",
                    observation_start="2024-01-01",
                    observation_end="2024-06-30",
                    vintage_date="2024-06-30",
                )
            with pytest.raises(DataVendorUnavailable, match="no observations"):
                fred.get_alfred_vintage(
                    "GDPC1",
                    observation_start="2024-01-01",
                    observation_end="2024-06-30",
                    vintage_date="2024-06-29",
                )

    def test_exact_vintage_cache_identity_includes_vintage_date(
        self, monkeypatch, mock_response_factory
    ):
        monkeypatch.setenv("FRED_API_KEY", "fake")

        def payload(vintage_date: str, value: str):
            return {
                "observations": [
                    {
                        "realtime_start": vintage_date,
                        "realtime_end": vintage_date,
                        "date": "2024-01-01",
                        "value": value,
                    }
                ]
            }

        with mock.patch.object(
            fred.requests,
            "get",
            side_effect=[
                mock_response_factory(payload("2024-06-29", "1.0")),
                mock_response_factory(payload("2024-06-30", "2.0")),
            ],
        ) as mocked:
            first = fred.get_alfred_vintage(
                "GDPC1",
                observation_start="2024-01-01",
                observation_end="2024-06-30",
                vintage_date="2024-06-29",
            )
            assert fred.get_alfred_vintage(
                "GDPC1",
                observation_start="2024-01-01",
                observation_end="2024-06-30",
                vintage_date="2024-06-29",
            ) == first
            second = fred.get_alfred_vintage(
                "GDPC1",
                observation_start="2024-01-01",
                observation_end="2024-06-30",
                vintage_date="2024-06-30",
            )

        assert first != second
        assert mocked.call_count == 2
        assert len(list(fred._cache_dir().glob("ALFRED_*.json"))) == 2


# --------------------------------------------------------------------- caching


class TestCache:
    def test_cache_hit_skips_network(
        self, monkeypatch, fake_payload, mock_response_factory
    ):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        with mock.patch.object(
            fred.requests, "get", return_value=mock_response_factory(fake_payload)
        ) as mocked:
            fred.get_fred_series("FEDFUNDS", "2024-01-01", "2024-06-30")
            fred.get_fred_series("FEDFUNDS", "2024-01-01", "2024-06-30")
            fred.get_fred_series("FEDFUNDS", "2024-01-01", "2024-06-30")
        # Only one network call despite three reads
        assert mocked.call_count == 1

    def test_cache_path_layout(self, monkeypatch, fake_payload, mock_response_factory):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        with mock.patch.object(
            fred.requests, "get", return_value=mock_response_factory(fake_payload)
        ):
            fred.get_fred_series("fedfunds", "2024-01-01", "2024-06-30")  # lowercase

        cache_dir = fred._cache_dir()
        files = list(cache_dir.glob("*.json"))
        assert len(files) == 1
        # Cache key should normalize series_id to upper-case
        assert files[0].name == "FEDFUNDS_2024-01-01_2024-06-30.json"
        # And the payload on disk is exactly what FRED sent
        assert json.loads(files[0].read_text()) == fake_payload

    def test_clear_cache_removes_files(
        self, monkeypatch, fake_payload, mock_response_factory
    ):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        with mock.patch.object(
            fred.requests, "get", return_value=mock_response_factory(fake_payload)
        ):
            fred.get_fred_series("FEDFUNDS", "2024-01-01", "2024-06-30")
            fred.get_fred_series("DGS10", "2024-01-01", "2024-06-30")

        deleted = fred.clear_cache()
        assert deleted == 2
        assert not list(fred._cache_dir().glob("*.json"))

    def test_stale_cache_is_refetched(
        self, monkeypatch, fake_payload, mock_response_factory
    ):
        monkeypatch.setenv("FRED_API_KEY", "fake")
        with mock.patch.object(
            fred.requests, "get", return_value=mock_response_factory(fake_payload)
        ) as mocked:
            fred.get_fred_series("FEDFUNDS", "2024-01-01", "2024-06-30")
            assert mocked.call_count == 1

            # Backdate the cache file beyond TTL
            cache_path = next(fred._cache_dir().glob("*.json"))
            old_time = time.time() - fred.CACHE_TTL_SECONDS - 60
            os.utime(cache_path, (old_time, old_time))

            fred.get_fred_series("FEDFUNDS", "2024-01-01", "2024-06-30")
            assert mocked.call_count == 2  # refetched


# --------------------------------------------------------------------- rate limiter


class TestRateLimiter:
    def test_under_capacity_does_not_sleep(self):
        limiter = fred._SlidingWindowLimiter(max_calls=3, window_seconds=10.0)
        start = time.monotonic()
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.05, f"expected near-zero, got {elapsed:.3f}s"

    def test_over_capacity_blocks_until_window_clears(self, monkeypatch):
        # Tight window so the test runs fast.
        limiter = fred._SlidingWindowLimiter(max_calls=2, window_seconds=0.2)

        sleeps: list[float] = []
        original_sleep = time.sleep
        monkeypatch.setattr(time, "sleep", lambda d: sleeps.append(d) or original_sleep(d))

        limiter.acquire()
        limiter.acquire()
        # Third call must wait until at least one of the prior two falls outside the window.
        limiter.acquire()

        assert sleeps, "expected the limiter to call time.sleep once over capacity"
        assert sleeps[0] > 0


# --------------------------------------------------------------------- live integration


_LIVE_SERIES = ["FEDFUNDS", "DGS10", "DTWEXBGS", "VIXCLS"]


@pytest.mark.skipif(
    not os.getenv("FRED_API_KEY"),
    reason="set FRED_API_KEY to run live FRED integration tests",
)
@pytest.mark.parametrize("series_id", _LIVE_SERIES)
def test_live_fetch(series_id):
    """Real network call. Only runs when FRED_API_KEY is set."""
    csv_text = fred.get_fred_series(series_id, "2024-01-01", "2024-01-31")
    assert csv_text.startswith(f"# FRED series {series_id}, ")
    body = csv_text.splitlines()[2:]
    assert body, f"no observations returned for {series_id}"
    assert any(line.startswith("2024-") for line in body)
