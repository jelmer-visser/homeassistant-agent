"""Register the HA Energy Agent custom Lovelace card."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_CARD_JS = "ha-energy-agent-card.js"
_CARD_VERSION = "4"  # Bump when the card JS changes to bust the browser cache
_STATIC_PATH = "/ha_energy_agent"
_RESOURCE_URL = f"{_STATIC_PATH}/{_CARD_JS}?v={_CARD_VERSION}"
_WWW_DIR = Path(__file__).parent / "www"


async def async_setup_frontend(hass: "HomeAssistant") -> None:
    """Serve the card JS and register it as a Lovelace resource.

    The static path is registered immediately (safe during async_setup).
    The Lovelace resource registration is deferred to EVENT_HOMEASSISTANT_STARTED
    because hass.data['lovelace'] is not populated until HA has fully started.

    Never raises.
    """
    if not (_WWW_DIR / _CARD_JS).exists():
        _LOGGER.warning(
            "Card JS not found at %s — skipping frontend setup", _WWW_DIR / _CARD_JS
        )
        return

    # 1. Register static path immediately — this is safe at any startup phase.
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(_STATIC_PATH, str(_WWW_DIR), cache_headers=False)]
        )
        _LOGGER.debug("Registered static path %s → %s", _STATIC_PATH, _WWW_DIR)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Could not register static path: %s", exc)
        return

    # 2. Lovelace resources are only available after HA has fully started.
    async def _register_lovelace_resource(event=None) -> None:  # type: ignore[assignment]
        try:
            resources = hass.data["lovelace"].resources
            await resources.async_load()

            base_url = f"{_STATIC_PATH}/{_CARD_JS}"
            existing = next(
                (item for item in resources.async_items()
                 if item.get("url", "").startswith(base_url)),
                None,
            )

            if existing is None:
                await resources.async_create_item(
                    {"res_type": "module", "url": _RESOURCE_URL}
                )
                _LOGGER.info("Registered Lovelace resource: %s", _RESOURCE_URL)
            elif existing.get("url") != _RESOURCE_URL:
                # Version changed — update the URL so browsers pick up the new JS.
                await resources.async_update_item(
                    existing["id"], {"res_type": "module", "url": _RESOURCE_URL}
                )
                _LOGGER.info(
                    "Updated Lovelace resource: %s → %s", existing.get("url"), _RESOURCE_URL
                )
            else:
                _LOGGER.debug("Lovelace resource up to date: %s", _RESOURCE_URL)

        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Could not register Lovelace resource: %s", exc)

    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

    if hass.is_running:
        # HA already fully started (e.g. integration reloaded after boot).
        await _register_lovelace_resource()
    else:
        # Normal boot path — wait for HA to finish starting.
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_lovelace_resource)
