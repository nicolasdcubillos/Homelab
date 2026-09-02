"""Console notifier: what ``--dry-run`` uses instead of sending anything."""

from __future__ import annotations

import logging
import sys

from ..models import Alert
from .base import Notifier, batch_groups, group_hits, register_notifier, render_text

log = logging.getLogger(__name__)


class ConsoleNotifier(Notifier):
    name = "console"

    def __init__(self, options: dict | None = None) -> None:
        options = options or {}
        self.max_hits_per_message = int(options.get("max_hits_per_message", 6))
        self.stream = options.get("stream") or sys.stdout

    async def send(self, alert: Alert) -> None:
        if alert.is_empty:
            return
        batches = batch_groups(group_hits(alert.hits), self.max_hits_per_message)
        print(
            f"\n=== {len(alert.hits)} new hit(s) in {len(batches)} message(s) ===", file=self.stream
        )
        for index, batch in enumerate(batches, start=1):
            print(f"\n--- message {index}/{len(batches)} ---", file=self.stream)
            print(render_text(batch), file=self.stream)
        self.stream.flush()


register_notifier("console", lambda options: ConsoleNotifier(options))
