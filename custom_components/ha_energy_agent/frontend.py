"""Register the HA Energy Agent custom Lovelace card."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_STATIC_PATH   = "/ha_energy_agent_static"
_CARD_JS       = "ha-energy-agent-card.js"
_RESOURCE_URL  = f"{_STATIC_PATH}/{_CARD_JS}"
_WWW_DIR       = str(Path(__file__).parent / "www")

_LOVELACE_DOMAIN = "lovelace"


async def async_setup_frontend(hass: "HomeAssistant") -> None:
    """Serve the card JS and auto-register it as a Lovelace resource."""

    # 1. Register static path so HA serves /ha_energy_agent_static/*
    try:
        from homeassistant.components.http import StaticPathConfig  # HA 2023.9+
        await hass.http.async_register_static_paths(
            [StaticPathConfig(_STATIC_PATH, _WWW_DIR, cache_headers=False)]
        )
    except (ImportError, AttributeError):
        # Older HA fallback
        try:
            hass.http.register_static_path(_STATIC_PATH, _WWW_DIR, False)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Could not register static path for card JS: %s", exc)
            return

    # 2. Auto-add to Lovelace resources so the card type is immediately available
    #    without the user having to add it manually in the UI.
    try:
        resources = hass.data.get(_LOVELACE_DOMAIN, {}).get("resources")
        if resources is None:
            _LOGGER.debug("Lovelace resources collection not available — skipping auto-registration")
            return
        existing_urls = {r["url"] for r in resources.async_items()}
        if _RESOURCE_URL not in existing_urls:
            await resources.async_create_item(
                {"res_type": "module", "url": _RESOURCE_URL}
            )
            _LOGGER.info("Registered Lovelace resource: %s", _RESOURCE_URL)
        else:
            _LOGGER.debug("Lovelace resource already registered: %s", _RESOURCE_URL)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "Could not auto-register Lovelace resource %s: %s — "
            "add it manually in Settings → Dashboards → Resources",
            _RESOURCE_URL, exc,
        )
