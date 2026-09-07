"""Catalogo cerrado: los instrumentos licenciados nunca tienen un fetch implicito."""

from __future__ import annotations

import hashlib
import json

from .schemas import SourceInfo

CATALOG_VERSION = "2026-09-07.1"


def _series(
    name: str,
    source_id: str,
    official_id: str,
    unit: str,
    frequency: str,
    *,
    required: bool = True,
    max_age_days: int = 75,
    **metadata: object,
) -> dict:
    return {
        "name": name,
        "source_id": source_id,
        "official_id": official_id,
        "unit": unit,
        "frequency": frequency,
        "required": required,
        "max_age_days": max_age_days,
        "impact": "HIGH" if required else "MEDIUM",
        "freshness_reference": "observed_at",
        "publication_grace_business_days": 1,
        "catalog_version": CATALOG_VERSION,
        **metadata,
    }


SERIES = {
    "US02Y": _series(
        "Treasury par nominal 2 anos",
        "treasury",
        "BC_2YEAR",
        "percent",
        "daily",
        max_age_days=7,
        expected_at="Dias habiles, fin del dia ET",
    ),
    "US10Y": _series(
        "Treasury par nominal 10 anos",
        "treasury",
        "BC_10YEAR",
        "percent",
        "daily",
        max_age_days=7,
        expected_at="Dias habiles, fin del dia ET",
    ),
    "USDJPY": _series(
        "H.10 yen por dolar, fixing de mediodia NY",
        "fed",
        "H10/JRXWJ_N.B.JA",
        "JPY per USD",
        "daily",
        max_age_days=14,
        quote_convention="JPY per USD",
        seasonal_adjustment="NSA",
        observation_convention="Noon buying rate NY; no cierre ni spot",
        expected_at="Lunes 16:15 ET, datos de la semana anterior; calendario Fed",
    ),
    "CPI": _series(
        "CPI todos los consumidores urbanos",
        "bls",
        "CUSR0000SA0",
        "index 1982-84=100",
        "monthly",
        seasonal_adjustment="SA",
    ),
    "CORE_CPI": _series(
        "CPI sin alimentos ni energia",
        "bls",
        "CUSR0000SA0L1E",
        "index 1982-84=100",
        "monthly",
        seasonal_adjustment="SA",
    ),
    "NFP": _series(
        "Nominas no agricolas, nivel",
        "bls",
        "CES0000000001",
        "thousands of persons",
        "monthly",
        seasonal_adjustment="SA",
    ),
    "UNEMPLOYMENT": _series(
        "Tasa de desempleo U-3",
        "bls",
        "LNS14000000",
        "percent",
        "monthly",
        seasonal_adjustment="SA",
    ),
    "AHE": _series(
        "Salario horario medio, sector privado",
        "bls",
        "CES0500000003",
        "USD per hour",
        "monthly",
        seasonal_adjustment="SA",
    ),
    "JOLTS": _series(
        "Vacantes totales, nivel JOLTS",
        "bls",
        "JTS000000000000000JOL",
        "thousands of persons",
        "monthly",
        seasonal_adjustment="SA",
        max_age_days=100,
    ),
    "PCE": _series(
        "Indice de precios PCE",
        "bea",
        "DPCERG",
        "index 2017=100",
        "monthly",
        seasonal_adjustment="SA",
        table="T20804",
        max_age_days=95,
    ),
    "CORE_PCE": _series(
        "Indice de precios PCE sin alimentos ni energia",
        "bea",
        "DPCCRG",
        "index 2017=100",
        "monthly",
        seasonal_adjustment="SA",
        table="T20804",
        max_age_days=95,
    ),
    "GDP": _series(
        "PIB real, nivel anualizado",
        "bea",
        "A191RX",
        "billions of chained 2017 USD",
        "quarterly",
        max_age_days=220,
        seasonal_adjustment="SAAR",
        table="T10106",
    ),
    "FED_FUNDS": _series(
        "Tasa efectiva federal funds H.15",
        "fed",
        "H15/FF",
        "percent",
        "daily",
        max_age_days=7,
        expected_at="Dias habiles 16:15 ET; H.15",
    ),
    "FED_BALANCE": _series(
        "Activos totales consolidados Fed H.4.1",
        "fed",
        "H41/total_assets",
        "millions of USD",
        "weekly",
        max_age_days=14,
        expected_at="Jueves 16:30 ET; dato miercoles",
    ),
    "NFCI": _series(
        "Chicago Fed NFCI, diagnostico bloqueado sin peso",
        "chicago_fed",
        "NFCI",
        "index",
        "weekly",
        required=False,
        max_age_days=21,
        analytical_weight=0,
        attribution="Federal Reserve Bank of Chicago, via FRED",
        license_status="BLOQUEADO_LICENCIA",
        authorized_import_only=True,
        terms_url="https://www.chicagofed.org/utilities/legal-notices",
        source_url="https://fred.stlouisfed.org/series/NFCI",
    ),
    "CLAIMS": _series(
        "Solicitudes iniciales de desempleo",
        "dol",
        "initial_claims",
        "persons",
        "weekly",
        required=False,
        max_age_days=21,
    ),
    "RETAIL_SALES": _series(
        "Ventas minoristas Census", "census", "MRTS", "millions of USD", "monthly", required=False
    ),
    "DURABLE_GOODS": _series(
        "Pedidos de bienes duraderos Census",
        "census",
        "M3",
        "millions of USD",
        "monthly",
        required=False,
    ),
}

