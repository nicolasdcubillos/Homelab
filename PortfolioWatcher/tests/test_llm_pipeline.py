from __future__ import annotations

import json
from datetime import UTC, datetime

from portfoliowatcher.config import AzureOpenAIConfig
from portfoliowatcher.llm_pipeline import LLMPipeline
from portfoliowatcher.news_ingestion import NewsItem
from portfoliowatcher.state import StateStore


class FakeLLMClient:
    """Mocked LLM client — returns scripted JSON responses, no network calls."""

    def __init__(self, responses: dict[str, str]) -> None:
        # keyed by model name, so triage and analysis can be scripted independently
        self.responses = responses
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, model: str) -> str:
        self.calls.append({"system": system, "user": user, "model": model})
        return self.responses[model]


def _news_item(guid: str = "guid-1") -> NewsItem:
    return NewsItem(
        ticker="AAPL",
        source="google_news_rss",
        guid=guid,
        title="Apple sued over patent dispute",
        link="https://example.com/news/1",
        published_at=datetime(2024, 1, 1, tzinfo=UTC),
        summary="A material lawsuit was filed against Apple.",
    )


def _config() -> AzureOpenAIConfig:
    return AzureOpenAIConfig(
        endpoint="https://example.openai.azure.com",
        api_key="fake-key",
        triage_deployment="gpt-5-6-luna",
        analysis_deployment="gpt-5-6-sol",
    )


def test_triage_discards_noise():
    client = FakeLLMClient(
        {"gpt-5-6-luna": json.dumps({"relevant": False, "reason": "marketing fluff"})}
    )
    pipeline = LLMPipeline(client, _config())
    result = pipeline.triage(_news_item())
    assert result.relevant is False
    assert result.reason == "marketing fluff"


def test_analyze_persists_signal_to_state(tmp_path):
    client = FakeLLMClient(
        {
            "gpt-5-6-sol": json.dumps(
                {
                    "signal_type": "riesgo",
                    "severity": "high",
                    "thesis": "Demanda por patente podría afectar ingresos.",
                }
            )
        }
    )
    with StateStore(tmp_path / "state.db") as state:
        pipeline = LLMPipeline(client, _config(), state=state)
        result = pipeline.analyze(_news_item())

        assert result.signal_type == "riesgo"
        assert result.severity == "high"
        assert "patente" in result.thesis

        rows = state.recent_signals(ticker="AAPL")
        assert len(rows) == 1
        assert rows[0]["signal_type"] == "riesgo"
        assert rows[0]["model"] == "gpt-5-6-sol"
        assert rows[0]["outcome_30d"] is None


def test_process_items_runs_triage_before_analysis(tmp_path):
    client = FakeLLMClient(
        {
            "gpt-5-6-luna": json.dumps({"relevant": True, "reason": "material"}),
            "gpt-5-6-sol": json.dumps(
                {"signal_type": "oportunidad", "severity": "medium", "thesis": "Upgrade emitido."}
            ),
        }
    )
    with StateStore(tmp_path / "state.db") as state:
        pipeline = LLMPipeline(client, _config(), state=state)
        results = pipeline.process_items([_news_item()])

    assert len(results) == 1
    assert results[0].signal_type == "oportunidad"
    # both tiers were called exactly once
    models_called = [call["model"] for call in client.calls]
    assert models_called == ["gpt-5-6-luna", "gpt-5-6-sol"]


def test_process_items_skips_analysis_when_triage_discards():
    client = FakeLLMClient(
        {"gpt-5-6-luna": json.dumps({"relevant": False, "reason": "not material"})}
    )
    pipeline = LLMPipeline(client, _config())
    results = pipeline.process_items([_news_item()])
    assert results == []
    assert len(client.calls) == 1  # analysis tier never called


def test_weekly_report_uses_analysis_model():
    client = FakeLLMClient({"gpt-5-6-sol": "Resumen ejecutivo del portafolio."})
    pipeline = LLMPipeline(client, _config())
    narrative = pipeline.weekly_report("Holdings: AAPL, MSFT")
    assert narrative == "Resumen ejecutivo del portafolio."
    assert client.calls[0]["model"] == "gpt-5-6-sol"


def test_safe_json_handles_markdown_fences():
    client = FakeLLMClient(
        {"gpt-5-6-luna": "```json\n" + json.dumps({"relevant": True, "reason": "ok"}) + "\n```"}
    )
    pipeline = LLMPipeline(client, _config())
    result = pipeline.triage(_news_item())
    assert result.relevant is True
