"""Two-tier LLM pipeline over Azure OpenAI: cheap triage, then deep analysis.

Tier 1 ("triage", deployment ``gpt-5-6-luna`` by default) discards noise from
raw news items cheaply. Tier 2 ("analysis", deployment ``gpt-5-6-sol`` by
default) only processes what survived triage: it classifies each item into
``riesgo | oportunidad | ruido``, assigns a severity, and writes a short
grounded thesis. The same "analysis" tier also drafts the full weekly
portfolio report.

Every prompt/response pair is persisted to the state store (see
:mod:`portfoliowatcher.state`) so it can be backtested later — the
``outcome_30d``/``outcome_90d`` fields start empty and are filled in manually
or by a future follow-up script.

IMPORTANT — this module and its prompts NEVER instruct the model to
recommend buying/selling automatically or to place trades. Output is always
framed as informational context for a human to evaluate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from .config import AzureOpenAIConfig
from .news_ingestion import NewsItem

log = logging.getLogger(__name__)

PROMPT_VERSION = "v1"

SYSTEM_PROMPT_DISCLAIMER = (
    "Eres un asistente de análisis de portafolio de inversión a largo plazo. "
    "NUNCA recomiendas comprar ni vender una acción de forma directa, ni "
    "ejecutas ni simulas ejecutar órdenes. Tu única función es señalar "
    "riesgos u oportunidades informativas, con contexto y severidad, para que "
    "un humano decida. Si no hay evidencia suficiente, clasifica como 'ruido'."
)

TRIAGE_SYSTEM_PROMPT = (
    f"{SYSTEM_PROMPT_DISCLAIMER}\n\n"
    "Tarea (triaje, " + PROMPT_VERSION + "): dado un titular/resumen de noticia o "
    "filing SEC de un ticker en un portafolio de largo plazo, decide si es "
    "'relevante' (podría afectar materialmente la tesis de inversión: "
    "resultados financieros, litigios, cambios regulatorios, downgrades/"
    "upgrades, movimientos de precio significativos, nuevas líneas de "
    "negocio) o 'ruido' (marketing, rumores sin fuente, contenido repetido, "
    "trivia). Responde SOLO con JSON: {\"relevant\": true|false, \"reason\": "
    "\"...\"}."
)

ANALYSIS_SYSTEM_PROMPT = (
    f"{SYSTEM_PROMPT_DISCLAIMER}\n\n"
    "Tarea (análisis, " + PROMPT_VERSION + "): dado un item de noticia/filing "
    "que sobrevivió el triaje, clasifícalo en 'riesgo', 'oportunidad' o "
    "'ruido', asigna severidad ('low', 'medium', 'high') y redacta una tesis "
    "corta de 2-3 líneas fundamentada en el contenido dado. Responde SOLO "
    "con JSON: {\"signal_type\": \"riesgo|oportunidad|ruido\", \"severity\": "
    "\"low|medium|high\", \"thesis\": \"...\"}."
)

WEEKLY_REPORT_SYSTEM_PROMPT = (
    f"{SYSTEM_PROMPT_DISCLAIMER}\n\n"
    "Tarea (informe semanal, " + PROMPT_VERSION + "): con el estado del "
    "portafolio (holdings, pesos, sectores, señales recientes) redacta un "
    "informe ejecutivo breve en español: concentración sectorial, fundamentales "
    "recientes relevantes, y un resumen de señales de riesgo/oportunidad de la "
    "semana. No incluyas ninguna recomendación de compra/venta directa."
)


class LLMClient(Protocol):
    """Minimal interface the pipeline needs — implemented by AzureOpenAIClient or a test double."""

    def complete(self, *, system: str, user: str, model: str) -> str: ...


@dataclass
class TriageResult:
    item: NewsItem
    relevant: bool
    reason: str
    raw_response: str


@dataclass
class AnalysisResult:
    item: NewsItem
    signal_type: str  # riesgo | oportunidad | ruido
    severity: str  # low | medium | high
    thesis: str
    raw_response: str
    prompt: str


class AzureOpenAIClient:
    """Thin wrapper over the ``openai`` SDK's Azure client."""

    def __init__(self, config: AzureOpenAIConfig) -> None:
        self.config = config
        self._client: Any = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import AzureOpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "openai is required for the Azure OpenAI client "
                "(pip install 'portfoliowatcher[azure]')"
            ) from exc
        self._client = AzureOpenAI(
            azure_endpoint=self.config.endpoint,
            api_key=self.config.api_key,
            api_version=self.config.api_version,
        )
        return self._client

    def complete(self, *, system: str, user: str, model: str) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content or ""


class LLMPipeline:
    """Runs the triage -> analysis pipeline and persists everything to state."""

    def __init__(self, client: LLMClient, config: AzureOpenAIConfig, state=None) -> None:
        self.client = client
        self.config = config
        self.state = state

    def triage(self, item: NewsItem) -> TriageResult:
        user_prompt = _news_item_prompt(item)
        raw = self.client.complete(
            system=TRIAGE_SYSTEM_PROMPT, user=user_prompt, model=self.config.triage_deployment
        )
        parsed = _safe_json(raw)
        relevant = bool(parsed.get("relevant", False))
        reason = str(parsed.get("reason", ""))
        return TriageResult(item=item, relevant=relevant, reason=reason, raw_response=raw)

    def analyze(self, item: NewsItem) -> AnalysisResult:
        user_prompt = _news_item_prompt(item)
        raw = self.client.complete(
            system=ANALYSIS_SYSTEM_PROMPT, user=user_prompt, model=self.config.analysis_deployment
        )
        parsed = _safe_json(raw)
        signal_type = str(parsed.get("signal_type", "ruido"))
        severity = str(parsed.get("severity", "low"))
        thesis = str(parsed.get("thesis", ""))
        result = AnalysisResult(
            item=item,
            signal_type=signal_type,
            severity=severity,
            thesis=thesis,
            raw_response=raw,
            prompt=user_prompt,
        )
        if self.state is not None:
            from .state import SignalRecord

            self.state.record_signal(
                SignalRecord(
                    ticker=item.ticker,
                    signal_type=signal_type,
                    severity=severity,
                    thesis=thesis,
                    news_guid=item.guid,
                    prompt=user_prompt,
                    response=raw,
                    model=self.config.analysis_deployment,
                )
            )
        return result

    def process_items(self, items: list[NewsItem]) -> list[AnalysisResult]:
        """Run triage first; only surviving items go through the expensive analysis tier."""
        results: list[AnalysisResult] = []
        for item in items:
            triage_result = self.triage(item)
            if not triage_result.relevant:
                log.debug("triage discarded %s: %s", item.guid, triage_result.reason)
                continue
            results.append(self.analyze(item))
        return results

    def weekly_report(self, portfolio_summary: str) -> str:
        return self.client.complete(
            system=WEEKLY_REPORT_SYSTEM_PROMPT,
            user=portfolio_summary,
            model=self.config.analysis_deployment,
        )


def _news_item_prompt(item: NewsItem) -> str:
    return (
        f"Ticker: {item.ticker}\n"
        f"Fuente: {item.source}\n"
        f"Título: {item.title}\n"
        f"Resumen: {item.summary}\n"
        f"Fecha: {item.published_at.isoformat()}\n"
        f"Link: {item.link}"
    )


def _safe_json(raw: str) -> dict:
    try:
        # Models sometimes wrap JSON in markdown fences despite instructions.
        cleaned = (
            raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        )
        return json.loads(cleaned)
    except (json.JSONDecodeError, AttributeError):
        log.warning("could not parse LLM response as JSON: %r", raw)
        return {}
