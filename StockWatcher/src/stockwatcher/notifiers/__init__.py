"""Notifier registry.

WhatsApp is the only production channel for the MVP; email/telegram would be
added by dropping another module here and calling :func:`register_notifier`.
"""

from __future__ import annotations

from .base import (
    Notifier,
    NotifierError,
    available_notifiers,
    batch_groups,
    build_notifier,
    destination_env,
    env_list,
    group_hits,
    register_notifier,
    render_text,
    resolve_destinations,
    summarize,
)
from .console import ConsoleNotifier
from .email import EmailNotifier
from .whatsapp import WhatsAppNotifier

__all__ = [
    "ConsoleNotifier",
    "EmailNotifier",
    "Notifier",
    "NotifierError",
    "WhatsAppNotifier",
    "available_notifiers",
    "batch_groups",
    "build_notifier",
    "destination_env",
    "env_list",
    "group_hits",
    "register_notifier",
    "render_text",
    "resolve_destinations",
    "summarize",
]
