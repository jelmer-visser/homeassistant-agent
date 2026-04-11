"""Todo list entity for HA Energy Agent — shows AI tips as actionable items.

Tips from each analysis cycle are synced into a HA todo list. Users can:
- Mark tips as done (survives re-analysis — won't be shown again until new tip)
- Delete tips they want to dismiss entirely
- See priority and estimated savings in the item description

Completed and dismissed tip UIDs are persisted via HA storage so state
survives restarts and analysis cycles.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.helpers.storage import Store

from custom_components.ha_energy_agent.const import DOMAIN
from custom_components.ha_energy_agent.models import AnalysisTip

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from custom_components.ha_energy_agent.coordinator import EnergyAgentCoordinator

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1
_PRIORITY_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}


async def async_setup_entry(
    hass: "HomeAssistant",
    entry: "ConfigEntry",
    async_add_entities: "AddEntitiesCallback",
) -> None:
    """Set up the Energy Tips todo list."""
    coordinator: "EnergyAgentCoordinator" = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EnergyTipsTodoList(coordinator, entry)])


def _tip_to_item(tip: AnalysisTip, completed_uids: set[str]) -> TodoItem:
    """Convert an AnalysisTip to a TodoItem."""
    icon = _PRIORITY_ICON.get(tip.priority, "")
    summary = f"{icon} {tip.title}".strip()

    desc_parts = [tip.description]
    if tip.reasoning:
        desc_parts.append(f"📊 Why: {tip.reasoning}")
    if tip.estimated_saving:
        desc_parts.append(f"Estimated saving: {tip.estimated_saving}")
    desc_parts.append(f"Category: {tip.category} · Priority: {tip.priority}")

    status = (
        TodoItemStatus.COMPLETED
        if tip.id in completed_uids
        else TodoItemStatus.NEEDS_ACTION
    )

    return TodoItem(
        uid=tip.id,
        summary=summary,
        description="\n".join(desc_parts),
        status=status,
    )


class EnergyTipsTodoList(TodoListEntity):
    """A todo list that surfaces AI energy tips and lets users act on them.

    Deliberately does NOT inherit CoordinatorEntity — that base class controls
    the `available` property via coordinator.last_update_success, which caused
    the entity to go unavailable whenever an AI API call failed. Instead we
    subscribe to coordinator updates manually and stay always-available because
    tips are persisted to storage independently of API health.
    """

    _attr_has_entity_name = True
    _attr_name = "Energy Tips"
    _attr_icon = "mdi:lightbulb-group"
    _attr_should_poll = False
    _attr_supported_features = (
        TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(
        self,
        coordinator: "EnergyAgentCoordinator",
        entry: "ConfigEntry",
    ) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_energy_tips"
        self._items: list[TodoItem] = []
        self._completed_uids: set[str] = set()
        self._dismissed_uids: set[str] = set()
        self._store = Store(
            coordinator.hass,
            _STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}.tips",
        )

    # ------------------------------------------------------------------
    # Entity lifecycle
    # ------------------------------------------------------------------

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "HA Energy Agent",
            "manufacturer": "Anthropic / Claude",
            "model": "Energy Optimization AI",
            "entry_type": "service",
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates and restore persisted state."""
        await super().async_added_to_hass()

        # Restore tips from storage so the list is populated immediately on restart.
        await self._load_from_store()

        # Sync from coordinator if it already has data (e.g. after reload).
        if self._coordinator.data:
            self._sync_tips(self._coordinator.data.analysis.tips)

        # Subscribe to future coordinator refreshes.
        self.async_on_remove(
            self._coordinator.async_add_listener(self._on_coordinator_update)
        )

        # Write state now — entity is always available.
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Coordinator listener
    # ------------------------------------------------------------------

    def _on_coordinator_update(self) -> None:
        """Called after each coordinator refresh."""
        if self._coordinator.data:
            try:
                self._sync_tips(self._coordinator.data.analysis.tips)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error syncing tips from coordinator data")
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # TodoListEntity contract
    # ------------------------------------------------------------------

    @property
    def todo_items(self) -> list[TodoItem]:
        return self._items

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Handle user marking an item done or undone."""
        uid = item.uid
        if item.status == TodoItemStatus.COMPLETED:
            self._completed_uids.add(uid)
        else:
            self._completed_uids.discard(uid)

        for i, existing in enumerate(self._items):
            if existing.uid == uid:
                self._items[i] = TodoItem(
                    uid=existing.uid,
                    summary=existing.summary,
                    description=existing.description,
                    status=item.status,
                )
                break

        await self._save_to_store()
        self.async_write_ha_state()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Handle user deleting items — mark as dismissed so they don't return."""
        for uid in uids:
            self._dismissed_uids.add(uid)
            self._completed_uids.discard(uid)
        self._items = [item for item in self._items if item.uid not in uids]
        await self._save_to_store()
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Internal sync
    # ------------------------------------------------------------------

    def _sync_tips(self, tips: list[AnalysisTip]) -> None:
        """Merge new AI tips into the list, respecting completed/dismissed state."""
        new_uids = {tip.id for tip in tips}

        # Drop completed/dismissed UIDs for tips the AI no longer returns.
        self._completed_uids &= new_uids
        self._dismissed_uids &= new_uids

        needs_action: list[TodoItem] = []
        completed: list[TodoItem] = []
        for tip in tips:
            if tip.id in self._dismissed_uids:
                continue
            item = _tip_to_item(tip, self._completed_uids)
            if item.status == TodoItemStatus.COMPLETED:
                completed.append(item)
            else:
                needs_action.append(item)

        priority_order = {"high": 0, "medium": 1, "low": 2}
        needs_action.sort(key=lambda i: _tip_priority(i.uid, tips, priority_order))
        completed.sort(key=lambda i: _tip_priority(i.uid, tips, priority_order))

        self._items = needs_action + completed

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    async def _load_from_store(self) -> None:
        data = await self._store.async_load()
        if not data:
            return
        self._completed_uids = set(data.get("completed_uids", []))
        self._dismissed_uids = set(data.get("dismissed_uids", []))
        self._items = [
            TodoItem(
                uid=d["uid"],
                summary=d["summary"],
                description=d.get("description", ""),
                status=(
                    TodoItemStatus.COMPLETED
                    if d["uid"] in self._completed_uids
                    else TodoItemStatus.NEEDS_ACTION
                ),
            )
            for d in data.get("items", [])
            if d["uid"] not in self._dismissed_uids
        ]

    async def _save_to_store(self) -> None:
        await self._store.async_save({
            "completed_uids": list(self._completed_uids),
            "dismissed_uids": list(self._dismissed_uids),
            "items": [
                {
                    "uid": item.uid,
                    "summary": item.summary,
                    "description": item.description or "",
                }
                for item in self._items
            ],
        })


def _tip_priority(uid: str, tips: list[AnalysisTip], order: dict) -> int:
    for tip in tips:
        if tip.id == uid:
            return order.get(tip.priority, 99)
    return 99
