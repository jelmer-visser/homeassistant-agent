"""Register the HA Energy Agent custom Lovelace card."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_CARD_JS = "ha-energy-agent-card.js"
_CARD_VERSION = "1"  # Bump when the card JS changes to bust the browser cache
_STATIC_PATH = "/ha_energy_agent"
_RESOURCE_URL = f"{_STATIC_PATH}/{_CARD_JS}?v={_CARD_VERSION}"
_WWW_DIR = Path(__file__).parent / "www"


async def async_setup_frontend(hass: "HomeAssistant") -> None:
    """Serve the card JS from the integration package and register it with Lovelace.

    Must be called from async_setup() (not async_setup_entry()) so the static
    path and extra-JS URL are registered before any Lovelace page load.

    Never raises — a failure here must not prevent the integration from loading.
    """
    if not (_WWW_DIR / _CARD_JS).exists():
        _LOGGER.warning(
            "Card JS not found at %s — skipping frontend setup", _WWW_DIR / _CARD_JS
        )
        return

    try:
        from homeassistant.components.frontend import add_extra_js_url
        from homeassistant.components.http import StaticPathConfig

        # Serve the integration's www/ directory at /ha_energy_agent/
        await hass.http.async_register_static_paths(
            [StaticPathConfig(_STATIC_PATH, str(_WWW_DIR), cache_headers=False)]
        )

        # Inject the card JS URL into every Lovelace page load.
        add_extra_js_url(hass, _RESOURCE_URL)
        _LOGGER.info("Registered HA Energy Agent card at %s", _RESOURCE_URL)

    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Could not register card JS: %s", exc)