# BLS/BEA/FRED identifican meses y trimestres por su inicio. Los limites de 95/100/220
# dias incluyen el periodo economico y el rezago de publicacion, no suponen igual TTL
# desde published_at. Son fallback conservador; un calendario oficial conocido prevalece.
for _id, _name, _owner, _unit in (
    ("SPX", "S&P 500 indice", "S&P Dow Jones Indices", "index points"),
    ("ES", "E-mini S&P 500 futuro", "CME", "index points"),
    ("NDX", "Nasdaq 100 indice", "Nasdaq", "index points"),
    ("NQ", "E-mini Nasdaq 100 futuro", "CME", "index points"),
    ("RUSSELL", "Russell 2000 indice", "FTSE Russell", "index points"),
    ("DOW", "Dow Jones Industrial Average", "S&P Dow Jones Indices", "index points"),
    ("DXY", "ICE US Dollar Index", "ICE", "index points"),
    ("VIX", "Cboe VIX", "Cboe", "index points"),
    ("MOVE", "ICE BofA MOVE", "ICE", "index points"),
    ("HY_OAS", "ICE BofA US High Yield OAS", "ICE", "percent"),
    ("IG_OAS", "ICE BofA US Corporate OAS", "ICE", "percent"),
    ("FED_FUNDS_FUTURES", "Futuros federal funds; expectativas no disponibles", "CME", "price"),
):
    SERIES[_id] = _series(
        _name,
        "licensed_market",
        _id,
        _unit,
        "daily",
        required=_id != "FED_FUNDS_FUTURES",
        max_age_days=5,
        owner=_owner,
        license_status="BLOQUEADO_LICENCIA",
        authorized_import_only=True,
        contract_required=_id in {"ES", "NQ", "FED_FUNDS_FUTURES"},
    )

REQUIRED_SERIES = tuple(key for key, value in SERIES.items() if value["required"])

