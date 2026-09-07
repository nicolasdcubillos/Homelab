"""Configuración de proceso; ninguna credencial forma parte de la API."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegimeSettings:
    enabled: bool = False
    deliveries_enabled: bool = False
    bls_key: str = field(default="", repr=False)
    bea_key: str = field(default="", repr=False)
    fred_key: str = field(default="", repr=False)
    acs_connection_string: str = field(default="", repr=False)
    acs_email_sender: str = field(default="", repr=False)
    acs_channel_id: str = field(default="", repr=False)
    whatsapp_template_name: str = ""
    whatsapp_template_language: str = "es"
    whatsapp_template_approved: bool = False
    public_base_url: str = ""
    disk_min_free_mb: int = 1024
    timeout: float = 20.0


def load_regime_settings() -> RegimeSettings:
    prefix = "DASHBOARD_REGIME_"

    def flag(name: str) -> bool:
        return os.getenv(prefix + name, "").strip().lower() in {"true", "1", "yes"}

    def number(name: str, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(os.getenv(prefix + name, str(default)))
        except ValueError:
            return default
        return value if minimum <= value <= maximum else default

    return RegimeSettings(
        enabled=flag("ENABLED"),
        deliveries_enabled=flag("DELIVERIES_ENABLED"),
        bls_key=os.getenv(prefix + "BLS_KEY", ""),
        bea_key=os.getenv(prefix + "BEA_KEY", ""),
        fred_key=os.getenv(prefix + "FRED_KEY", ""),
        acs_connection_string=os.getenv(prefix + "ACS_CONNECTION_STRING", ""),
        acs_email_sender=os.getenv(prefix + "ACS_EMAIL_SENDER", ""),
        acs_channel_id=os.getenv(prefix + "ACS_CHANNEL_ID", ""),
        whatsapp_template_name=os.getenv(prefix + "WHATSAPP_TEMPLATE_NAME", ""),
        whatsapp_template_language=os.getenv(prefix + "WHATSAPP_TEMPLATE_LANGUAGE", "es"),
        whatsapp_template_approved=flag("WHATSAPP_TEMPLATE_APPROVED"),
        public_base_url=os.getenv(prefix + "PUBLIC_BASE_URL", "").rstrip("/"),
        disk_min_free_mb=int(number("DISK_MIN_FREE_MB", 1024, 0, 1_000_000)),
        timeout=number("TIMEOUT", 20, 1, 120),
    )
