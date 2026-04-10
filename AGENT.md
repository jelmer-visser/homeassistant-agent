# HA Energy Agent — Agent Context

## Project Overview

**ha_energy_agent** is a Home Assistant custom component that uses AI (Anthropic Claude or OpenAI GPT) to analyze home energy data and deliver actionable optimization recommendations. It is distributed as a HACS custom integration.

Core flow: collect energy sensor data → send to AI → parse structured recommendations → expose via HA sensor entities + persistent notifications.

## Repository Layout

```
custom_components/ha_energy_agent/   # Main integration package
├── __init__.py                      # HA entry point: setup/unload, service registration
├── const.py                         # All constants: providers, model lists, config keys, categories
├── models.py                        # Pydantic models for the entire data pipeline
├── coordinator.py                   # DataUpdateCoordinator: orchestrates each analysis cycle
├── config_flow.py                   # 4-step config UI + options flow
├── discovery.py                     # Dynamic HA entity discovery and categorization
├── sensor.py                        # 4 read-only HA sensor entities
├── services.yaml                    # run_analysis_now service definition
├── manifest.json                    # HA integration metadata
├── strings.json / translations/     # UI localization
│
├── analysis/
│   ├── base.py                      # AnalysisClient protocol (interface)
│   ├── claude.py                    # Anthropic Claude implementation
│   ├── openai_client.py             # OpenAI implementation
│   ├── prompts.py                   # System prompt + dynamic user message builder
│   └── parser.py                    # JSON extraction and validation from AI responses
│
└── processing/
    └── history.py                   # Fetch, resample, stats, anomaly detection

tests/
├── conftest.py
├── test_history.py
├── test_parser.py
├── test_prompts.py
└── test_providers.py
```

## Architecture

### Data Flow (per analysis cycle)

```
HA Recorder → fetch_history_bundles()
                    ↓
             resample + stats + anomaly detection
                    ↓
             build_user_message() + SYSTEM_PROMPT
                    ↓
             AI Provider (Claude or OpenAI) → raw text
                    ↓
             parse_claude_response() → AnalysisResult
                    ↓
             Sensor entities updated + HA notification sent
```

### Key Design Decisions

- **Async-first**: All I/O is async. SDK clients are lazy-loaded in a thread executor to avoid blocking the HA event loop on SSL/import.
- **Provider abstraction**: `AnalysisClient` protocol (`analysis/base.py`) decouples coordinator from specific AI providers.
- **Coordinator pattern**: Uses `DataUpdateCoordinator` — sensors are `CoordinatorEntity` subclasses that automatically update.
- **Pydantic models**: Strong typing throughout (`models.py`). Parser validates and defaults AI output before it touches the rest of the system.

### Energy Categories

`grid`, `solar`, `battery`, `heat_pump`, `temperature`, `pricing`

Discovery scoring rules support both English and Dutch entity names/device classes.

### AI Providers

| Provider | Config key | API key prefix | Reasoning model detection |
|----------|-----------|----------------|--------------------------|
| Anthropic Claude | `anthropic` | `sk-ant-` | N/A |
| OpenAI | `openai` | `sk-` | o1/o3/o4 family → no JSON response format |

## Sensors Exposed

| Sensor | Description |
|--------|-------------|
| Energy Efficiency Score | 0–100 score from last analysis |
| Last Analysis Time | ISO timestamp |
| Total Tips Count | Number of tips returned |
| High Priority Tips | Count of high-priority tips |

## Configuration Options

Stored in config entry options:
- `analysis_interval`: 15 / 30 / 60 minutes
- `history_hours`: History window (12–48 h)
- `ai_model`: Provider-specific model string
- `tariff_type`: `fixed` or `dynamic` (Nord Pool)
- `notify`: bool — enable persistent HA notifications
- `selected_entities`: dict mapping category → list of entity_ids

## Running Tests

```bash
pytest tests/
# or with verbose output
pytest tests/ -v
```

All tests use `pytest-asyncio` (auto mode, configured in `pyproject.toml`).

## Linting

```bash
ruff check custom_components/ tests/
ruff format custom_components/ tests/
```

Line length: 100. Target: Python 3.11.

## Key Files to Read First

For any new work, start with:
1. `models.py` — understand the data structures
2. `coordinator.py` — understand the orchestration logic
3. The relevant `analysis/` or `processing/` module for the area you're working in

## HA Integration Notes

- Domain: `ha_energy_agent`
- Requires: `recorder` integration
- Minimum HA version: `2024.1.0`
- Minimum HACS version: `1.32.0`
- Platform: `sensor`
