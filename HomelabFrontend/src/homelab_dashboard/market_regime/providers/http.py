"""HTTP allowlisted y presupuestos defensivos; cuotas durables pertenecen al coordinador."""

from __future__ import annotations

import random
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .base import ProviderError, QuotaError

MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_ATTEMPTS = 3
DAILY_REQUEST_BUDGETS = {
    "treasury": 18,
    "fed": 24,
    "bls": 20,
    "bea": 20,
    "fred": 40,
    "census": 10,
    "dol": 10,
    "bea_calendar": 4,
}
MAX_REQUESTS_PER_COLLECTION = {
    "treasury": 9,
    "fed": 12,
    "bls": 3,
    "bea": 6,
    "fred": 39,
    "bea_calendar": 3,
}
HOSTS = {
    "treasury": {"home.treasury.gov"},
    "fed": {"www.federalreserve.gov"},
    "bls": {"api.bls.gov"},
    "bea": {"apps.bea.gov"},
    "bea_calendar": {"apps.bea.gov"},
    "fred": {"api.stlouisfed.org"},
}
_lock = threading.Lock()
_requests: dict[str, deque[float]] = defaultdict(deque)
_SECRETS = {"api_key", "apikey", "key", "userid", "registrationkey"}


def sanitized_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _SECRETS])
    host = parts.hostname or ""
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


def _reserve(source_id: str) -> None:
    now = time.monotonic()
    with _lock:
        entries = _requests[source_id]
        while entries and entries[0] < now - 86400:
            entries.popleft()
        if len(entries) >= DAILY_REQUEST_BUDGETS[source_id]:
            raise QuotaError("Presupuesto local diario de solicitudes agotado.")
        # 20/min queda por debajo de BEA 100 solicitudes y 30 errores/min;
        # BEA usa como maximo 4 MiB/respuesta => menos de 100 MB/min.
        minute_count = sum(t >= now - 60 for t in entries)
        if source_id in {"bea", "bea_calendar"}:
            other = "bea_calendar" if source_id == "bea" else "bea"
            minute_count += sum(t >= now - 60 for t in _requests[other])
        if minute_count >= 20:
            raise QuotaError("Presupuesto local por minuto agotado.")
        entries.append(now)


def _retry_delay(value: str | None, attempt: int) -> float:
    if value:
        try:
            delay = float(value)
        except ValueError:
            try:
                when = parsedate_to_datetime(value)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                delay = (when - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError) as exc:
                raise ProviderError("Retry-After invalido; reintento diferido.") from exc
        if not 0 <= delay <= 5:
            raise QuotaError("Retry-After requiere espera larga; reintento diferido.")
        return delay
    return min(0.5 * 2**attempt + random.uniform(0, 0.2), 5)


class PublicHTTP:
    def __init__(self, source_id: str, transport: httpx.BaseTransport | None = None):
        self.source_id = source_id
        self.request_count = 0
        self.deadline = time.monotonic() + 110
        self.client = httpx.Client(
            timeout=httpx.Timeout(20),
            transport=transport,
            follow_redirects=False,
            headers={
                "User-Agent": "Homelab-Market-Regime/1.0 (official data research)",
                "Accept-Encoding": "identity",
            },
        )

    def __enter__(self) -> PublicHTTP:
        return self

    def __exit__(self, *args: object) -> None:
        self.client.close()

    def fetch(
        self,
        url: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> tuple[str, bytes]:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in HOSTS[self.source_id]
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ProviderError("URL fuera de la lista de fuentes oficiales.")
        maximum = (
            4 * 1024 * 1024 if self.source_id in {"bea", "bea_calendar"} else MAX_PAYLOAD_BYTES
        )
        for attempt in range(MAX_ATTEMPTS):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise QuotaError("Tiempo total de recopilacion agotado.")
            if self.request_count >= MAX_REQUESTS_PER_COLLECTION[self.source_id]:
                raise QuotaError("Presupuesto de esta recopilacion agotado.")
            _reserve(self.source_id)
            self.request_count += 1
            try:
                with self.client.stream(
                    "POST" if json is not None else "GET",
                    url,
                    params=params,
                    json=json,
                    timeout=min(20, remaining),
                ) as response:
                    status = response.status_code
                    if status in {429, 500, 502, 503, 504}:
                        if attempt == MAX_ATTEMPTS - 1:
                            raise ProviderError(f"HTTP {status}; maximo de intentos alcanzado.")
                        delay = _retry_delay(response.headers.get("retry-after"), attempt)
                    elif status != 200:
                        raise ProviderError(f"HTTP {status}; no implica cuota agotada.")
                    else:
                        length = response.headers.get("content-length")
                        if length and length.isdecimal() and int(length) > maximum:
                            raise ProviderError("Respuesta excede el limite de bytes.")
                        data = bytearray()
                        started = time.monotonic()
                        for chunk in response.iter_bytes(chunk_size=65536):
                            if time.monotonic() - started > 20 or time.monotonic() > self.deadline:
                                raise ProviderError("Respuesta excede 20 segundos de lectura.")
                            data.extend(chunk)
                            if len(data) > maximum:
                                raise ProviderError("Respuesta excede el limite de bytes.")
                        return sanitized_url(str(response.url)), bytes(data)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                if attempt == MAX_ATTEMPTS - 1:
                    raise ProviderError("Error de red/timeout tras 3 intentos.") from None
                delay = _retry_delay(None, attempt)
            except httpx.DecodingError:
                raise ProviderError("Codificacion HTTP invalida.") from None
            if time.monotonic() + delay >= self.deadline:
                raise QuotaError("Tiempo total agotado; reintento diferido.")
            time.sleep(delay)
        raise ProviderError("No se obtuvo respuesta.")
