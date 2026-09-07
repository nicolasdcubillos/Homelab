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
    from ..settings import _env_bool, _env_int, _env_str

    prefix = "DASHBOARD_REGIME_"

    def number(name: str, default: float, minimum: float, maximum: float) -> float:
        raw = os.getenv(prefix + name, "").strip()
        try:
            value = float(raw) if raw else default
        except ValueError:
            raise ValueError(f"{prefix}{name} debe ser un numero.") from None
        if not minimum <= value <= maximum:
            raise ValueError(f"{prefix}{name} debe estar entre {minimum} y {maximum}.")
        return value

    disk_min_free_mb = _env_int(prefix + "DISK_MIN_FREE_MB", 1024, minimum=0)
    if disk_min_free_mb > 1_000_000:
        raise ValueError(f"{prefix}DISK_MIN_FREE_MB no puede superar 1000000.")

    return RegimeSettings(
        enabled=_env_bool(prefix + "ENABLED", False),
        deliveries_enabled=_env_bool(prefix + "DELIVERIES_ENABLED", False),
        bls_key=_env_str(prefix + "BLS_KEY", ""),
        bea_key=_env_str(prefix + "BEA_KEY", ""),
        fred_key=_env_str(prefix + "FRED_KEY", ""),
        acs_connection_string=_env_str(prefix + "ACS_CONNECTION_STRING", ""),
        acs_email_sender=_env_str(prefix + "ACS_EMAIL_SENDER", ""),
        acs_channel_id=_env_str(prefix + "ACS_CHANNEL_ID", ""),
        whatsapp_template_name=_env_str(prefix + "WHATSAPP_TEMPLATE_NAME", ""),
        whatsapp_template_language=_env_str(prefix + "WHATSAPP_TEMPLATE_LANGUAGE", "es"),
        whatsapp_template_approved=_env_bool(prefix + "WHATSAPP_TEMPLATE_APPROVED", False),
        public_base_url=_env_str(prefix + "PUBLIC_BASE_URL", "").rstrip("/"),
        disk_min_free_mb=disk_min_free_mb,
        timeout=number("TIMEOUT", 20, 1, 120),
    )
