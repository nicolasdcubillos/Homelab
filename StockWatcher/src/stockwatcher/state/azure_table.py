"""Azure Table Storage state store (production backend).

Three logical partitions live in one table:

``availability``
    RowKey = the hit key, ``Available`` = bool.
``store``
    RowKey = the host with ``.`` replaced (Azure forbids ``/ \\ # ?`` in keys;
    dots are legal but we normalize anyway for readability).
``meta``
    RowKey = the meta key, ``Value`` = string.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from ..models import StoreRecord
from .base import StateStore

log = logging.getLogger(__name__)

PARTITION_AVAILABILITY = "availability"
PARTITION_STORE = "store"
PARTITION_META = "meta"


def _encode_host(host: str) -> str:
    return host.replace("/", "_").replace("\\", "_").replace("#", "_").replace("?", "_")


class AzureTableStateStore(StateStore):
    """Requires the ``azure`` extra (``azure-data-tables``)."""

    def __init__(
        self,
        table_name: str = "stockwatcher",
        connection_string: str | None = None,
        connection_string_env: str = "AZURE_STORAGE_CONNECTION_STRING",
        account_url: str | None = None,
    ) -> None:
        self.table_name = table_name
        self.connection_string = connection_string or os.getenv(connection_string_env)
        self.account_url = account_url or os.getenv("AZURE_STORAGE_ACCOUNT_URL")
        self._client = None

    async def open(self) -> None:
        try:
            from azure.data.tables.aio import TableServiceClient
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "azure-data-tables is required for the azure_table state backend "
                "(pip install 'stockwatcher[azure]')"
            ) from exc

        if self.connection_string:
            service = TableServiceClient.from_connection_string(self.connection_string)
        elif self.account_url:
            from azure.identity.aio import DefaultAzureCredential

            service = TableServiceClient(
                endpoint=self.account_url, credential=DefaultAzureCredential()
            )
        else:
            raise RuntimeError(
                "azure_table backend needs AZURE_STORAGE_CONNECTION_STRING "
                "or AZURE_STORAGE_ACCOUNT_URL"
            )

        self._service = service
        try:
            await service.create_table_if_not_exists(self.table_name)
        except Exception as exc:  # pragma: no cover - network
            log.warning("could not ensure table %s exists: %s", self.table_name, exc)
        self._client = service.get_table_client(self.table_name)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
        service = getattr(self, "_service", None)
        if service is not None:
            await service.close()
            self._service = None

    @property
    def client(self):
        if self._client is None:
            raise RuntimeError("AzureTableStateStore used before open()")
        return self._client

    async def get_states(self, keys: Iterable[str]) -> dict[str, bool]:
        from azure.core.exceptions import ResourceNotFoundError

        out: dict[str, bool] = {}
        for key in dict.fromkeys(keys):
            try:
                entity = await self.client.get_entity(PARTITION_AVAILABILITY, key)
            except ResourceNotFoundError:
                continue
            except Exception as exc:  # pragma: no cover - network
                log.warning("state read failed for %s: %s", key, exc)
                continue
            out[key] = bool(entity.get("Available"))
        return out

    async def set_states(self, updates: Mapping[str, bool]) -> None:
        now = datetime.now(UTC).isoformat()
        for key, value in updates.items():
            entity = {
                "PartitionKey": PARTITION_AVAILABILITY,
                "RowKey": key,
                "Available": bool(value),
                "UpdatedAt": now,
            }
            try:
                await self.client.upsert_entity(entity)
            except Exception as exc:  # pragma: no cover - network
                log.warning("state write failed for %s: %s", key, exc)

    async def list_stores(self) -> list[StoreRecord]:
        records: list[StoreRecord] = []
        query = f"PartitionKey eq '{PARTITION_STORE}'"
        try:
            async for entity in self.client.query_entities(query):
                records.append(
                    StoreRecord(
                        host=str(entity.get("Host") or entity.get("RowKey")),
                        provider=str(entity.get("Provider") or "shopify"),
                        country=str(entity.get("Country") or "US"),
                        enabled=bool(entity.get("Enabled", True)),
                        first_seen=_parse(entity.get("FirstSeen")) or datetime.now(UTC),
                        last_ok=_parse(entity.get("LastOk")),
                        fail_count=int(entity.get("FailCount") or 0),
                        source=str(entity.get("Source") or "discovery"),
                        note=str(entity.get("Note") or ""),
                    )
                )
        except Exception as exc:  # pragma: no cover - network
            log.warning("store registry read failed: %s", exc)
        return records

    async def upsert_store(self, record: StoreRecord) -> None:
        entity = {
            "PartitionKey": PARTITION_STORE,
            "RowKey": _encode_host(record.host),
            "Host": record.host,
            "Provider": record.provider,
            "Country": record.country,
            "Enabled": record.enabled,
            "FirstSeen": record.first_seen.astimezone(UTC).isoformat(),
            "LastOk": record.last_ok.astimezone(UTC).isoformat() if record.last_ok else "",
            "FailCount": record.fail_count,
            "Source": record.source,
            "Note": record.note,
        }
        try:
            await self.client.upsert_entity(entity)
        except Exception as exc:  # pragma: no cover - network
            log.warning("store registry write failed for %s: %s", record.host, exc)

    async def get_meta(self, key: str) -> str | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            entity = await self.client.get_entity(PARTITION_META, key)
        except ResourceNotFoundError:
            return None
        except Exception as exc:  # pragma: no cover - network
            log.warning("meta read failed for %s: %s", key, exc)
            return None
        value = entity.get("Value")
        return str(value) if value is not None else None

    async def set_meta(self, key: str, value: str) -> None:
        try:
            await self.client.upsert_entity(
                {"PartitionKey": PARTITION_META, "RowKey": key, "Value": str(value)}
            )
        except Exception as exc:  # pragma: no cover - network
            log.warning("meta write failed for %s: %s", key, exc)


def _parse(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:  # pragma: no cover - defensive
        return None
