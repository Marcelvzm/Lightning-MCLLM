// LightningMCLLM web GUI — vanilla JS, no build step.
// Communicates with the FastAPI backend over /api and /api/ws.

const $ = (id) => document.getElementById(id);

const state = {
  status: null,
  show: null,
  envs: [],
  currentEnv: null,
  ws: null,
  selectedBank: null,
};

// ---------------------------------------------------------------- websocket

function connectWs() {
  const url = (location.protocol === "https:" ? "wss:" : "ws:") + "//" + location.host + "/api/ws";
  const ws = new WebSocket(url);
  state.ws = ws;
  ws.onopen = () => $("conn-status").classList.replace("offline", "online");
  ws.onclose = () => {
    $("conn-status").classList.replace("online", "offline");
    setTimeout(connectWs, 1000);
  };
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "status") onStatus(msg.data);
      if (msg.type === "show") onShow(msg.data);
    } catch (e) {
      console.error("bad ws msg", e);
    }
  };
}

// ----------------------------------------------------------------- HTTP

async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(await r.text());
  if (r.headers.get("content-type")?.includes("json")) return r.json();
  return r.text();
}
const cmd = (op, args = {}) => api("POST", `/api/cmd/${op}`, args);
const get = (path) => api("GET", path);

// ----------------------------------------------------------------- handlers

function onStatus(s) {
  state.status = s;
  $("bpm-value").textContent = s.bpm.toFixed(1);
  $("bpm-source").textContent = s.bpm_source;
  $("beat-pos").textContent = s.beat_position.toFixed(2);
  $("master-value").textContent = s.master.toFixed(2);
  $("dmx-status").textContent = (s.dmx_connected ? "✓ " : "✗ ") + s.dmx_description;
  $("dmx-status").style.color = s.dmx_connected ? "var(--green)" : "var(--red)";
  $("voice-count").textContent = s.active_voice_count;
  $("nonzero").textContent = s.last_frame_nonzero;
  $("tick-rate").textContent = s.actual_dt_ms.toFixed(1) + "ms / " + s.tick_rate_hz + "Hz";

  // active chases highlight
  document.querySelectorAll("#chases-list li").forEach(li => {
    const name = li.dataset.name;
    li.classList.toggle("active", s.active_chases.some(k => k === `chase:${name}` || k.startsWith(`chase:${name}:`)));
  });

  // active slot highlight (heuristic: chase slot with active chase)
  document.querySelectorAll(".slot[data-chase]").forEach(el => {
    el.classList.toggle("active", s.active_chases.some(k => k.startsWith(`chase:${el.dataset.chase}:`)));
  });

  // errors
  const errs = $("errors");
  errs.innerHTML = "";
  for (const e of (s.last_errors || [])) {
    const d = document.createElement("div"); d.textContent = e; errs.appendChild(d);
  }

  refreshShadow();
}

function onShow(sh) {
  state.show = sh;
  // genres
  const gsel = $("genre-select");
  gsel.innerHTML = '<option value="">— pick —</option>';
  for (const g of (sh.genres || [])) {
    const o = document.createElement("option");
    o.value = g.name;
    o.textContent = `${g.name} (${g.bpm} BPM)`;
    gsel.appendChild(o);
  }
  // scenes
  const scenes = $("scenes-list");
  scenes.innerHTML = "";
  for (const name of (sh.scenes || [])) {
    const li = document.createElement("li");
    li.textContent = name;
    li.dataset.name = name;
    li.onclick = () => cmd("snap_scene", { scene: name });
    scenes.appendChild(li);
  }
  // chases
  const chases = $("chases-list");
  chases.innerHTML = "";
  for (const c of (sh.chases || [])) {
    const li = document.createElement("li");
    const len = c.length_beats != null ? `${c.length_beats}b` : `${c.length_seconds}s`;
    li.textContent = `${c.name} (${len}, ${c.step_count} steps)`;
    li.dataset.name = c.name;
    li.onclick = () => {
      // toggle: if active, stop, else start
      const isActive = state.status?.active_chases?.some(k => k.startsWith(`chase:${c.name}:`));
      cmd(isActive ? "stop_chase" : "start_chase", { chase: c.name });
    };
    chases.appendChild(li);
  }
  // fixtures
  const fxs = $("fixtures-list");
  fxs.innerHTML = "";
  for (const f of (sh.fixtures || [])) {
    const li = document.createElement("li");
    li.textContent = `${f.name}  @${f.address.toString().padStart(3, "0")}+${f.footprint}  [${f.tags.join(",")}]`;
    fxs.appendChild(li);
  }
  // banks select
  const bankSel = $("bank-select");
  bankSel.innerHTML = "";
  for (const b of (sh.banks || [])) {
    const o = document.createElement("option"); o.value = b.name; o.textContent = b.name;
    bankSel.appendChild(o);
  }
  if ((sh.banks || []).length > 0) {
    if (!state.selectedBank || !sh.banks.find(b => b.name === state.selectedBank)) {
      state.selectedBank = sh.banks[0].name;
    }
    bankSel.value = state.selectedBank;
    renderSlots();
  }
}

