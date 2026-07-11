"use strict";

const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];

const simulationForm = $("#simulation-form");
const simulationResult = $("#simulation-result");

const presets = {
  nominal: {
    sim_landing_weight: 64000,
    sim_touchdown_speed: 69,
    sim_crosswind: 8,
    sim_sink_rate: 1.2,
    sim_yaw: 2,
    sim_taxi_distance: 4.2,
    sim_taxi_speed: 14,
    sim_temperature: 29,
    sim_brake_temperature: 220,
    runway_condition: "DRY",
  },
  "hot-taxi": {
    sim_landing_weight: 66000,
    sim_touchdown_speed: 70,
    sim_crosswind: 7,
    sim_sink_rate: 1.3,
    sim_yaw: 2.5,
    sim_taxi_distance: 7,
    sim_taxi_speed: 23,
    sim_temperature: 42,
    sim_brake_temperature: 360,
    runway_condition: "ROUGH",
  },
  "hard-landing": {
    sim_landing_weight: 70000,
    sim_touchdown_speed: 78,
    sim_crosswind: 18,
    sim_sink_rate: 2.8,
    sim_yaw: 7,
    sim_taxi_distance: 4,
    sim_taxi_speed: 16,
    sim_temperature: 32,
    sim_brake_temperature: 470,
    runway_condition: "WET",
  },
};

function escapeHTML(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setLoading(container, message) {
  container.innerHTML = `
    <div class="loading-state">
      <span class="spinner" aria-hidden="true"></span>
      <span>${escapeHTML(message)}</span>
    </div>`;
}

function setError(container, error) {
  const details = error?.error?.details
    ?.map((detail) => `${detail.field}: ${detail.message}`)
    .join(" · ");
  const message = details || error?.error?.message || error?.message || "The request could not be completed.";
  container.innerHTML = `
    <div class="error-state">
      <span class="empty-icon">!</span>
      <h3>Check the inputs</h3>
      <p>${escapeHTML(message)}</p>
    </div>`;
}

async function postJSON(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) {
    throw body;
  }
  return body;
}

function boundedRange(center, spread, minimum, maximum) {
  return {
    minimum: Math.max(minimum, center - spread),
    most_likely: center,
    maximum: Math.min(maximum, center + spread),
  };
}

function numberValue(formData, name) {
  return Number(formData.get(name));
}

function simulationPayload(form) {
  const data = new FormData(form);
  const selectedDefects = $$('input[name="known_defects"]:checked', form).map(
    (input) => input.value,
  );
  return {
    profile_id: data.get("profile_id"),
    current_condition: {
      cycles_since_install: numberValue(data, "cycles_since_install"),
      current_tread_depth_mm: numberValue(data, "current_tread_depth_mm"),
      measured_cold_pressure_psi: numberValue(data, "measured_cold_pressure_psi"),
      reference_cold_pressure_psi: numberValue(data, "reference_cold_pressure_psi"),
      tire_temperature_c: 30,
      retread_count: 0,
      known_defects: selectedDefects,
    },
    horizon_cycles: numberValue(data, "horizon_cycles"),
    simulation_runs: numberValue(data, "simulation_runs"),
    random_seed: numberValue(data, "random_seed"),
    future_conditions: {
      landing_weight_kg: boundedRange(numberValue(data, "sim_landing_weight"), 6000, 50000, 73500),
      touchdown_ground_speed_ms: boundedRange(numberValue(data, "sim_touchdown_speed"), 6, 58, 82),
      crosswind_kt: boundedRange(numberValue(data, "sim_crosswind"), 8, 0, 25),
      touchdown_sink_rate_ms: boundedRange(numberValue(data, "sim_sink_rate"), 0.7, 0, 4),
      touchdown_yaw_angle_deg: boundedRange(numberValue(data, "sim_yaw"), 3, 0, 15),
      taxi_distance_km: boundedRange(numberValue(data, "sim_taxi_distance"), 1.5, 0.5, 8),
      average_taxi_speed_kt: boundedRange(numberValue(data, "sim_taxi_speed"), 6, 0, 30),
      outside_air_temperature_c: boundedRange(numberValue(data, "sim_temperature"), 10, 5, 45),
      brake_temperature_c: boundedRange(numberValue(data, "sim_brake_temperature"), 120, 0, 600),
      heavy_braking_probability: data.get("runway_condition") === "DRY" ? 0.05 : 0.12,
      runway_condition: data.get("runway_condition"),
    },
  };
}

