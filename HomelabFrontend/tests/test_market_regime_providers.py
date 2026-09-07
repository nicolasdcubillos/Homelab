"""Fixtures SINTETICOS para contratos; nunca constituyen evidencia de datos reales."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode

import httpx
import pytest

from homelab_dashboard.market_regime.catalog import REQUIRED_SERIES, SERIES, SOURCES, source_infos
from homelab_dashboard.market_regime.providers import (
    bea,
    bea_calendar,
    bls,
    collect_source,
    fed,
    fred,
    treasury,
)
from homelab_dashboard.market_regime.providers import http as provider_http
from homelab_dashboard.market_regime.providers.authorized_import import parse_authorized_import
from homelab_dashboard.market_regime.providers.base import ParseError, ProviderError
from homelab_dashboard.market_regime.providers.fed_calendar import parse_calendar
from homelab_dashboard.market_regime.providers.http import PublicHTTP, sanitized_url

NOW = datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)
SYNTHETIC_TREASURY = b"""<feed xmlns="http://www.w3.org/2005/Atom"
 xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
 xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
 <entry><content><m:properties><d:NEW_DATE>2026-09-03T00:00:00</d:NEW_DATE>
 <d:BC_2YEAR>3.50</d:BC_2YEAR><d:BC_10YEAR>4.25</d:BC_10YEAR>
 </m:properties></content></entry></feed>"""
SYNTHETIC_FED = {
    fed.H10: b"<table><tr><th>3-SEP-26</th><td>145.00</td></tr>"
    b"<tr><th>4-SEP-26</th><td>ND</td></tr></table>",
    fed.H15: b"<table><tr><th>Instruments</th><th>2026Sep3</th><th>2026Sep4</th></tr>"
    b"<tr><td>Federal funds (effective) 1 2 3</td><td>3.5</td>"
    b"<td>n.a.</td></tr></table>",
    fed.H41: b"<table><tr><th>Assets, liabilities, and capital</th>"
    b"<th>Eliminations from consolidation</th><th>WednesdaySep 2, 2026</th>"
    b"<th>Change since</th></tr><tr><td>Total assets</td><td>(0)</td>"
    b"<td>6,500,000</td><td>+ 100</td><td>- 100</td></tr></table>",
    fed.FOMC: b'<a href="/newsevents/pressreleases/monetary20260729a.htm">Statement</a>'
    b'<a href="/monetarypolicy/fomcminutes20260729.htm">Minutes</a>'
    b'<a href="/monetarypolicy/fomcprojtabl20260617.htm">Projection</a>'
    b'<a href="https://example.invalid/monetary20260729a.htm">Untrusted</a>',
}
SYNTHETIC_FOMC_CALENDAR = b"""
<div><h4><a>2026 FOMC Meetings</a></h4>
  <div class="row fomc-meeting">
    <div class="fomc-meeting__month"><strong>July</strong></div>
    <div class="fomc-meeting__date">28-29</div>
    <div><a href="/newsevents/pressreleases/monetary20260729a.htm">Statement</a></div>
    <div class="fomc-meeting__minutes">
      <a href="/monetarypolicy/files/fomcminutes20260729.pdf">PDF</a>
      <a href="/monetarypolicy/fomcminutes20260729.htm">HTML</a>
      (Released August 19, 2026)
    </div>
  </div>
  <div class="row fomc-meeting">
    <div class="fomc-meeting__month"><strong>September</strong></div>
    <div class="fomc-meeting__date">15-16*</div>
  </div>
</div>
<div><h4><a>2027 FOMC Meetings</a></h4>
  <div class="row fomc-meeting">
    <div class="fomc-meeting__month">January</div>
    <div class="fomc-meeting__date">26-27</div>
  </div>
