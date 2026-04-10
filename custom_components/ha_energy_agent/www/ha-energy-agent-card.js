/**
 * HA Energy Agent — custom Lovelace card
 * Add to a dashboard with:  type: custom:ha-energy-agent-card
 */

const CARD_VERSION = "1.0.0";

const ENTITY = {
  score:       "sensor.ha_energy_agent_efficiency_score",
  last:        "sensor.ha_energy_agent_last_analysis",
  tips:        "sensor.ha_energy_agent_tips_count",
  highPrio:    "sensor.ha_energy_agent_high_priority_tips",
  todo:        "todo.ha_energy_agent_energy_tips",
};

const SERVICE_DOMAIN = "ha_energy_agent";
const SERVICE_RUN    = "run_analysis_now";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function scoreColor(val) {
  if (val === null) return "var(--disabled-color, #9E9E9E)";
  if (val >= 70)    return "var(--success-color, #4CAF50)";
  if (val >= 40)    return "var(--warning-color, #FF9800)";
  return               "var(--error-color, #F44336)";
}

function scoreLabel(val) {
  if (val === null) return "Unknown";
  if (val >= 70)    return "Good";
  if (val >= 40)    return "Fair";
  return               "Poor";
}

function stateOrDash(stateObj) {
  return stateObj ? stateObj.state : "—";
}

// ---------------------------------------------------------------------------
// Card element
// ---------------------------------------------------------------------------

class HaEnergyAgentCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
  }

  setConfig(config) {
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    const hass = this._hass;
    if (!hass) return;

    const scoreObj    = hass.states[ENTITY.score];
    const lastObj     = hass.states[ENTITY.last];
    const tipsObj     = hass.states[ENTITY.tips];
    const highPrioObj = hass.states[ENTITY.highPrio];

    const scoreVal    = scoreObj ? parseInt(scoreObj.state, 10) : null;
    const color       = scoreColor(scoreVal);
    const label       = scoreLabel(scoreVal);
    const tipsVal     = stateOrDash(tipsObj);
    const highVal     = stateOrDash(highPrioObj);
    const lastVal     = lastObj ? lastObj.state : "Never";
    const highNum     = highPrioObj ? parseInt(highPrioObj.state, 10) : 0;

    // Arc maths (r=28, cx/cy=32 ⟹ circumference≈175.9)
    const R     = 28;
    const CIRC  = 2 * Math.PI * R;
    const pct   = scoreVal !== null ? Math.max(0, Math.min(scoreVal, 100)) / 100 : 0;
    const dash  = (pct * CIRC).toFixed(1);
    const gap   = (CIRC - pct * CIRC).toFixed(1);

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card {
          padding: 16px;
          font-family: var(--paper-font-body1_-_font-family, sans-serif);
        }

        /* ── Header ── */
        .header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 14px;
        }
        .header-left {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .title {
          font-size: 1em;
          font-weight: 500;
          color: var(--primary-text-color);
        }

        /* ── Score row ── */
        .score-row {
          display: flex;
          align-items: center;
          gap: 16px;
          margin-bottom: 14px;
        }
        .arc-wrap { flex-shrink: 0; }
        svg .bg   { fill: none; stroke: var(--divider-color, #e0e0e0); stroke-width: 4; }
        svg .arc  { fill: none; stroke-width: 4; stroke-linecap: round;
                    transform: rotate(-90deg); transform-origin: 50% 50%; transition: stroke-dasharray .5s ease; }
        .score-text {
          font-size: 1.35em;
          font-weight: 700;
          fill: var(--primary-text-color);
        }
        .score-sub {
          font-size: 0.6em;
          fill: var(--secondary-text-color);
        }
        .score-desc { }
        .score-desc .label {
          font-size: 1em;
          font-weight: 500;
          color: ${color};
        }
        .score-desc .sublabel {
          font-size: 0.78em;
          color: var(--secondary-text-color);
          margin-top: 2px;
        }

        /* ── Metrics grid ── */
        .metrics {
          display: grid;
          grid-template-columns: 1fr 1fr 1fr;
          gap: 8px;
          margin-bottom: 12px;
        }
        .metric {
          background: var(--secondary-background-color);
          border-radius: 8px;
          padding: 8px 10px;
        }
        .metric-value {
          font-size: 1.15em;
          font-weight: 600;
          color: var(--primary-text-color);
        }
        .metric-value.urgent { color: var(--error-color, #F44336); }
        .metric-label {
          font-size: 0.72em;
          color: var(--secondary-text-color);
          margin-top: 2px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        /* ── Last analysis ── */
        .last-row {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.78em;
          color: var(--secondary-text-color);
        }

        /* ── Run button ── */
        mwc-button, ha-progress-button {
          --mdc-theme-primary: var(--primary-color);
        }
        .run-btn {
          background: none;
          border: 1px solid var(--primary-color);
          color: var(--primary-color);
          border-radius: 6px;
          padding: 4px 10px;
          font-size: 0.8em;
          cursor: pointer;
          font-family: inherit;
        }
        .run-btn:active { opacity: .7; }
      </style>

      <ha-card>
        <div class="header">
          <div class="header-left">
            <ha-icon icon="mdi:home-lightning-bolt" style="color:var(--primary-color)"></ha-icon>
            <span class="title">Energy Agent</span>
          </div>
          <button class="run-btn" id="run-btn">Run now</button>
        </div>

        <div class="score-row">
          <div class="arc-wrap">
            <svg width="64" height="64" viewBox="0 0 64 64">
              <circle class="bg" cx="32" cy="32" r="${R}"/>
              <circle class="arc"
                cx="32" cy="32" r="${R}"
                stroke="${color}"
                stroke-dasharray="${dash} ${gap}"
              />
              <text class="score-text" x="32" y="36" text-anchor="middle">
                ${scoreVal !== null ? scoreVal : "—"}
              </text>
            </svg>
          </div>
          <div class="score-desc">
            <div class="label">${label}</div>
            <div class="sublabel">Efficiency score</div>
          </div>
        </div>

        <div class="metrics">
          <div class="metric">
            <div class="metric-value">${tipsVal}</div>
            <div class="metric-label">Active tips</div>
          </div>
          <div class="metric">
            <div class="metric-value ${highNum > 0 ? "urgent" : ""}">${highVal}</div>
            <div class="metric-label">High priority</div>
          </div>
          <div class="metric" style="cursor:pointer" id="tips-btn">
            <div class="metric-value" style="font-size:.85em">📋</div>
            <div class="metric-label">View tips</div>
          </div>
        </div>

        <div class="last-row">
          <ha-icon icon="mdi:clock-outline" style="--mdc-icon-size:14px"></ha-icon>
          Last analysis: ${lastVal}
        </div>
      </ha-card>
    `;

    this.shadowRoot.getElementById("run-btn").addEventListener("click", () => {
      this._hass.callService(SERVICE_DOMAIN, SERVICE_RUN, {});
    });

    this.shadowRoot.getElementById("tips-btn").addEventListener("click", () => {
      const event = new CustomEvent("hass-more-info", {
        detail: { entityId: ENTITY.todo },
        bubbles: true,
        composed: true,
      });
      this.dispatchEvent(event);
    });
  }

  getCardSize() { return 3; }

  static getConfigElement() {
    // No config editor needed — card works with zero config
    return document.createElement("div");
  }

  static getStubConfig() {
    return {};
  }
}

customElements.define("ha-energy-agent-card", HaEnergyAgentCard);

// Register with the Lovelace card picker
window.customCards = window.customCards || [];
window.customCards.push({
  type:        "ha-energy-agent-card",
  name:        "HA Energy Agent",
  description: "Efficiency score, tips summary and one-click analysis trigger.",
  preview:     false,
});

console.info(
  `%c HA-ENERGY-AGENT-CARD %c v${CARD_VERSION} `,
  "background:#1976D2;color:#fff;padding:2px 4px;border-radius:3px 0 0 3px;font-weight:bold",
  "background:#424242;color:#fff;padding:2px 4px;border-radius:0 3px 3px 0"
);
