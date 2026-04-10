"""HA Energy Agent — AI-powered home energy optimization."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "todo"]


async def async_setup(hass: "HomeAssistant", config: dict) -> bool:
    """Register the custom Lovelace card once at integration load time."""
    try:
        from custom_components.ha_energy_agent.frontend import async_setup_frontend
        await async_setup_frontend(hass)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Frontend card setup failed (non-fatal): %s", exc)
    return True


async def async_setup_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Set up HA Energy Agent from a config entry."""
    import voluptuous as vol
    from homeassistant.core import ServiceCall

    from custom_components.ha_energy_agent.const import DOMAIN, SERVICE_RUN_NOW
    from custom_components.ha_energy_agent.coordinator import EnergyAgentCoordinator

    coordinator = EnergyAgentCoordinator(hass, entry)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _handle_run_now(call: ServiceCall) -> None:
        for coord in hass.data.get(DOMAIN, {}).values():
            if isinstance(coord, EnergyAgentCoordinator):
                await coord.async_run_now()

    hass.services.async_register(
        DOMAIN,
        SERVICE_RUN_NOW,
        _handle_run_now,
        schema=vol.Schema({}),
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    entry.async_create_background_task(
        hass,
        coordinator.async_refresh(),
        name=f"{DOMAIN}_initial_refresh",
    )

    return True


async def async_unload_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Unload a config entry."""
    from custom_components.ha_energy_agent.const import DOMAIN, SERVICE_RUN_NOW

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_RUN_NOW)

    return unload_ok


async def _async_update_options(hass: "HomeAssistant", entry: "ConfigEntry") -> None:
    """Reload entry when options change (e.g. new interval)."""
    await hass.config_entries.async_reload(entry.entry_id)
