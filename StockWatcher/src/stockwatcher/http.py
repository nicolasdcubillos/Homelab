"""Shared async HTTP client: bounded concurrency + per-host politeness."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from types import TracebackType

import httpx

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

BASE_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Ch-Ua": '"Chromium";v="126", "Not)A;Brand";v="24", "Google Chrome";v="126"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Connection": "keep-alive",
}

#: Sending this makes Shopify Markets localize prices to the caller's geo IP
#: (Kith returns COP for a Colombian IP).  Only providers that need it — Foot
#: Locker will serve empty pages without it — should opt in.
ACCEPT_LANGUAGE_EN_US = {"Accept-Language": "en-US,en;q=0.9"}

#: Transient statuses worth retrying with backoff.
RETRY_STATUS = frozenset({429, 502, 503, 504})

#: Body text Shopify serves when it decides we look like a bot.
CHALLENGE_MARKER = "Verifying your connection"


class RateLimited(RuntimeError):
    """A store throttled or challenged us.  Reported, never fatal."""


class _RateLimiter:
    """Token-bucket limiter for the *whole* client.

    Shopify's edge rate-limits per client IP across **all** storefronts it
    hosts, not per store.  Scanning 37 Shopify shops therefore trips a single
    shared budget: bursting made every host return 429 at once, while pacing
    the same requests at ~4/s returned 200 from every one of them.  So the
    limiter is global rather than per host.
    """

    def __init__(self, rate: float) -> None:
        self.rate = rate
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def acquire(self) -> None:
        if self.rate <= 0:
            return
        interval = 1.0 / self.rate
        async with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + interval
        wait = slot - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)

    async def penalize(self, seconds: float) -> None:
        """Push every queued request back after a throttling response."""
        async with self._lock:
            self._next_slot = max(self._next_slot, time.monotonic() + seconds)


class HttpClient:
    """Thin wrapper over ``httpx.AsyncClient``.

    Three layers of politeness, learned the hard way:

    * A **global semaphore** caps total in-flight requests (default 18) so a
      40-store scan finishes in seconds without saturating the network.
    * A **per-host semaphore** (default 2) stops us blasting one storefront.
      Firing a watch's 6 search queries at one Shopify host simultaneously
      reliably returns ``HTTP 429`` and the store silently yields zero results.
    * A **per-host minimum delay**, because some hosts rate-limit on frequency
      rather than concurrency (Foot Locker needs ~2.5s or it serves empty
      "No Results" pages).

    On top of that, ``429``/``503`` responses are retried with exponential
    backoff, honouring ``Retry-After`` when present.
    """

    def __init__(
        self,
        *,
        concurrency: int = 18,
        timeout: float = 20.0,
        default_delay: float = 0.0,
        user_agent: str = DEFAULT_USER_AGENT,
        per_host_concurrency: int = 1,
        max_retries: int = 2,
        rate: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._default_delay = default_delay
        self._per_host_concurrency = max(1, per_host_concurrency)
        self._max_retries = max(0, max_retries)
        self._limiter = _RateLimiter(rate)
        #: Exposed so browser-based providers can present the same identity.
        self.user_agent = user_agent
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_semaphores: dict[str, asyncio.Semaphore] = {}
        self._host_last: dict[str, float] = {}
        headers = {**BASE_HEADERS, "User-Agent": user_agent}
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
            limits=httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=20),
        )

    @property
    def raw(self) -> httpx.AsyncClient:
        return self._client

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _lock_for(self, host: str) -> asyncio.Lock:
        lock = self._host_locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            self._host_locks[host] = lock
        return lock

    def _semaphore_for(self, host: str) -> asyncio.Semaphore:
        semaphore = self._host_semaphores.get(host)
        if semaphore is None:
            semaphore = asyncio.Semaphore(self._per_host_concurrency)
            self._host_semaphores[host] = semaphore
        return semaphore

    async def _throttle(self, host: str, delay: float) -> None:
        if delay <= 0:
            return
        async with self._lock_for(host):
            last = self._host_last.get(host)
            now = time.monotonic()
            if last is not None:
                # Jitter keeps a fleet of hosts from settling into lockstep,
                # which itself looks robotic.
                wait = delay + random.uniform(0, delay * 0.4) - (now - last)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._host_last[host] = time.monotonic()

    @staticmethod
    def _retry_after(response: httpx.Response, attempt: int) -> float:
        raw = response.headers.get("retry-after")
        if raw:
            try:
                return min(float(raw), 10.0)
            except ValueError:
                pass
        return min(0.75 * (2**attempt), 6.0)

    async def get(
        self,
        url: str,
        *,
        delay: float | None = None,
        headers: dict[str, str] | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        host = httpx.URL(url).host or ""
        effective_delay = self._default_delay if delay is None else delay
        response: httpx.Response | None = None

        for attempt in range(self._max_retries + 1):
            await self._throttle(host, effective_delay)
            await self._limiter.acquire()
            async with self._semaphore, self._semaphore_for(host):
                log.debug("GET %s", url)
                response = await self._client.get(url, headers=headers, params=params)
            if response.status_code not in RETRY_STATUS or attempt == self._max_retries:
                return response
            wait = self._retry_after(response, attempt)
            log.debug("HTTP %s from %s; retrying in %.1fs", response.status_code, host, wait)
            # The budget is shared across every Shopify host, so slow the whole
            # client down rather than just this request.
            await self._limiter.penalize(wait)
            await asyncio.sleep(wait)

        assert response is not None
        return response

    async def get_json(self, url: str, **kwargs) -> dict | list | None:
        response = await self.get(url, **kwargs)
        if response.status_code != 200:
            if response.status_code in RETRY_STATUS:
                raise RateLimited(f"HTTP {response.status_code} from {url}")
            return None
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type and not response.text.lstrip().startswith(("{", "[")):
            # Shopify answers a bot challenge with an HTML page and HTTP 200.
            # Surfacing it as an error keeps it visible in the run summary
            # instead of silently looking like "this store has no stock".
            if CHALLENGE_MARKER in response.text:
                raise RateLimited(f"bot challenge from {url}")
            return None
        try:
            return response.json()
        except ValueError:
            return None
