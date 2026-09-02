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
    group_hits,
    register_notifier,
    render_text,
    summarize,
)
from .console import ConsoleNotifier
from .whatsapp import WhatsAppNotifier

__all__ = [
    "ConsoleNotifier",
    "Notifier",
    "NotifierError",
    "WhatsAppNotifier",
    "available_notifiers",
    "batch_groups",
    "build_notifier",
    "group_hits",
    "register_notifier",
    "render_text",
    "summarize",
]
