"""Async Home Assistant REST API client."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import aiohttp
import structlog

from ha_agent.config import Settings

log = structlog.get_logger(__name__)


class HAClient:
    """Thin async wrapper around the Home Assistant REST API."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.ha_base_url
        self._headers = {
            "Authorization": f"Bearer {settings.ha_token}",
            "Content-Type": "application/json",
        }
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "HAClient":
        timeout = aiohttp.ClientTimeout(total=30)
        self._session = aiohttp.ClientSession(headers=self._headers, timeout=timeout)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._session:
            await self._session.close()

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    async def check_connectivity(self) -> str:
        """Call GET /api/ and return HA version string."""
        async with self._session.get(self._url("/api/")) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("version", "unknown")

    async def get_state(self, entity_id: str) -> dict[str, Any]:
        """Fetch current state of a single entity."""
        async with self._session.get(self._url(f"/api/states/{entity_id}")) as resp:
            if resp.status == 404:
                return {"entity_id": entity_id, "state": "unavailable", "attributes": {}}
            resp.raise_for_status()
            return await resp.json()

    async def get_states_bulk(self, entity_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch current states for multiple entities in parallel."""
        tasks = [self.get_state(eid) for eid in entity_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: dict[str, dict[str, Any]] = {}
        for eid, result in zip(entity_ids, results):
            if isinstance(result, Exception):
                log.warning("state_fetch_failed", entity_id=eid, error=str(result))
                out[eid] = {"entity_id": eid, "state": "unavailable", "attributes": {}}
            else:
                out[eid] = result
        return out

    async def get_history(
        self,
        entity_id: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """
        Fetch state history for one entity.
        Returns list of {state, last_changed} dicts (minimal_response=true).
        """
        params = urlencode({
            "filter_entity_id": entity_id,
            "end_time": end.isoformat(),
            "minimal_response": "true",
            "no_attributes": "true",
            "significant_changes_only": "false",
        })
        url = self._url(f"/api/history/period/{start.isoformat()}?{params}")
        async with self._session.get(url) as resp:
            if resp.status == 404:
                return []
            resp.raise_for_status()
            data = await resp.json()
            # data is [[{state, last_changed}, ...], ...]  — one list per entity
            if not data:
                return []
            return data[0]

    async def get_history_bulk(
        self,
        entity_ids: list[str],
        start: datetime,
        end: datetime,
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch history for multiple entities in parallel."""
        tasks = [self.get_history(eid, start, end) for eid in entity_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: dict[str, list[dict[str, Any]]] = {}
        for eid, result in zip(entity_ids, results):
            if isinstance(result, Exception):
                log.warning("history_fetch_failed", entity_id=eid, error=str(result))
                out[eid] = []
            else:
                out[eid] = result
        return out

    async def call_service(
        self, domain: str, service: str, data: dict[str, Any]
    ) -> None:
        """Call a HA service."""
        url = self._url(f"/api/services/{domain}/{service}")
        async with self._session.post(url, json=data) as resp:
            resp.raise_for_status()

    async def send_persistent_notification(
        self, title: str, message: str, notification_id: str
    ) -> None:
        await self.call_service(
            "persistent_notification",
            "create",
            {"title": title, "message": message, "notification_id": notification_id},
        )

    async def set_input_text(self, entity_id: str, value: str) -> None:
        await self.call_service(
            "input_text",
            "set_value",
            {"entity_id": entity_id, "value": value},
        )
