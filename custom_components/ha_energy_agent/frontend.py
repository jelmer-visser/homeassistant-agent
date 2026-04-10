"""Register the HA Energy Agent custom Lovelace card."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_CARD_JS      = "ha-energy-agent-card.js"
_SRC          = Path(__file__).parent / "www" / _CARD_JS
# /config/www/ is always served at /local/ — no custom static-path needed
_LOCAL_SUBDIR = "ha_energy_agent"
_RESOURCE_URL = f"/local/{_LOCAL_SUBDIR}/{_CARD_JS}"


async def async_setup_frontend(hass: "HomeAssistant") -> None:
    """Copy the card JS into /config/www/ and register it with the frontend.

    This function never raises — a failure here must not prevent the
    integration from loading.
    """
    if not _SRC.exists():
        _LOGGER.warning("Card JS source not found at %s — skipping frontend setup", _SRC)
        return

    # 1. Copy JS to /config/www/ha_energy_agent/ so it's served at /local/…
    try:
        dst_dir = Path(hass.config.config_dir) / "www" / _LOCAL_SUBDIR
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / _CARD_JS
        # Only overwrite when the source is newer (avoids unnecessary writes)
        if not dst.exists() or _SRC.stat().st_mtime > dst.stat().st_mtime:
            shutil.copy2(_SRC, dst)
            _LOGGER.info("Copied card JS to %s", dst)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Could not copy card JS to www: %s", exc)
        return

    # 2. Register the URL so Lovelace loads it on every page.
    try:
        from homeassistant.components.frontend import add_extra_js_url
        add_extra_js_url(hass, _RESOURCE_URL)
        _LOGGER.debug("Registered extra JS URL: %s", _RESOURCE_URL)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Could not register card JS URL: %s", exc)
