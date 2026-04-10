"""Auto-register a Lovelace sidebar panel for HA Energy Agent."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_DASHBOARD_URL = "ha-energy-agent"
_STORAGE_KEY = f"lovelace.{_DASHBOARD_URL}"
_STORAGE_VERSION = 1


_SEED_MARKER = "ha_energy_agent_seeded"


def _build_lovelace_config() -> dict:
    return {
        _SEED_MARKER: True,  # Marker so we know we seeded this — never overwrite after this
        "title": "Energy Agent",
        "views": [
            {
                "title": "Overview",
                "icon": "mdi:home-lightning-bolt",
                "cards": [
                    {
                        "type": "todo-list",
                        "entity": "todo.ha_energy_agent_energy_tips",
                        "title": "Energy Tips",
                    },
                    {
                        "type": "gauge",
                        "entity": "sensor.ha_energy_agent_efficiency_score",
                        "name": "Efficiency Score",
                        "min": 0,
                        "max": 100,
                        "severity": {
                            "green": 70,
                            "yellow": 40,
                            "red": 0,
                        },
                    },
                    {
                        "type": "entities",
                        "title": "Agent Status",
                        "entities": [
                            "sensor.ha_energy_agent_last_analysis",
                            "sensor.ha_energy_agent_tips_count",
                            "sensor.ha_energy_agent_high_priority_tips",
                        ],
                    },
                ],
            }
        ],
    }


async def async_setup_dashboard(hass: "HomeAssistant", entry: "ConfigEntry") -> None:
    """Register the sidebar panel and seed the Lovelace config if not yet present."""
    from homeassistant.components.frontend import async_register_built_in_panel
    from homeassistant.helpers.storage import Store

    store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
    existing = await store.async_load()

    # Only seed when our marker is absent. This handles three cases:
    # 1. Fresh install — no storage yet → seed.
    # 2. HA auto-created a default ("New section") before we ran → no marker → seed.
    # 3. User previously customised the dashboard → marker present → leave it alone.
    already_seeded = bool(
        existing and existing.get("config", {}).get(_SEED_MARKER)
    )
    if not already_seeded:
        await store.async_save({"config": _build_lovelace_config()})

    try:
        async_register_built_in_panel(
            hass,
            component_name="lovelace",
            sidebar_title="Energy Agent",
            sidebar_icon="mdi:home-lightning-bolt",
            frontend_url_path=_DASHBOARD_URL,
            config={"mode": "storage"},
            require_admin=False,
        )
    except ValueError:
        pass  # Panel already registered (e.g. integration reloaded)


async def async_remove_dashboard(hass: "HomeAssistant") -> None:
    """Remove the sidebar panel on integration unload."""
    try:
        from homeassistant.components.frontend import async_remove_panel
        async_remove_panel(hass, _DASHBOARD_URL)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("Could not remove dashboard panel: %s", exc)