</div>
<p>* Meeting associated with a Summary of Economic Projections.</p>
"""


@pytest.fixture(autouse=True)
def isolated_provider_budget(monkeypatch):
    monkeypatch.setattr(provider_http, "_requests", defaultdict(deque))
    monkeypatch.setattr(provider_http.time, "sleep", lambda _: None)


def bls_response():
    return {
        "status": "REQUEST_SUCCEEDED",
        "Results": {
            "series": [
                {
                    "seriesID": official,
                    "data": [
                        {"year": "2026", "period": "M07", "value": "123.45"},
                        {"year": "2025", "period": "M13", "value": "999"},
                    ],
                }
                for official in bls.SERIES_IDS
            ]
        },
    }


def bea_response(table):
    lines = [
        (1, "DPCERG", "Personal consumption expenditures"),
        (23, "DPCCRG", "PCE excluding food and energy"),
    ]
    if table == "T10106":
        lines = [(1, "A191RX", "Gross domestic product")]
    return {
        "BEAAPI": {
            "Results": {
                "Data": [
                    {
                        "TableName": table,
                        "LineNumber": str(number),
                        "LineDescription": description,
                        "SeriesCode": code,
                        "METRIC_NAME": "Chained Dollars" if table == "T10106" else "Index Numbers",
                        "CL_UNIT": "Level",
                        "UNIT_MULT": "9" if table == "T10106" else "0",
                        "TimePeriod": "2026Q2" if table == "T10106" else "2026M07",
                        "DataValue": "123.456",
                    }
                    for number, code, description in lines
                ],
                "Notes": [
                    {
                        "NoteText": "[Billions of chained (2017) dollars]"
                        if table == "T10106"
                        else "[Index numbers, 2017=100]"
                    }
                ],
            }
        }
    }


def import_body():
    return {
        "manifest": {
            "schema_version": "1",
            "provider": "Synthetic test provider",
            "source_url": "https://example.invalid/data",
            "terms_url": "https://example.invalid/terms",
            "license_id": "fixture-license",
            "license_evidence_sha256": "a" * 64,
            "attribution": "Synthetic fixture only",
            "permissions": ["storage", "processing", "shared_display", "derivatives"],
        },
        "observations": [
            {
                "series_id": "SPX",
                "period": "2026-09-03",
                "value": "5000",
                "unit": "index points",
                "frequency": "daily",
                "observed_at": "2026-09-03T20:00:00Z",
                "bar_closed": True,
            }
        ],
    }


def test_catalog_required_and_no_silent_substitutes():
    assert set(REQUIRED_SERIES) == {
        "US02Y",
        "US10Y",
        "USDJPY",
        "CPI",
        "CORE_CPI",
        "NFP",
        "UNEMPLOYMENT",
        "AHE",
        "JOLTS",
        "PCE",
        "CORE_PCE",
        "GDP",
        "FED_FUNDS",
        "FED_BALANCE",
        "SPX",
        "ES",
        "NDX",
        "NQ",
        "RUSSELL",
        "DOW",
        "DXY",
        "VIX",
        "MOVE",
        "HY_OAS",
        "IG_OAS",
    }
    assert SERIES["NFCI"]["analytical_weight"] == 0
    assert SERIES["USDJPY"]["quote_convention"] == "JPY per USD"
    assert not (
        {"BAMLH0A0HYM2", "BAMLC0A0CM", "DTWEXBGS", "VIXCLS", "NFCI"} & fred.ALLOWLIST.keys()
    )
    assert SERIES["NFCI"]["license_status"] == "BLOQUEADO_LICENCIA"
    assert all(source.terms_url.startswith("https://") for source in SOURCES)


def test_readiness_is_offline_and_does_not_modify_catalog():
    configured = source_infos({"BEA_API_KEY": "test-only"})
    assert next(s for s in configured if s.id == "bea").status == "DISPONIBLE"
    assert next(s for s in SOURCES if s.id == "bea").status == "NO_CONFIGURADO"
    assert "test-only" not in repr(configured)


def test_freshness_fallback_accounts_for_economic_period_start():
    # Al 7 de septiembre, Q2 y julio pueden ser las ultimas publicaciones oficiales.
    period_starts = {
        "GDP": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "PCE": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "JOLTS": datetime(2026, 7, 1, tzinfo=timezone.utc),
    }
    for series_id, start in period_starts.items():
        assert (NOW - start).days <= SERIES[series_id]["max_age_days"]
        assert SERIES[series_id]["freshness_reference"] == "observed_at"
    assert SERIES["USDJPY"]["max_age_days"] == 14
    assert SERIES["US10Y"]["max_age_days"] == 7


@pytest.mark.parametrize(
    "source,status",
    [
        ("bea", "NO_CONFIGURADO"),
        ("fred", "NO_CONFIGURADO"),
        ("licensed_market", "BLOQUEADO_LICENCIA"),
        ("authorized_import", "NO_CONFIGURADO"),
        ("chicago_fed", "BLOQUEADO_LICENCIA"),
        ("census", "NO_CONFIGURADO"),
        ("dol", "NO_CONFIGURADO"),
        ("unknown", "ERROR"),
    ],
)
def test_disabled_sources_never_fetch(source, status):
    def forbidden(request):
        pytest.fail("No debe consultar una fuente deshabilitada.")

    result = collect_source(source, {}, now=NOW, transport=httpx.MockTransport(forbidden))
    assert result.status == status
    assert not result.payloads


def test_market_license_cannot_be_enabled_by_credentials():
    result = collect_source("licensed_market", {"licensed_market": "test-only"}, now=NOW)
    assert result.status == "BLOQUEADO_LICENCIA"


def test_nfci_is_blocked_even_with_fred_key():
    calls = []

    def handler(request):
        calls.append(request)
        pytest.fail("NFCI nunca debe descargarse sin derechos aplicables.")

    result = collect_source(
        "chicago_fed",
        {"fred": "test-only"},
        now=NOW,
        transport=httpx.MockTransport(handler),
    )
    assert result.status == "BLOQUEADO_LICENCIA"
    assert not calls
    assert (
        "NFCI"
        not in next(
            source for source in source_infos({"fred": "test-only"}) if source.id == "fred"
        ).series
    )
    assert all(params["series_id"] != "NFCI" for _, params in fred.requests(NOW, "test-only"))
    with pytest.raises(ParseError):
        fred.parse(b'{"count": 0, "observations":[]}', fred.URL + "?series_id=NFCI", NOW)


def test_treasury_same_observation_dates_and_conservative_availability():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=SYNTHETIC_TREASURY)

    result = collect_source("treasury", {}, now=NOW, transport=httpx.MockTransport(handler))
    assert result.status == "DISPONIBLE"
    assert len(calls) == 3
    rows = result.payloads[0].observations
    assert {row.series_id for row in rows} == {"US02Y", "US10Y"}
    assert rows[0].observed_at == rows[1].observed_at
    assert rows[0].value == Decimal("3.50")
    assert all(row.available_at == NOW and row.published_at is None for row in rows)
    assert all(row.raw_hash == hashlib.sha256(SYNTHETIC_TREASURY).hexdigest() for row in rows)


@pytest.mark.parametrize(
    "raw",
    [
        b"<html>error</html>",
        b"<broken",
        b'<!DOCTYPE foo [<!ENTITY entity "x">]><feed/>',
        SYNTHETIC_TREASURY.replace(b"3.50", b"NaN"),
        SYNTHETIC_TREASURY.replace(b"2026-09-03", b"2027-09-03"),
    ],
)
def test_treasury_invalid_payload_is_not_data(raw):
    with pytest.raises(ParseError):
        treasury.parse(raw, treasury.URL, NOW)


def test_fed_three_series_and_documents_are_not_expectations():
    result = collect_source(
        "fed",
        {},
        now=NOW,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                content=SYNTHETIC_FED[str(r.url)],
            )
        ),
    )
    assert result.status == "DISPONIBLE"
    rows = [o for p in result.payloads for o in p.observations]
    assert {row.series_id for row in rows} == {"USDJPY", "FED_FUNDS", "FED_BALANCE"}
    assert len(rows) == 3
    assert next(row for row in rows if row.series_id == "FED_BALANCE").value == 6500000
    assert all(row.published_at is None and row.available_at == NOW for row in rows)
    documents = fed.parse_fomc_documents(SYNTHETIC_FED[fed.FOMC])
    assert {item["kind"] for item in documents} == {"statement", "minutes", "projections"}
    assert all("federalreserve.gov" in item["url"] for item in documents)
    assert not result.payloads[-1].observations


def test_fed_partial_error_keeps_successful_payloads_without_fabrication():
    def handler(request):
        if str(request.url) == fed.H41:
            return httpx.Response(403, content=b"blocked")
        return httpx.Response(200, content=SYNTHETIC_FED[str(request.url)])

    result = collect_source("fed", {}, now=NOW, transport=httpx.MockTransport(handler))
    assert result.status == "ERROR"
    assert "HTTP 403" in result.detail
    assert {o.series_id for p in result.payloads for o in p.observations} == {
        "USDJPY",
        "FED_FUNDS",
    }


def test_fomc_upcoming_dates_are_parsed_from_official_headings_not_generated():
    events = parse_calendar(SYNTHETIC_FOMC_CALENDAR, NOW)
    assert len(events) == 6
    meetings = [event for event in events if event.kind == "meeting"]
    assert {event.event_at.date().isoformat() for event in meetings} == {
        "2026-07-29",
        "2026-09-16",
        "2027-01-27",
    }
    assert all(event.scheduled and event.timestamp_precision == "date" for event in meetings)
    assert all(event.available_at == NOW and event.published_at is None for event in events)
    september = next(event for event in meetings if event.event_at.month == 9)
    january = next(event for event in meetings if event.event_at.month == 1)
    assert september.event_at.hour == 4  # Medianoche NY en verano, no hora de decision.
    assert january.event_at.hour == 5
    minutes = next(event for event in events if event.kind == "minutes")
    assert minutes.event_at.date().isoformat() == "2026-08-19"
    assert "20260729" in minutes.source_url  # URL identifica reunion, NO publicacion.
    assert not minutes.scheduled


def test_fomc_does_not_infer_minutes_publication_or_sep_without_annotation():
    raw = SYNTHETIC_FOMC_CALENDAR.replace(b"(Released August 19, 2026)", b"")
    raw = raw.replace(b"Meeting associated with a Summary of Economic Projections.", b"")
    events = parse_calendar(raw, NOW)
    assert not any(event.kind in {"minutes", "projection"} for event in events)


def test_fomc_invalid_calendar_is_explicit_error_not_guessed_future_dates():
    with pytest.raises(ParseError):
        parse_calendar(b"<html>Calendar unavailable</html>", NOW)
    with pytest.raises(ParseError):
        parse_calendar(SYNTHETIC_FOMC_CALENDAR.replace(b"15-16*", b"date pending"), NOW)


def test_collected_fomc_payload_exposes_events_without_changing_observation_contract():
    def handler(request):
        raw = (
            SYNTHETIC_FOMC_CALENDAR
            if str(request.url) == fed.FOMC
            else SYNTHETIC_FED[str(request.url)]
        )
        return httpx.Response(200, content=raw)

    result = collect_source("fed", {}, now=NOW, transport=httpx.MockTransport(handler))
    assert result.status == "DISPONIBLE"
    assert len(result.payloads[-1].events) == 6
    assert not result.payloads[-1].observations
    assert result.payloads[-1].raw_hash == hashlib.sha256(SYNTHETIC_FOMC_CALENDAR).hexdigest()


def test_bea_calendar_operates_without_api_key_and_keeps_schedules_distinct_from_releases():
    body = {
        "file_last_updated": "2026-07-13T08:00:42.402013",
        "Gross Domestic Product": {
            "release_dates": [
                "2026-09-30T12:30:00+00:00",
                "2026-09-30T12:30:00+00:00",
            ]
        },
        "Personal Income and Outlays": {"release_dates": ["2026-09-30T12:30:00+00:00"]},
    }
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == bea_calendar.URL
        return httpx.Response(200, json=body)

    result = collect_source("bea_calendar", {}, now=NOW, transport=httpx.MockTransport(handler))
    assert result.status == "DISPONIBLE"
    assert len(calls) == 1
    events = result.payloads[0].events
    assert len(events) == 2
    assert not result.payloads[0].observations
    assert all(event.scheduled and event.published_at is None for event in events)
    assert all(
        event.available_at == NOW and event.timestamp_precision == "exact" for event in events
    )
    assert events[0].event_at == datetime(2026, 9, 30, 12, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"Gross Domestic Product": {"release_dates": ["2026-09-30T08:30:00"]}},
        {"Gross Domestic Product": {"release_dates": "tomorrow"}},
        {"Gross Domestic Product": {"release_dates": ["not a date"]}},
    ],
)
def test_bea_calendar_invalid_dates_are_not_guessed(body):
    with pytest.raises(ParseError):
        bea_calendar.parse_events(json.dumps(body).encode(), bea_calendar.URL, NOW)


def test_bls_unregistered_batch_and_monthly_period_not_release_date():
    def handler(request):
        body = json.loads(request.content)
        assert len(body["seriesid"]) == 6
        assert int(body["endyear"]) - int(body["startyear"]) == 2
        assert "registrationkey" not in body
        return httpx.Response(200, json=bls_response())

    result = collect_source("bls", {}, now=NOW, transport=httpx.MockTransport(handler))
    assert result.status == "DISPONIBLE"
    assert len(result.payloads[0].observations) == 6
    assert all(
        o.period == "2026-07" and o.available_at == NOW and o.published_at is None
        for o in result.payloads[0].observations
    )


def test_bls_error_200_quarantines_raw_and_does_not_echo_remote_message():
    result = collect_source(
        "bls",
        {},
        now=NOW,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "status": "REQUEST_NOT_PROCESSED",
                    "message": ["sensitive remote echo"],
                },
            ),
        ),
    )
    assert result.status == "ERROR"
    assert result.payloads[0].raw
    assert not result.payloads[0].observations
    assert "sensitive remote echo" not in result.detail


def test_bls_missing_series_rejected():
    body = bls_response()
    body["Results"]["series"].pop()
    with pytest.raises(ParseError):
        bls.parse(json.dumps(body).encode(), bls.URL, NOW)


def test_bea_optional_key_tables_units_and_redaction():
    key = "synthetic-api-key"

    def handler(request):
        assert request.url.params["UserID"] == key
        body = bea_response(request.url.params["TableName"])
        body["BEAAPI"]["Request"] = {"RequestParam": [{"ParameterValue": key}]}
        return httpx.Response(200, json=body)

    result = collect_source("bea", {"bea": key}, now=NOW, transport=httpx.MockTransport(handler))
    assert result.status == "DISPONIBLE"
    assert {o.series_id for p in result.payloads for o in p.observations} == {
        "PCE",
        "CORE_PCE",
        "GDP",
    }
    for item in result.payloads:
        assert key.encode() not in item.raw
        assert key not in item.source_url
        assert "UserID" not in item.source_url
        assert all(
            row.available_at == NOW and row.published_at is None for row in item.observations
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("LineDescription", "Wrong concept"),
        ("METRIC_NAME", "Current Dollars"),
        ("UNIT_MULT", "6"),
        ("TimePeriod", "2026Q7"),
        ("DataValue", "Infinity"),
    ],
)
def test_bea_semantic_changes_fail_closed(field, value):
    body = bea_response("T10106")
    body["BEAAPI"]["Results"]["Data"][0][field] = value
    with pytest.raises(ParseError):
        bea.parse(json.dumps(body).encode(), bea.URL + "?TableName=T10106", NOW)


def test_bea_json_error_is_explicit():
    body = {"BEAAPI": {"Results": {"Error": {"APIErrorCode": "4"}}}}
    with pytest.raises(ParseError, match="Error JSON"):
        bea.parse(json.dumps(body).encode(), bea.URL + "?TableName=T10106", NOW)


def test_bea_resolves_series_code_not_row_position():
    body = bea_response("T20804")
    body["BEAAPI"]["Results"]["Data"].reverse()
    for row in body["BEAAPI"]["Results"]["Data"]:
        row["LineNumber"] = "999"
    rows = bea.parse(json.dumps(body).encode(), bea.URL + "?TableName=T20804", NOW)
    assert {row.series_id for row in rows} == {"PCE", "CORE_PCE"}


def test_fred_does_not_backdate_current_revised_history():
    body = {
        "count": 2,
        "observations": [
            {"date": "2025-01-01", "value": "123", "realtime_start": "2025-01-01"},
            {"date": "2025-02-01", "value": "."},
        ],
    }
    rows = fred.parse(json.dumps(body).encode(), fred.URL + "?series_id=CPIAUCSL", NOW)
    assert len(rows) == 1
    assert rows[0].available_at == NOW
    assert rows[0].published_at is None
    assert rows[0].vintage == "current_snapshot:2026-09-07"
    requests = fred.requests(NOW, "test-only")
    assert all(params["realtime_start"] == "2026-09-07" for _, params in requests)
    assert not any(params["series_id"] in {"BAMLH0A0HYM2", "BAMLC0A0CM"} for _, params in requests)


def test_fred_rejects_ice_even_if_parser_called_directly():
    with pytest.raises(ParseError):
        fred.parse(
            b'{"count": 0, "observations":[]}',
            fred.URL + "?series_id=BAMLH0A0HYM2",
            NOW,
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://api.bls.gov/data",
        "https://example.invalid/data",
        "https://test:secret@api.bls.gov/data",
        "https://api.bls.gov:8443/data",
    ],
)
def test_http_allowlist_blocks_arbitrary_network(url):
    transport = httpx.MockTransport(lambda r: pytest.fail("Unexpected fetch"))
    with PublicHTTP("bls", transport) as client:
        with pytest.raises(ProviderError):
            client.fetch(url)


def test_http_does_not_follow_redirect_to_arbitrary_host():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://example.invalid"})

    with PublicHTTP("bls", httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match="HTTP 302"):
            client.fetch(bls.URL)
    assert len(calls) == 1


def test_http_retry_after_and_maximum_three_attempts(monkeypatch):
    calls, sleeps = [], []
    monkeypatch.setattr(provider_http.time, "sleep", sleeps.append)

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "2"})

    with PublicHTTP("bls", httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match="3|intentos"):
            client.fetch(bls.URL)
    assert len(calls) == 3
    assert sleeps == [2, 2]


def test_http_long_retry_after_is_deferred_not_ignored():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    with PublicHTTP("bls", httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match="diferido"):
            client.fetch(bls.URL)
    assert len(calls) == 1


def test_http_daily_budget_counts_attempts():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"{}"))
    for _ in range(20):
        with PublicHTTP("bls", transport) as client:
            client.fetch(bls.URL)
    with PublicHTTP("bls", transport) as client:
        with pytest.raises(ProviderError, match="diario"):
            client.fetch(bls.URL)


def test_bea_numeric_and_calendar_endpoints_share_minute_budget():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"{}"))
    for _ in range(17):
        with PublicHTTP("bea", transport) as client:
            client.fetch(bea.URL)
    for _ in range(3):
        with PublicHTTP("bea_calendar", transport) as client:
            client.fetch(bea_calendar.URL)
    with PublicHTTP("bea", transport) as client:
        with pytest.raises(ProviderError, match="minuto"):
            client.fetch(bea.URL)


def test_http_enforces_stream_size(monkeypatch):
    monkeypatch.setattr(provider_http, "MAX_PAYLOAD_BYTES", 100)
    with PublicHTTP(
        "bls",
        httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"x" * 101),
        ),
    ) as client:
        with pytest.raises(ProviderError, match="bytes"):
            client.fetch(bls.URL)


def test_http_network_errors_do_not_reveal_request_secrets():
    def handler(request):
        raise httpx.ReadTimeout("https://api.bls.gov/?api_key=do-not-show")

    result = collect_source("bls", {}, now=NOW, transport=httpx.MockTransport(handler))
    assert result.status == "ERROR"
    assert "timeout" in result.detail
    assert "do-not-show" not in result.detail


def test_saved_urls_remove_sensitive_query_and_userinfo():
    url = "https://user:secret@api.stlouisfed.org/fred?" + urlencode(
        {"api_key": "not-a-real-key", "series_id": "DFF", "UserID": "test-only"},
    )
    assert sanitized_url(url) == "https://api.stlouisfed.org/fred?series_id=DFF"


def test_unknown_now_timezone_is_error_without_network():
    result = collect_source("fed", {}, now=NOW.replace(tzinfo=None))
    assert result.status == "ERROR"


def test_authorized_import_validates_but_never_self_approves_rights():
    metadata, result = parse_authorized_import(
        json.dumps(import_body()).encode(),
        "json",
        now=NOW,
    )
    assert metadata.license_id == "fixture-license"
    assert result.source_id == "authorized_import"
    assert result.observations[0].available_at == NOW
    assert result.raw_hash == result.observations[0].raw_hash
    assert not hasattr(metadata, "approved")


@pytest.mark.parametrize(
    "field,value",
    [
        ("unit", "USD"),
        ("frequency", "monthly"),
        ("value", "NaN"),
        ("series_id", "UNKNOWN"),
        ("bar_closed", False),
        ("observed_at", "2026-09-03T20:00:00"),
        ("available_at", "2026-09-04T20:00:00Z"),
    ],
)
def test_authorized_import_rejects_invalid_data(field, value):
    body = import_body()
    body["observations"][0][field] = value
    with pytest.raises(ParseError):
        parse_authorized_import(json.dumps(body).encode(), "json", now=NOW)


def test_authorized_import_manifest_cannot_assert_approval():
    body = import_body()
    body["manifest"]["approved"] = True
    with pytest.raises(ParseError):
        parse_authorized_import(json.dumps(body).encode(), "json", now=NOW)


def test_authorized_import_does_not_accept_urls_with_credentials():
    body = import_body()
    body["manifest"]["source_url"] += "?api_key=not-real"
    with pytest.raises(ParseError):
        parse_authorized_import(json.dumps(body).encode(), "json", now=NOW)


def test_authorized_import_requires_contract_and_roll_for_futures():
    body = import_body()
    body["observations"][0]["series_id"] = "ES"
    with pytest.raises(ParseError, match="contrato"):
        parse_authorized_import(json.dumps(body).encode(), "json", now=NOW)


def test_authorized_import_date_vintage_is_next_day_in_publication_zone():
    body = import_body()
    body["observations"][0].update(
        timestamp_precision="date",
        vintage="2026-09-07",
        publication_timezone="America/New_York",
    )
    _, result = parse_authorized_import(json.dumps(body).encode(), "json", now=NOW)
    row = result.observations[0]
    assert row.available_at == datetime(2026, 9, 8, 4, tzinfo=timezone.utc)
    assert row.published_at is None
    assert row.timestamp_precision == "date"


def test_authorized_import_csv_and_duplicate_rejection():
    body = import_body()
    csv_raw = (
        b"series_id,period,value,unit,frequency,observed_at,bar_closed\n"
        b"SPX,2026-09-03,5000,index points,daily,2026-09-03T20:00:00Z,true\n"
    )
    _, result = parse_authorized_import(csv_raw, "csv", now=NOW, manifest=body["manifest"])
    assert len(result.observations) == 1
    body["observations"].append(body["observations"][0].copy())
    with pytest.raises(ParseError, match="duplicadas"):
        parse_authorized_import(json.dumps(body).encode(), "json", now=NOW)


def test_reingesting_revised_values_never_claims_old_availability():
    original = treasury.parse(SYNTHETIC_TREASURY, treasury.URL, NOW)
    revised_at = NOW + timedelta(days=7)
    revised = treasury.parse(SYNTHETIC_TREASURY.replace(b"3.50", b"3.60"), treasury.URL, revised_at)
    assert original[0].observed_at == revised[0].observed_at
    assert original[0].value != revised[0].value
    assert revised[0].available_at == revised_at
