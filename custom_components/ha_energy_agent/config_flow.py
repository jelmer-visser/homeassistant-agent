"""Config flow for HA Energy Agent — 4-step setup + OptionsFlow.

Steps:
  1. user (credentials) — AI provider + API key
  2. discover           — auto-scan HA entities (no user input, shows summary)
  3. sensor_review      — one entity picker per sensor slot, pre-filled by discovery
  4. settings           — interval, history window, AI model, tariff, notification

OptionsFlow lets the user re-run discovery or change settings post-setup.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from custom_components.ha_energy_agent.const import (
    ANTHROPIC_MODELS,
    CONF_AI_API_KEY,
    CONF_AI_PROVIDER,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_FIXED_DAY_RATE,
    DEFAULT_FIXED_NIGHT_RATE,
    DEFAULT_HISTORY_HOURS,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_NORDPOOL_ENTITY_ID,
    DEFAULT_NOTIFY_HA,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_TARIFF_TYPE,
    DOMAIN,
    OPENAI_MODELS,
    OPT_AI_MODEL,
    OPT_FIXED_DAY_RATE,
    OPT_FIXED_NIGHT_RATE,
    OPT_HISTORY_HOURS,
    OPT_INTERVAL_MINUTES,
    OPT_NORDPOOL_ENTITY_ID,
    OPT_NOTIFY_HA,
    OPT_SELECTED_ENTITIES,
    OPT_TARIFF_TYPE,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    SENSOR_SLOTS,
)
from custom_components.ha_energy_agent.discovery import (
    _pre_populate_slots,
    discover_entities,
    discovery_summary,
)

_LOGGER = logging.getLogger(__name__)


def _models_for_provider(provider: str) -> list[str]:
    return ANTHROPIC_MODELS if provider == PROVIDER_ANTHROPIC else OPENAI_MODELS


def _default_model_for_provider(provider: str) -> str:
    return DEFAULT_ANTHROPIC_MODEL if provider == PROVIDER_ANTHROPIC else DEFAULT_OPENAI_MODEL


def _build_settings_schema(defaults: dict, provider: str) -> vol.Schema:
    """Build the settings step schema."""
    models = _models_for_provider(provider)
    default_model = _default_model_for_provider(provider)
    return vol.Schema(
        {
            vol.Required(OPT_AI_MODEL, default=defaults.get(OPT_AI_MODEL, default_model)): SelectSelector(
                SelectSelectorConfig(
                    options=models,
                    mode=SelectSelectorMode.LIST,
                    translation_key="ai_model",
                )
            ),
            vol.Required(OPT_INTERVAL_MINUTES, default=defaults.get(OPT_INTERVAL_MINUTES, DEFAULT_INTERVAL_MINUTES)): SelectSelector(
                SelectSelectorConfig(
                    options=["15", "30", "60"],
                    mode=SelectSelectorMode.LIST,
                    translation_key="interval_minutes",
                )
            ),
            vol.Required(OPT_HISTORY_HOURS, default=str(defaults.get(OPT_HISTORY_HOURS, DEFAULT_HISTORY_HOURS))): SelectSelector(
                SelectSelectorConfig(
                    options=["12", "24", "48"],
                    mode=SelectSelectorMode.LIST,
                    translation_key="history_hours",
                )
            ),
            vol.Required(OPT_TARIFF_TYPE, default=defaults.get(OPT_TARIFF_TYPE, DEFAULT_TARIFF_TYPE)): SelectSelector(
                SelectSelectorConfig(
                    options=["fixed", "dynamic"],
                    mode=SelectSelectorMode.LIST,
                    translation_key="tariff_type",
                )
            ),
            vol.Optional(OPT_FIXED_DAY_RATE, default=defaults.get(OPT_FIXED_DAY_RATE, DEFAULT_FIXED_DAY_RATE)): NumberSelector(
                NumberSelectorConfig(min=0.0, max=2.0, step=0.001, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_FIXED_NIGHT_RATE, default=defaults.get(OPT_FIXED_NIGHT_RATE, DEFAULT_FIXED_NIGHT_RATE)): NumberSelector(
                NumberSelectorConfig(min=0.0, max=2.0, step=0.001, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(OPT_NORDPOOL_ENTITY_ID, default=defaults.get(OPT_NORDPOOL_ENTITY_ID, DEFAULT_NORDPOOL_ENTITY_ID)): EntitySelector(
                EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(OPT_NOTIFY_HA, default=defaults.get(OPT_NOTIFY_HA, DEFAULT_NOTIFY_HA)): BooleanSelector(),
        }
    )


def _build_slot_schema(pre_populated: dict[str, str]) -> vol.Schema:
    """Build the sensor review schema — one EntitySelector per slot."""
    fields: dict = {}
    for slot in SENSOR_SLOTS:
        default = pre_populated.get(slot.key, "")
        fields[vol.Optional(slot.key, default=default)] = EntitySelector(
            EntitySelectorConfig(domain="sensor")
        )
    return vol.Schema(fields)


def _coerce_settings(user_input: dict) -> dict:
    """Coerce string values from SelectSelector to proper Python types."""
    out = dict(user_input)
    if OPT_INTERVAL_MINUTES in out:
        out[OPT_INTERVAL_MINUTES] = int(out[OPT_INTERVAL_MINUTES])
    if OPT_HISTORY_HOURS in out:
        out[OPT_HISTORY_HOURS] = int(out[OPT_HISTORY_HOURS])
    if OPT_FIXED_DAY_RATE in out:
        out[OPT_FIXED_DAY_RATE] = float(out[OPT_FIXED_DAY_RATE])
    if OPT_FIXED_NIGHT_RATE in out:
        out[OPT_FIXED_NIGHT_RATE] = float(out[OPT_FIXED_NIGHT_RATE])
    return out


class HAEnergyAgentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle initial configuration of HA Energy Agent."""

    VERSION = 1

    def __init__(self) -> None:
        self._provider: str = PROVIDER_ANTHROPIC
        self._api_key: str = ""
        self._discovery_result: dict = {}
        self._pre_populated_slots: dict[str, str] = {}
        self._selected_slots: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 1: AI provider + API key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            provider = user_input[CONF_AI_PROVIDER]
            api_key = user_input[CONF_AI_API_KEY].strip()

            if provider == PROVIDER_ANTHROPIC and not api_key.startswith("sk-ant-"):
                errors[CONF_AI_API_KEY] = "invalid_anthropic_key"
            elif provider == PROVIDER_OPENAI and not api_key.startswith("sk-"):
                errors[CONF_AI_API_KEY] = "invalid_openai_key"
            else:
                self._provider = provider
                self._api_key = api_key
                return await self.async_step_discover()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AI_PROVIDER, default=PROVIDER_ANTHROPIC): SelectSelector(
                        SelectSelectorConfig(
                            options=[PROVIDER_ANTHROPIC, PROVIDER_OPENAI],
                            mode=SelectSelectorMode.LIST,
                            translation_key="ai_provider",
                        )
                    ),
                    vol.Required(CONF_AI_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 2: Run discovery, show summary. No user input needed — just Next."""
        if user_input is not None:
            return await self.async_step_sensor_review()

        self._discovery_result = await self.hass.async_add_executor_job(
            discover_entities, self.hass
        )
        self._pre_populated_slots = _pre_populate_slots(self._discovery_result)
        summary = discovery_summary(self._discovery_result, self._pre_populated_slots)
        _LOGGER.info("Discovery complete: %s", summary)

        return self.async_show_form(
            step_id="discover",
            data_schema=vol.Schema({}),
            description_placeholders={"summary": summary},
        )

    async def async_step_sensor_review(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 3: One entity picker per sensor slot, pre-filled by discovery."""
        if user_input is not None:
            self._selected_slots = {k: v for k, v in user_input.items() if v}
            return await self.async_step_settings()

        schema = _build_slot_schema(self._pre_populated_slots)
        return self.async_show_form(
            step_id="sensor_review",
            data_schema=schema,
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 4: Interval, history window, AI model, tariff configuration."""
        if user_input is not None:
            options = _coerce_settings(user_input)
            options[OPT_SELECTED_ENTITIES] = self._selected_slots

            return self.async_create_entry(
                title="HA Energy Agent",
                data={CONF_AI_PROVIDER: self._provider, CONF_AI_API_KEY: self._api_key},
                options=options,
            )

        schema = _build_settings_schema({}, self._provider)
        return self.async_show_form(
            step_id="settings",
            data_schema=schema,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "HAEnergyAgentOptionsFlow":
        return HAEnergyAgentOptionsFlow(config_entry)


class HAEnergyAgentOptionsFlow(config_entries.OptionsFlow):
    """Handle options: re-discover or change settings."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._discovery_result: dict = {}
        self._pre_populated_slots: dict[str, str] = {}

        raw = config_entry.options.get(OPT_SELECTED_ENTITIES, {})
        # Backwards compat: old format was dict[str, list[str]] — discard, user re-configures once
        if raw and isinstance(next(iter(raw.values())), list):
            self._selected_slots: dict[str, str] = {}
        else:
            self._selected_slots = dict(raw)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Show main options menu: re-discover or change settings."""
        if user_input is not None:
            if user_input.get("action") == "rediscover":
                return await self.async_step_discover()
            return await self.async_step_settings()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action", default="settings"): SelectSelector(
                        SelectSelectorConfig(
                            options=["settings", "rediscover"],
                            mode=SelectSelectorMode.LIST,
                            translation_key="options_action",
                        )
                    )
                }
            ),
        )

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Re-run discovery."""
        if user_input is not None:
            return await self.async_step_sensor_review()

        self._discovery_result = await self.hass.async_add_executor_job(
            discover_entities, self.hass
        )
        self._pre_populated_slots = _pre_populate_slots(
            self._discovery_result, self._selected_slots
        )
        summary = discovery_summary(self._discovery_result, self._pre_populated_slots)
        return self.async_show_form(
            step_id="discover",
            data_schema=vol.Schema({}),
            description_placeholders={"summary": summary},
        )

    async def async_step_sensor_review(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Entity slot selection."""
        if user_input is not None:
            self._selected_slots = {k: v for k, v in user_input.items() if v}
            return await self.async_step_settings()

        schema = _build_slot_schema(self._pre_populated_slots)
        return self.async_show_form(
            step_id="sensor_review",
            data_schema=schema,
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Change settings."""
        if user_input is not None:
            options = _coerce_settings(user_input)
            options[OPT_SELECTED_ENTITIES] = self._selected_slots
            return self.async_create_entry(title="", data=options)

        provider = self._config_entry.data.get(CONF_AI_PROVIDER, PROVIDER_ANTHROPIC)
        schema = _build_settings_schema(self._config_entry.options, provider)
        return self.async_show_form(
            step_id="settings",
            data_schema=schema,
        )
