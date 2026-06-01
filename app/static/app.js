/* ═══════════════════════════════════════════════════
   Modbus IEC104 Mock Interface – client-side logic
   ═══════════════════════════════════════════════════ */

"use strict";

// ── Track which inputs are currently focused so we don't overwrite them ──────
const focusedAddresses = new Set();
const MONITORING_RANGE_START = 10000;
const MONITORING_RANGE_END = 10999;
const CONTROL_RANGE_START = 11000;
const CONTROL_RANGE_END = 11999;

// ── BIT-field bit labels ──────────────────────────────────────────────────────
const BIT_LABELS = {
  10000: ["b0=Deactivated", "b1=Cyclic", "b2=On data change"],
  11062: ["b0=0%", "b1=30%", "b2=60%", "b3=100%"],
  11063: ["b0=0%", "b1=30%", "b2=60%", "b3=100%"],
};

// ── ON/OFF register addresses ─────────────────────────────────────────────────
// These show a labelled toggle instead of a plain number input.
const ON_OFF_NAMES = new Set([
  "ReactivePower_SetPoint_QU_ON_OFF",
  "ReactivePower_SetPoint_Q_kVar_ON_OFF",
  "ReactivePower_SetPoint_Q_percent_ON_OFF",
  "CosPhi_SetPoint_ON_OFF",
  "ActivePower_SetPoint_P_ON_OFF",
  "ActivePower_SetPoint_P_percent_ON_OFF",
  "ControlStage_SetPoint_percent_ON_OFF",
  "ControlStage_0_percent_SetPoint_ON_OFF",
  "ControlStage_30_percent_SetPoint_ON_OFF",
  "ControlStage_60_percent_SetPoint_ON_OFF",
  "ControlStage_100_percent_SetPoint_ON_OFF",
]);

// ─────────────────────────────────────────────────────────────────────────────
//  Rendering helpers
// ─────────────────────────────────────────────────────────────────────────────

function fmtEng(value, factor) {
  if (value === null || value === undefined) return "—";
  if (factor === 1000) return value.toFixed(3);
  if (factor === 0.01) return value.toFixed(2);
  return Number.isInteger(value) ? value.toString() : value.toFixed(3);
}

function buildWritableCell(reg, eng) {
  const addr = reg.address;
  const isOnOff = ON_OFF_NAMES.has(reg.name);

  if (reg.datatype === "BIT") {
    return buildBitInput(reg, eng);
  }

  if (isOnOff) {
    return buildToggle(reg, eng);
  }

  // Default: number input
  const wrap = document.createElement("span");
  wrap.className = "input-wrap";
  const inp = document.createElement("input");
  inp.type = "number";
  inp.id = `input-${addr}`;
  inp.className = "reg-input";
  inp.step = reg.factor < 1 ? reg.factor.toString() : "1";
  inp.value = eng !== null ? fmtEng(eng, reg.factor) : "0";
  inp.addEventListener("focus", () => focusedAddresses.add(addr));
  inp.addEventListener("blur", () => focusedAddresses.delete(addr));
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter") writeRegister(addr, parseFloat(inp.value), "ui");
  });
  const btn = document.createElement("button");
  btn.textContent = "✔";
  btn.title = "Write value";
  btn.addEventListener("click", () =>
    writeRegister(addr, parseFloat(inp.value), "ui")
  );
  wrap.appendChild(inp);
  wrap.appendChild(btn);
  return wrap;
}

function buildBitInput(reg, eng) {
  const addr = reg.address;
  const raw = eng !== null ? Math.round(eng / (reg.factor || 1)) : 0;
  const labels = BIT_LABELS[addr] || ["b0", "b1", "b2", "b3", "b5", "b6", "b7", "b8"];
  const wrap = document.createElement("span");
  wrap.className = "bit-wrap";
  wrap.id = `input-${addr}`;
  // Keep track of focused state via any checkbox inside
  wrap.addEventListener("focusin", () => focusedAddresses.add(addr));
  wrap.addEventListener("focusout", () => {
    // Delay so blur fires before we remove from set
    setTimeout(() => {
      if (!wrap.contains(document.activeElement)) focusedAddresses.delete(addr);
    }, 100);
  });

  for (let bit = 0; bit < labels.length; bit++) {
    const lbl = document.createElement("label");
    lbl.className = "bit-label";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.bit = bit;
    cb.checked = !!(raw & (1 << bit));
    cb.addEventListener("change", () => {
      let current = getCurrentBitValue(addr, labels.length);
      if (cb.checked) current |= 1 << bit;
      else current &= ~(1 << bit);
      writeRegister(addr, current * (reg.factor || 1), "ui");
    });
    lbl.appendChild(cb);
    lbl.appendChild(document.createTextNode(" " + labels[bit]));
    wrap.appendChild(lbl);
  }
  return wrap;
}

