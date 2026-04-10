"""Register the HA Energy Agent custom Lovelace card."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_CARD_JS = "ha-energy-agent-card.js"
_CARD_VERSION = "2"  # Bump when the card JS changes to bust the browser cache
_STATIC_PATH = "/ha_energy_agent"
_RESOURCE_URL = f"{_STATIC_PATH}/{_CARD_JS}?v={_CARD_VERSION}"
_WWW_DIR = Path(__file__).parent / "www"


async def async_setup_frontend(hass: "HomeAssistant") -> None:
    """Serve the card JS and register it as a Lovelace resource.

    Uses the same mechanism as HACS custom cards so it appears in
    Settings → Dashboards → Resources and loads on every Lovelace page.

    Must be called from async_setup() so the static path is registered
    before any page load. Never raises.
    """
    if not (_WWW_DIR / _CARD_JS).exists():
        _LOGGER.warning(
            "Card JS not found at %s — skipping frontend setup", _WWW_DIR / _CARD_JS
        )
        return

    # 1. Serve the www/ directory at /ha_energy_agent/<file>
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(_STATIC_PATH, str(_WWW_DIR), cache_headers=False)]
        )
        _LOGGER.debug("Registered static path %s → %s", _STATIC_PATH, _WWW_DIR)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Could not register static path: %s", exc)
        return

    # 2. Register as a Lovelace resource (shows up in the resources list,
    #    loaded on every dashboard page — same as HACS cards).
    try:
        resources = hass.data["lovelace"]["resources"]
        await resources.async_load()

        # Check whether our URL (ignoring the version query string) is already listed.
        base_url = f"{_STATIC_PATH}/{_CARD_JS}"
        already_registered = any(
            item.get("url", "").startswith(base_url)
            for item in resources.async_items()
        )

        if not already_registered:
            await resources.async_create_item(
                {"res_type": "module", "url": _RESOURCE_URL}
            )
            _LOGGER.info("Registered Lovelace resource: %s", _RESOURCE_URL)
        else:
            _LOGGER.debug("Lovelace resource already registered: %s", base_url)

    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Could not register Lovelace resource: %s", exc)