SOURCES = [
    SourceInfo(
        id="treasury",
        name="US Treasury",
        url="https://home.treasury.gov/",
        terms_url="https://home.treasury.gov/footer/privacy-act",
        status="DISPONIBLE",
        detail="Curva par nominal diaria oficial; no yield intradia.",
    ),
    SourceInfo(
        id="fed",
        name="Federal Reserve H.10 / H.15 / H.4.1 / FOMC",
        url="https://www.federalreserve.gov/",
        terms_url="https://www.federalreserve.gov/disclaimer.htm",
        status="DISPONIBLE",
        detail="USDJPY historico; H.15 y H.4.1 actuales; FOMC enlaces/documentos, sin NLP.",
    ),
    SourceInfo(
        id="bls",
        name="Bureau of Labor Statistics",
        url="https://www.bls.gov/",
        terms_url="https://www.bls.gov/bls/linksite.htm",
        status="DISPONIBLE",
        detail="API sin registro: <=10 series, <=3 anos, <=20 consultas/dia locales.",
    ),
    SourceInfo(
        id="bea",
        name="Bureau of Economic Analysis",
        url="https://www.bea.gov/",
        terms_url="https://www.bea.gov/about/policies-and-information",
        requires_key=True,
        status="NO_CONFIGURADO",
        detail="Falta clave BEA opcional.",
    ),
    SourceInfo(
        id="bea_calendar",
        name="BEA: calendario oficial de publicaciones",
        url="https://www.bea.gov/news/schedule",
        terms_url="https://www.bea.gov/about/policies-and-information",
        status="DISPONIBLE",
        detail="JSON oficial publico sin clave; horarios programados, no publicacion confirmada.",
    ),
    SourceInfo(
        id="fred",
        name="FRED/ALFRED: lista oficial permitida",
        url="https://fred.stlouisfed.org/",
        terms_url="https://fred.stlouisfed.org/legal/",
        requires_key=True,
        status="NO_CONFIGURADO",
        detail="Falta clave FRED opcional. ICE OAS y NFCI excluidos incluso con clave.",
    ),
    SourceInfo(
        id="chicago_fed",
        name="Chicago Fed NFCI: derechos de derivados restringidos",
        url="https://www.chicagofed.org/research/data/nfci/about",
        terms_url="https://www.chicagofed.org/utilities/legal-notices",
        status="BLOQUEADO_LICENCIA",
        restricted=True,
        detail="Sin fetch ni derivados. Los derechos de Chicago Fed no son los del Board. "
        "NFCI permanece diagnostico opcional de peso cero.",
    ),
    SourceInfo(
        id="census",
        name="US Census Bureau (confirmacion)",
        url="https://www.census.gov/economic-indicators/",
        terms_url="https://www.census.gov/about/policies/privacy.html",
        status="NO_CONFIGURADO",
        detail="Tier medio pendiente de parser validado; no sustituye BLS/BEA.",
    ),
    SourceInfo(
        id="dol",
        name="US Department of Labor (confirmacion)",
        url="https://oui.doleta.gov/unemploy/claims.asp",
        terms_url="https://www.dol.gov/general/aboutdol/copyright",
        status="NO_CONFIGURADO",
        detail="Tier medio pendiente de parser validado.",
    ),
    SourceInfo(
        id="licensed_market",
        name="Indices, futuros y credito: proveedor pendiente",
        url="https://www.ice.com/market-data",
        terms_url="https://fred.stlouisfed.org/series/BAMLH0A0HYM2",
        status="BLOQUEADO_LICENCIA",
        restricted=True,
        detail="Sin fetch. ICE/FRED OAS: ventana 3 anos no concede distribucion a terceros. "
        "VIX publico y Alpha Vantage personal tampoco habilitan uso multiusuario.",
    ),
    SourceInfo(
        id="authorized_import",
        name="Importacion local autorizada",
        url="https://home.treasury.gov/",
        terms_url="https://www.ice.com/market-data/terms-and-conditions",
        status="NO_CONFIGURADO",
        restricted=True,
        detail="Solo CLI local; requiere aprobacion de derechos persistida por admin.",
    ),
]
for _source in SOURCES:
    _source.series = [key for key, value in SERIES.items() if value["source_id"] == _source.id]
    if _source.id == "fred":
        _source.series += [
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
        ]

# Estos permisos cubren solo los datos federales originales seleccionados, no material
# de terceros presente en el sitio ni un vendor habilitado por una clave.
LICENSES = {
    source.id: {
        "terms_url": source.terms_url,
        "reviewed_at": "2026-09-07",
        "version": CATALOG_VERSION,
        "attribution": source.name,
        "storage": source.id in {"treasury", "fed", "bls", "bea", "fred", "bea_calendar"},
        "processing": source.id in {"treasury", "fed", "bls", "bea", "fred", "bea_calendar"},
        "shared_display": source.id in {"treasury", "fed", "bls", "bea", "fred", "bea_calendar"},
        "derivatives": source.id in {"treasury", "fed", "bls", "bea", "fred", "bea_calendar"},
        "external_notification": source.id
        in {
            "treasury",
            "fed",
            "bls",
            "bea",
            "fred",
            "bea_calendar",
        },
        "scope": "Solo series originales oficiales del allowlist; requiere atribucion.",
    }
    for source in SOURCES
}
for _license in LICENSES.values():
    _license["policy_hash"] = hashlib.sha256(
        json.dumps(_license, sort_keys=True).encode()
    ).hexdigest()


def credential(credentials: dict[str, str], source_id: str) -> str:
    for key in (source_id, f"{source_id}_api_key", f"{source_id.upper()}_API_KEY"):
        value = credentials.get(key, "")
        if value and value.strip():
            return value.strip()
    return ""


def source_infos(credentials: dict[str, str]) -> list[SourceInfo]:
    result = [source.model_copy(deep=True) for source in SOURCES]
    for source in result:
        if source.id in {"bea", "fred"} and credential(credentials, source.id):
            source.status = "DISPONIBLE"
            source.detail = "Clave configurada; validez/cuota se comprueban al recopilar."
        if source.id == "bls" and credential(credentials, "bls"):
            source.detail = "API registrada; presupuesto local sigue <=20 consultas/dia."
    return result