function getCurrentBitValue(addr, bits) {
  const wrap = document.getElementById(`input-${addr}`);
  if (!wrap) return 0;
  let v = 0;
  wrap.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    if (cb.checked) v |= 1 << parseInt(cb.dataset.bit);
  });
  return v;
}

function buildToggle(reg, eng) {
  const addr = reg.address;
  const isOn = eng !== null && eng !== 0;
  const wrap = document.createElement("span");
  wrap.className = "toggle-wrap";
  wrap.id = `input-${addr}`;
  const btn = document.createElement("button");
  btn.className = `toggle ${isOn ? "on" : "off"}`;
  btn.textContent = isOn ? "ON" : "OFF";
  btn.addEventListener("click", () => {
    const newVal = btn.classList.contains("on") ? 0 : 1;
    writeRegister(addr, newVal, "ui");
  });
  wrap.appendChild(btn);
  return wrap;
}

function buildReadonlyCell(eng, factor) {
  const span = document.createElement("span");
  span.className = "ro-value";
  span.textContent = fmtEng(eng, factor);
  return span;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Update helpers – only change DOM if value changed or input not focused
// ─────────────────────────────────────────────────────────────────────────────

function updateInput(addr, eng, factor, datatype) {
  if (focusedAddresses.has(addr)) return; // user is editing

  const el = document.getElementById(`input-${addr}`);
  if (!el) return;

  if (datatype === "BIT") {
    const raw = eng !== null ? Math.round(eng / (factor || 1)) : 0;
    el.querySelectorAll("input[type=checkbox]").forEach((cb) => {
      cb.checked = !!(raw & (1 << parseInt(cb.dataset.bit)));
    });
    return;
  }

  const isOnOff = el.classList.contains("toggle-wrap");
  if (isOnOff) {
    const btn = el.querySelector("button");
    if (!btn) return;
    const on = eng !== null && eng !== 0;
    btn.className = `toggle ${on ? "on" : "off"}`;
    btn.textContent = on ? "ON" : "OFF";
    return;
  }

  // Plain number input
  const inp = el.querySelector("input[type=number]");
  if (inp && !focusedAddresses.has(addr)) {
    const newVal = fmtEng(eng, factor);
    if (inp.value !== newVal) inp.value = newVal;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  API calls
// ─────────────────────────────────────────────────────────────────────────────

async function writeRegister(address, value, source) {
  try {
    const resp = await fetch(`/api/registers/${address}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value, source }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      alert(`Write error ${resp.status}: ${err.detail || JSON.stringify(err)}`);
    }
  } catch (e) {
    alert(`Network error: ${e}`);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Section builders (first render)
// ─────────────────────────────────────────────────────────────────────────────

let firstRender = true;

function buildCard(rv) {
  const { definition: reg, engineering_value: eng } = rv;
  const card = document.createElement("div");
  card.className = "reg-card";
  card.id = `card-${reg.address}`;

  const header = document.createElement("div");
  header.className = "reg-header";

  const nameEl = document.createElement("span");
  nameEl.className = "reg-name";
  nameEl.textContent = reg.name;

  const addrEl = document.createElement("span");
  addrEl.className = "reg-addr";
  addrEl.textContent = `#${reg.address}`;

  header.appendChild(nameEl);
  header.appendChild(addrEl);
  card.appendChild(header);

  const desc = document.createElement("div");
  desc.className = "reg-desc";
  desc.textContent = reg.description;
  card.appendChild(desc);

  const valueRow = document.createElement("div");
  valueRow.className = "reg-value-row";

  if (reg.access !== "read") {
    valueRow.appendChild(buildWritableCell(reg, eng));
  } else {
    const roSpan = document.createElement("span");
    roSpan.id = `ro-${reg.address}`;
    roSpan.className = "ro-value";
    roSpan.textContent = fmtEng(eng, reg.factor);
    valueRow.appendChild(roSpan);
  }

  const unitEl = document.createElement("span");
  unitEl.className = "reg-unit";
  unitEl.textContent = reg.unit !== "-" ? reg.unit : "";
  valueRow.appendChild(unitEl);

  card.appendChild(valueRow);
  return card;
}

function updateCard(rv) {
  const { definition: reg, engineering_value: eng } = rv;
  if (reg.access !== "read") {
    updateInput(reg.address, eng, reg.factor, reg.datatype);
  } else {
    const el = document.getElementById(`ro-${reg.address}`);
    if (el) el.textContent = fmtEng(eng, reg.factor);
  }
}

function renderAll(registers) {
  const sections = {
    monitoring: document.getElementById("grid-monitoring"),
    control: document.getElementById("grid-control"),
  };

  if (firstRender) {
    Object.values(sections).forEach((el) => (el.innerHTML = ""));
    for (const rv of registers) {
      const addr = rv.definition.address;
      let target = null;
      if (addr >= MONITORING_RANGE_START && addr <= MONITORING_RANGE_END) {
        target = sections.monitoring;
      } else if (addr >= CONTROL_RANGE_START && addr <= CONTROL_RANGE_END) {
        target = sections.control;
      }
      if (!target) continue;
      target.appendChild(buildCard(rv));
    }
    firstRender = false;
  } else {
    for (const rv of registers) {
      updateCard(rv);
    }
  }

  updateRawTable(registers);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Raw register table
// ─────────────────────────────────────────────────────────────────────────────

function updateRawTable(registers) {
  const tbody = document.getElementById("raw-tbody");
  if (!tbody) return;

  if (tbody.rows.length !== registers.length) {
    // Rebuild
    tbody.innerHTML = "";
    for (const rv of registers) {
      const r = rv.definition;
      const tr = document.createElement("tr");
      tr.id = `raw-row-${r.address}`;
      tr.innerHTML = `
        <td>${r.address}</td>
        <td>${r.name}</td>
        <td class="mono" id="raw-hex-${r.address}">0x0000</td>
        <td class="mono" id="raw-dec-${r.address}">0</td>
        <td id="raw-eng-${r.address}">0</td>
        <td>${r.unit}</td>
        <td>${r.access}</td>
        <td>${r.role}</td>
      `;
      tbody.appendChild(tr);
    }
  }

  for (const rv of registers) {
    const addr = rv.definition.address;
    const raw = Array.isArray(rv.raw_value)
      ? rv.raw_value
      : [rv.raw_value];
    const hexStr = raw
      .map((w) => "0x" + (w & 0xffff).toString(16).toUpperCase().padStart(4, "0"))
      .join(" ");
    const decStr = raw.join(", ");
    const engStr = fmtEng(rv.engineering_value, rv.definition.factor);

    const hexEl = document.getElementById(`raw-hex-${addr}`);
    const decEl = document.getElementById(`raw-dec-${addr}`);
    const engEl = document.getElementById(`raw-eng-${addr}`);
    if (hexEl) hexEl.textContent = hexStr;
    if (decEl) decEl.textContent = decStr;
    if (engEl) engEl.textContent = engStr;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  History table
// ─────────────────────────────────────────────────────────────────────────────

async function refreshHistory() {
  try {
    const data = await fetch("/api/history").then((r) => r.json());
    const tbody = document.getElementById("history-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";
    const recent = data.slice(-50).reverse();
    for (const rec of recent) {
      const tr = document.createElement("tr");
      const ts = new Date(rec.timestamp).toLocaleTimeString();
      tr.innerHTML = `
        <td>${ts}</td>
        <td><span class="source-badge source-${rec.source}">${rec.source}</span></td>
        <td>${rec.address}</td>
        <td>${rec.name}</td>
        <td class="mono">${rec.old_raw}</td>
        <td class="mono">${rec.new_raw}</td>
        <td>${typeof rec.engineering_value === "number" ? rec.engineering_value.toFixed(4) : rec.engineering_value}</td>
      `;
      tbody.appendChild(tr);
    }
  } catch (_) {
    // Ignore – history is non-critical
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Polling loop
// ─────────────────────────────────────────────────────────────────────────────

async function poll() {
  try {
    const registers = await fetch("/api/registers").then((r) => r.json());
    renderAll(registers);
    document.getElementById("status-text").textContent = "● Connected";
    document.getElementById("status-text").style.color = "#27ae60";
    document.getElementById("last-update").textContent =
      "Updated " + new Date().toLocaleTimeString();
  } catch (e) {
    document.getElementById("status-text").textContent = "● Disconnected";
    document.getElementById("status-text").style.color = "#e74c3c";
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  EMS simulation
// ─────────────────────────────────────────────────────────────────────────────

document.getElementById("sim-btn").addEventListener("click", async () => {
  const body = {
    active_power_kw: parseFloat(document.getElementById("sim-p").value) || 0,
    reactive_power_kvar: parseFloat(document.getElementById("sim-q").value) || 0,
    voltage_v: parseFloat(document.getElementById("sim-v").value) || 400,
    current_a: parseFloat(document.getElementById("sim-i").value) || 0,
    frequency_hz: parseFloat(document.getElementById("sim-f").value) || 50.0,
    soc_percent: parseFloat(document.getElementById("sim-soc").value) || 0,
  };
  try {
    const resp = await fetch("/api/simulate/ems", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const json = await resp.json();
    if (!resp.ok || json.errors) {
      console.warn("EMS sim errors:", json.errors);
    }
    await poll(); // Immediate refresh
  } catch (e) {
    alert(`EMS simulation error: ${e}`);
  }
});

// ─────────────────────────────────────────────────────────────────────────────
//  Boot
// ─────────────────────────────────────────────────────────────────────────────

poll();
setInterval(poll, 1000);
setInterval(refreshHistory, 2000);