function conditionStatusClass(status) {
  if (status.includes("REQUIRED") || status.includes("REACHED")) return "critical";
  if (status.includes("ATTENTION")) return "warning";
  return "";
}

function renderSimulation(data) {
  const forecast = data.forecast;
  const cycle = data.representative_cycle.result;
  const cycles = forecast.cycles_to_planning_threshold;
  const tread = forecast.final_tread_depth_mm;
  const comparison = data.pressure_policy_comparison;
  const probability = Math.round(forecast.probability_threshold_within_horizon * 100);
  const drivers = data.scenario_drivers
    .map((driver) => `<span>${escapeHTML(driver.replaceAll("_", " "))}</span>`)
    .join("");
  simulationResult.innerHTML = `
    <div class="result-content">
      <div class="result-head">
        <div><p>Complete assessment</p><h3>${escapeHTML(data.gear)} gear · ${escapeHTML(forecast.horizon_cycles)} cycles</h3></div>
        <span class="status-pill ${conditionStatusClass(data.current_condition.status)}">${escapeHTML(data.current_condition.status)}</span>
      </div>
      <div class="metric-grid">
        <div class="metric">
          <span>Representative-cycle severity</span><strong>${escapeHTML(cycle.severity.index)}</strong>
          <small>${escapeHTML(cycle.severity.level)} · most-likely conditions</small>
        </div>
        <div class="metric">
          <span>Representative-cycle wear</span><strong>${escapeHTML(cycle.estimated_wear_rate_mm_per_cycle)} mm</strong>
          <small>modeled wear per cycle</small>
        </div>
        <div class="metric wide">
          <span>Cycles to planning threshold</span><strong>${escapeHTML(cycles.p50)}</strong>
          <small>p10 ${escapeHTML(cycles.p10)} · p90 ${escapeHTML(cycles.p90)}</small>
        </div>
        <div class="metric">
          <span>Final tread at horizon</span><strong>${escapeHTML(tread.p50)} mm</strong>
          <small>p10 ${escapeHTML(tread.p10)} · p90 ${escapeHTML(tread.p90)}</small>
        </div>
        <div class="metric">
          <span>Threshold probability</span><strong>${escapeHTML(probability)}%</strong>
          <small>within ${escapeHTML(forecast.horizon_cycles)} cycles</small>
        </div>
        <div class="metric wide">
          <span>If reference pressure were maintained</span><strong>+${escapeHTML(comparison.estimated_median_cycle_difference)} cycles</strong>
          <small>${escapeHTML(comparison.current_pressure_policy_median_cycles)} current-policy vs ${escapeHTML(comparison.maintained_reference_pressure_median_cycles)} maintained-reference median</small>
        </div>
      </div>
      <div class="driver-card">
        <strong>Scenario drivers</strong>
        <p>Heuristic labels for understanding this input—not causal model explanations.</p>
        <div class="driver-list">${drivers}</div>
      </div>
      <div class="recommendation-card">
        <strong>${escapeHTML(data.recommendation.attention)}</strong>
        <p>${escapeHTML(data.recommendation.message)}</p>
      </div>
      <div class="guardrail-card">
        <strong>${escapeHTML(data.confidence.level)} confidence · certified limits ${escapeHTML(data.approved_limits.status)}</strong>
        <p>${escapeHTML(data.confidence.reason)} ${escapeHTML(data.unscheduled_removal_risk.message)}</p>
      </div>
      <details class="raw-details">
        <summary>View assumptions and raw API response</summary>
        <pre>${escapeHTML(JSON.stringify(data, null, 2))}</pre>
      </details>
    </div>`;
}

simulationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $('button[type="submit"]', simulationForm);
  setLoading(simulationResult, "Assessing current and future tire condition…");
  button.disabled = true;
  try {
    renderSimulation(await postJSON("/api/v1/tire-assessments", simulationPayload(simulationForm)));
  } catch (error) {
    setError(simulationResult, error);
  } finally {
    button.disabled = false;
  }
});

$$('[data-preset]').forEach((button) => {
  button.addEventListener("click", () => {
    const preset = presets[button.dataset.preset];
    Object.entries(preset).forEach(([name, value]) => {
      const input = simulationForm.elements.namedItem(name);
      if (input) input.value = value;
    });
    $$('[data-preset]').forEach((item) => item.classList.toggle("active", item === button));
  });
});
