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
_WWW_DIR      = Path(__file__).parent / "www"


async def async_setup_frontend(hass: "HomeAssistant") -> None:
    """Serve the card JS and register it so Lovelace loads it automatically.

    This function never raises — a frontend setup failure must not prevent
    the integration from loading.
    """
    # Guard: www directory must exist (it may be absent on a partial deploy)
    if not _WWW_DIR.is_dir():
        _LOGGER.warning(
            "Card www directory not found at %s — skipping frontend setup", _WWW_DIR
        )
        return

    # 1. Serve /ha_energy_agent_static/* from our www/ directory.
    #    Skip silently if already registered (integration reload).
    try:
        try:
            from homeassistant.components.http import StaticPathConfig  # HA 2023.9+
            await hass.http.async_register_static_paths(
                [StaticPathConfig(_STATIC_PATH, str(_WWW_DIR), cache_headers=False)]
            )
        except (ImportError, AttributeError):
            hass.http.register_static_path(_STATIC_PATH, str(_WWW_DIR), False)
    except Exception as exc:  # noqa: BLE001
        # "already registered" errors are expected on reload — log at debug level
        _LOGGER.debug("Static path registration skipped: %s", exc)

    # 2. Tell the frontend to load our card JS on every Lovelace page.
    try:
        from homeassistant.components.frontend import add_extra_js_url
        add_extra_js_url(hass, _RESOURCE_URL)
        _LOGGER.debug("Registered extra JS URL: %s", _RESOURCE_URL)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Could not register card JS URL: %s", exc)
