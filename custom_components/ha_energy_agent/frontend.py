"""Register the HA Energy Agent custom Lovelace card."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_STATIC_PATH  = "/ha_energy_agent_static"
_CARD_JS      = "ha-energy-agent-card.js"
_RESOURCE_URL = f"{_STATIC_PATH}/{_CARD_JS}"
_WWW_DIR      = str(Path(__file__).parent / "www")


async def async_setup_frontend(hass: "HomeAssistant") -> None:
    """Serve the card JS and register it so Lovelace loads it automatically."""
    from homeassistant.components.frontend import add_extra_js_url

    # 1. Serve /ha_energy_agent_static/* from our www/ directory.
    try:
        from homeassistant.components.http import StaticPathConfig  # HA 2023.9+
        await hass.http.async_register_static_paths(
            [StaticPathConfig(_STATIC_PATH, _WWW_DIR, cache_headers=False)]
        )
    except (ImportError, AttributeError):
        # Older HA
        try:
            hass.http.register_static_path(_STATIC_PATH, _WWW_DIR, False)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Could not register static path for card JS: %s", exc)
            return

    # 2. Tell the frontend to load our card JS on every Lovelace page.
    #    add_extra_js_url is the HA-blessed approach — no lovelace resource
    #    management needed, works across all HA versions.
    add_extra_js_url(hass, _RESOURCE_URL)
    _LOGGER.debug("Registered extra JS URL: %s", _RESOURCE_URL)
