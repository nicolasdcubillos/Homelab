from __future__ import annotations

from datetime import UTC, datetime

from portfoliowatcher.state import SignalRecord, StateStore


def test_dedupe_seen_news(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        assert not state.is_seen("guid-1")
        state.mark_seen("guid-1", "AAPL", "google_news_rss")
        assert state.is_seen("guid-1")
        assert not state.is_seen("guid-2")


def test_filter_unseen(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        state.mark_seen("guid-1", "AAPL", "google_news_rss")
        items = [("guid-1", "AAPL", "google_news_rss"), ("guid-2", "AAPL", "google_news_rss")]
        unseen = state.filter_unseen(items)
        assert unseen == [("guid-2", "AAPL", "google_news_rss")]


def test_record_and_query_signals(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        signal_id = state.record_signal(
            SignalRecord(
                ticker="AAPL",
                signal_type="riesgo",
                severity="high",
                thesis="Litigio material anunciado.",
                prompt="prompt text",
                response='{"signal_type": "riesgo"}',
                model="gpt-5-6-sol",
                news_guid="guid-1",
            )
        )
        assert signal_id > 0
        rows = state.recent_signals(ticker="AAPL")
        assert len(rows) == 1
        assert rows[0]["signal_type"] == "riesgo"
        assert rows[0]["outcome_30d"] is None
        assert rows[0]["outcome_90d"] is None

        state.set_outcome(signal_id, outcome_30d="down 3%")
        rows = state.recent_signals(ticker="AAPL")
        assert rows[0]["outcome_30d"] == "down 3%"
        assert rows[0]["outcome_90d"] is None


def test_price_snapshots(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        assert state.last_price_snapshot("AAPL") is None
        state.record_price_snapshot("AAPL", 200.0, 195.0, "Technology")
        snap = state.last_price_snapshot("AAPL")
        assert snap["price"] == 200.0
        assert snap["sector"] == "Technology"


def test_full_analysis_tracking(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        assert state.last_full_analysis_at() is None
        now = datetime(2024, 1, 1, tzinfo=UTC)
        state.mark_full_analysis_run(now)
        assert state.last_full_analysis_at() == now


def test_state_persists_across_reopen(tmp_path):
    db_path = tmp_path / "state.db"
    with StateStore(db_path) as state:
        state.mark_seen("guid-1", "AAPL", "google_news_rss")

    with StateStore(db_path) as state:
        assert state.is_seen("guid-1")