function renderSlots() {
  const grid = $("slots-grid");
  grid.innerHTML = "";
  if (!state.show?.banks) return;
  const bank = state.show.banks.find(b => b.name === state.selectedBank);
  if (!bank) return;
  // Generate 3x3 grid (slots 1..9)
  for (let id = 1; id <= 9; id++) {
    const slot = bank.slots.find(s => s.id === id);
    const el = document.createElement("div");
    el.className = "slot";
    if (slot) {
      el.classList.toggle("blackout", slot.kind === "blackout");
      if (slot.kind === "chase") el.dataset.chase = slot.name;
      el.innerHTML = `
        <div class="id">${slot.id}</div>
        <div class="label">${slot.label || slot.name || slot.kind}</div>
        <div class="kind">${slot.kind}</div>
      `;
      el.onclick = () => cmd("fire_slot", { bank: state.selectedBank, slot_id: slot.id });
    } else {
      el.innerHTML = `<div class="id">${id}</div><div class="label" style="color:#444">—</div>`;
      el.style.cursor = "default";
    }
    grid.appendChild(el);
  }
}

// ----------------------------------------------------------------- shadow visualizer

let shadowFetching = false;
async function refreshShadow() {
  if (shadowFetching) return;
  shadowFetching = true;
  try {
    const r = await fetch("/api/shadow");
    if (!r.ok) return;
    const data = await r.json();
    const bytes = atob(data.frame_b64);
    drawShadow(bytes);
  } finally {
    shadowFetching = false;
  }
}

function drawShadow(byteString) {
  const canvas = $("universe-canvas");
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, w, h);
  // 512 channels in 1024 width => 2px per channel
  for (let i = 0; i < 512; i++) {
    const v = byteString.charCodeAt(i);
    ctx.fillStyle = `rgb(${v}, ${v}, ${v})`;
    ctx.fillRect(i * 2, 0, 2, h);
  }
}

// ----------------------------------------------------------------- env loading

async function refreshEnvs() {
  const data = await get("/api/environments");
  state.envs = data.environments;
  state.currentEnv = data.current;
  const sel = $("env-select");
  sel.innerHTML = "";
  for (const e of state.envs) {
    const o = document.createElement("option"); o.value = e; o.textContent = e;
    sel.appendChild(o);
  }
  sel.value = state.currentEnv || "";
  $("env-label").textContent = `env: ${state.currentEnv}`;
}

async function refreshShow() {
  const sh = await get("/api/show");
  onShow(sh);
}

// ----------------------------------------------------------------- bindings

function bind() {
  $("bpm-slider").oninput = (e) => {
    const v = parseFloat(e.target.value);
    $("bpm-input").value = v;
    cmd("set_bpm", { bpm: v, source: "manual" });
  };
  $("bpm-input").onchange = (e) => {
    const v = parseFloat(e.target.value);
    $("bpm-slider").value = v;
    cmd("set_bpm", { bpm: v, source: "manual" });
  };
  $("tap-btn").onclick = () => cmd("tap");
  $("master-slider").oninput = (e) => cmd("set_master", { value: parseFloat(e.target.value) });
  $("blackout-btn").onclick = () => cmd("blackout");
  $("release-blackout-btn").onclick = () => cmd("release_blackout");
  $("stop-all-btn").onclick = () => cmd("stop_all_chases");
  $("reload-btn").onclick = async () => {
    const r = await api("POST", "/api/reload");
    if (!r.ok) alert("Reload failed:\n" + (r.errors || []).join("\n"));
    await refreshShow();
  };
  $("env-select").onchange = async (e) => {
    const r = await api("POST", `/api/environments/${encodeURIComponent(e.target.value)}`);
    if (!r.ok) alert("Switch failed:\n" + (r.errors || []).join("\n"));
    state.currentEnv = e.target.value;
    $("env-label").textContent = `env: ${state.currentEnv}`;
    await refreshShow();
  };
  $("bank-select").onchange = (e) => { state.selectedBank = e.target.value; renderSlots(); };
  $("genre-apply").onclick = async () => {
    const g = $("genre-select").value;
    if (!g) return;
    const r = await api("POST", `/api/genres/${encodeURIComponent(g)}`);
    $("genre-hint").textContent = r.lead_chase ? `applied: ${g} (lead: ${r.lead_chase})` : `applied: ${g}`;
  };

  // Keyboard: 1-9 fire bank slots, Space = blackout
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.key >= "1" && e.key <= "9") {
      const id = parseInt(e.key);
      cmd("fire_slot", { bank: state.selectedBank, slot_id: id });
    }
    if (e.key === " ") { e.preventDefault(); cmd("blackout"); }
    if (e.key === "Escape") cmd("release_blackout");
    if (e.key === "t" || e.key === "T") cmd("tap");
  });
}

// ----------------------------------------------------------------- boot

(async () => {
  bind();
  await refreshEnvs();
  await refreshShow();
  connectWs();
})();
