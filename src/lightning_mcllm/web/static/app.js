// LightningMCLLM web GUI — vanilla JS, no build step.
// Communicates with the FastAPI backend over /api and /api/ws.

const $ = (id) => document.getElementById(id);

const state = {
  status: null,
  stage: null,
  envs: [],
  currentEnv: null,
  ws: null,
  selectedShow: null,
  selectedBank: null,
  playMode: false,
  filter: "",
  bankFilter: "__all__",
  draggingTimeline: false,
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
      if (msg.type === "stage") onStage(msg.data);
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
const post = (path, body) => api("POST", path, body);

// ----------------------------------------------------------------- handlers

function onStatus(s) {
  state.status = s;
  $("bpm-value").textContent = s.bpm.toFixed(1);
  $("bpm-source").textContent = s.bpm_source;
  $("beat-pos").textContent = s.beat_position.toFixed(2);
  $("beat-pos").style.color = s.bpm_source.includes("silent") || !s.running ? "var(--red)" : "";
  // Audio button: highlight when audio detector is running (source starts with "audio")
  const audioBtn = $("audio-btn");
  if (audioBtn) {
    const audioOn = s.bpm_source && s.bpm_source.startsWith("audio");
    audioBtn.classList.toggle("active", audioOn);
    audioBtn.textContent = audioOn ? "🎵 Audio (ON)" : "🎵 Audio";
  }
  // Sync the pause-on-silence checkbox with engine state. When the
  // detector is running we know the truth; otherwise leave the box
  // alone so the user's preselection is preserved.
  const pauseChk = $("pause-on-silence");
  if (pauseChk && s.audio && typeof s.audio.pause_on_silence === "boolean") {
    if (pauseChk.checked !== s.audio.pause_on_silence) {
      pauseChk.checked = s.audio.pause_on_silence;
    }
  }
  // Audio diagnostics: only show when detector is running.
  // Helps debug "audio (silent)" by showing actual RMS / confidence vs thresholds.
  const audioDiag = $("audio-diag");
  if (audioDiag) {
    if (s.audio && s.audio.running) {
      const a = s.audio;
      const rmsBad = a.rms < a.rms_threshold;
      const confBad = a.confidence < a.confidence_threshold;
      audioDiag.style.display = "";
      const rangeStr = a.range ? `[${a.range[0]}-${a.range[1]}]` : "—";
      let multStr = "";
      if (a.range && a.bpm_multiplier === 0) {
        multStr = ` <b style="color:var(--red)">✗ outside range</b>`;
      } else if (a.bpm_multiplier && a.bpm_multiplier !== 1) {
        multStr = ` <b style="color:var(--accent)">→ ${a.bpm_corrected.toFixed(1)} (×${a.bpm_multiplier})</b>`;
      }
      audioDiag.innerHTML =
        `<span title="audio level (root-mean-square)">RMS: <b style="color:${rmsBad ? 'var(--red)' : 'var(--green)'}">${a.rms.toFixed(4)}</b> ` +
        `<span class="muted-hint">/ thr ${a.rms_threshold}</span></span>` +
        `<span title="aubio beat-tracking confidence (0..1)">  Conf: <b style="color:${confBad ? 'var(--red)' : 'var(--green)'}">${a.confidence.toFixed(2)}</b> ` +
        `<span class="muted-hint">/ thr ${a.confidence_threshold}</span></span>` +
        `<span class="muted-hint">  raw BPM: ${a.bpm_raw.toFixed(1)}</span>${multStr}` +
        `<span class="muted-hint">  range ${rangeStr}</span>` +
        `<span class="muted-hint">  ${a.silent ? '⏸ silent' : '▶ tracking'}</span>`;
    } else {
      audioDiag.style.display = "none";
    }
  }
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

  // bank slot active highlight
  document.querySelectorAll(".bank-slot-row .slot[data-chase]").forEach(el => {
    el.classList.toggle("active", s.active_chases.some(k => k.startsWith(`chase:${el.dataset.chase}:`)));
  });

  // show state display
  renderShowState(s.show);

  // errors
  const errs = $("errors");
  errs.innerHTML = "";
  for (const e of (s.last_errors || [])) {
    const d = document.createElement("div");
    d.textContent = e;
    errs.appendChild(d);
  }

  refreshShadow();
  refreshSim();
}

function _fmtTime(s) {
  s = Math.max(0, s || 0);
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed(1);
  return `${m}:${sec.padStart(4, "0")}`;
}

function renderShowState(showState) {
  const el = $("show-state");
  const tlRow = $("show-timeline-row");
  const refRow = $("show-refbpm-row");
  if (!showState) {
    el.innerHTML = '<span class="state-label">no show running</span>';
    if (tlRow) tlRow.style.display = "none";
    if (refRow) refRow.style.display = "none";
    return;
  }
  const stateClass = "state-" + showState.state;
  const elapsed = showState.elapsed_seconds || 0;
  const total = showState.length_seconds || 0;
  const estTag = showState.length_is_estimate ? " (est.)" : "";
  el.innerHTML = `
    <span class="${stateClass}">${showState.state.toUpperCase()}</span>
    <span><b>${escapeHtml(showState.name)}</b></span>
    <span>${_fmtTime(elapsed)} / ${_fmtTime(total)}${estTag}</span>
    <span>action: ${escapeHtml(showState.current_action || "—")}</span>
    ${showState.waiting ? `<span class="muted-hint">${escapeHtml(showState.waiting)}</span>` : ""}
  `;
  // Show timeline + reference-BPM rows when a show is loaded.
  if (tlRow) tlRow.style.display = "";
  if (refRow) refRow.style.display = "";
  // Update the slider position only if the user is not actively dragging.
  const slider = $("show-timeline");
  const label = $("show-timeline-label");
  if (slider && !state.draggingTimeline) {
    const max = Math.max(0.1, total);
    slider.max = String(Math.round(max * 10));  // 0.1s precision
    slider.value = String(Math.round(elapsed * 10));
  }
  if (label) label.textContent = `${_fmtTime(elapsed)} / ${_fmtTime(total)}${estTag}`;
  // Sync the reference-BPM input from server unless the user is editing it.
  const refInput = $("show-refbpm");
  const refHint = $("show-refbpm-hint");
  if (refInput && document.activeElement !== refInput && showState.reference_bpm) {
    if (parseFloat(refInput.value) !== showState.reference_bpm) {
      refInput.value = String(showState.reference_bpm);
    }
  }
  if (refHint) {
    refHint.textContent = showState.length_is_estimate
      ? "show contains wait_chase / wait_group — total is approximate"
      : "";
  }
}

function onStage(st) {
  state.stage = st;
  if (!st || !st.loaded) {
    $("scenes-list").innerHTML = "";
    $("chases-list").innerHTML = "";
    $("fixtures-list").innerHTML = "";
    return;
  }

  // shows dropdown
  const showSel = $("show-select");
  showSel.innerHTML = '<option value="">— select show —</option>';
  for (const sh of (st.shows || [])) {
    const o = document.createElement("option");
    o.value = sh.name;
    o.textContent = `${sh.name} (${sh.bpm} BPM, ${sh.script_length} actions)`;
    showSel.appendChild(o);
  }
  if (state.selectedShow && !st.shows.find(s => s.name === state.selectedShow)) {
    state.selectedShow = null;
  }
  if (state.selectedShow) showSel.value = state.selectedShow;

  // scenes
  const scenes = $("scenes-list");
  scenes.innerHTML = "";
  for (const name of (st.scenes || [])) {
    const li = document.createElement("li");
    li.dataset.name = name;
    li.dataset.kind = "scene";
    const kbdBadge = makeKbdBadgeForName("scene", name);
    li.innerHTML = `${kbdBadge}<span class="item-name">${escapeHtml(name)}</span>`;
    li.onclick = () => cmd("snap_scene", { scene: name });
    scenes.appendChild(li);
  }
  $("scenes-count").textContent = `(${(st.scenes || []).length})`;

  // chases
  const chases = $("chases-list");
  chases.innerHTML = "";
  for (const c of (st.chases || [])) {
    const li = document.createElement("li");
    li.dataset.name = c.name;
    li.dataset.kind = "chase";
    const len = c.length_beats != null ? `${c.length_beats}b` : `${c.length_seconds}s`;
    const kbdBadge = makeKbdBadgeForName("chase", c.name);
    li.innerHTML = `${kbdBadge}<span class="item-name">${escapeHtml(c.name)}</span><span class="item-meta">${len} · ${c.step_count}st</span>`;
    li.onclick = () => {
      const isActive = state.status?.active_chases?.some(k => k.startsWith(`chase:${c.name}:`));
      cmd(isActive ? "stop_chase" : "start_chase", { chase: c.name });
    };
    chases.appendChild(li);
  }
  $("chases-count").textContent = `(${(st.chases || []).length})`;

  // fixtures (read-only)
  const fxs = $("fixtures-list");
  fxs.innerHTML = "";
  for (const f of (st.fixtures || [])) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="item-name">${escapeHtml(f.name)}</span><span class="item-meta">@${f.address.toString().padStart(3, "0")}+${f.footprint} [${(f.tags || []).join(",")}]</span>`;
    fxs.appendChild(li);
  }
  $("fixtures-count").textContent = `(${(st.fixtures || []).length})`;

  // banks
  const bankSel = $("bank-select");
  bankSel.innerHTML = "";
  for (const b of (st.banks || [])) {
    const o = document.createElement("option"); o.value = b.name; o.textContent = b.name;
    bankSel.appendChild(o);
  }
  // bank filter dropdown (Triggers panel) — same options + leading "All"
  const bankFilter = $("bank-filter");
  bankFilter.innerHTML = '<option value="__all__">All</option>';
  for (const b of (st.banks || [])) {
    const o = document.createElement("option"); o.value = b.name; o.textContent = b.name;
    bankFilter.appendChild(o);
  }
  if (state.bankFilter !== "__all__" && !(st.banks || []).find(b => b.name === state.bankFilter)) {
    state.bankFilter = "__all__";
  }
  bankFilter.value = state.bankFilter;
  if ((st.banks || []).length > 0) {
    if (!state.selectedBank || !st.banks.find(b => b.name === state.selectedBank)) {
      state.selectedBank = st.banks[0].name;
    }
    bankSel.value = state.selectedBank;
    renderBankSlots();
  }

  applyFilter();
  // Re-apply active-chase highlight from the last known status — the
  // list rebuild above wiped the .active class. Without this, on every
  // hot-reload (i.e. every YAML save) the highlight blinks off until
  // the next status frame arrives.
  if (state.status?.active_chases) {
    const active = state.status.active_chases;
    document.querySelectorAll("#chases-list li").forEach(li => {
      const name = li.dataset.name;
      li.classList.toggle(
        "active",
        active.some(k => k === `chase:${name}` || k.startsWith(`chase:${name}:`)),
      );
    });
    document.querySelectorAll(".bank-slot-row .slot[data-chase]").forEach(el => {
      el.classList.toggle(
        "active",
        active.some(k => k.startsWith(`chase:${el.dataset.chase}:`)),
      );
    });
  }
}

function makeKbdBadgeForName(kind, name) {
  // In Play-Mode: find a keybinding pointing at this scene/chase
  if (!state.playMode || !state.selectedShow) return "";
  const sh = (state.stage?.shows || []).find(s => s.name === state.selectedShow);
  if (!sh) return "";
  for (const [key, b] of Object.entries(sh.keybindings || {})) {
    if (b.kind === kind && b.name === name) {
      return `<span class="kbd-badge">${escapeHtml(key)}</span>`;
    }
  }
  return "";
}

function renderBankSlots() {
  const row = $("bank-slot-row");
  row.innerHTML = "";
  if (!state.stage?.banks) return;
  const bank = state.stage.banks.find(b => b.name === state.selectedBank);
  if (!bank) return;
  for (const slot of bank.slots) {
    const el = document.createElement("div");
    el.className = "slot";
    el.classList.toggle("blackout", slot.kind === "blackout");
    if (slot.kind === "chase") el.dataset.chase = slot.name;
    el.innerHTML = `<span class="id">${slot.id}</span> ${escapeHtml(slot.label || slot.name || slot.kind)}`;
    el.onclick = () => cmd("fire_slot", { bank: state.selectedBank, slot_id: slot.id });
    row.appendChild(el);
  }
}

// ----------------------------------------------------------------- filter

function applyFilter() {
  const f = state.filter.trim().toLowerCase();
  // Build per-kind name sets for the selected bank, or null = "all".
  let bankScenes = null, bankChases = null;
  if (state.bankFilter && state.bankFilter !== "__all__") {
    const bank = (state.stage?.banks || []).find(b => b.name === state.bankFilter);
    if (bank) {
      bankScenes = new Set();
      bankChases = new Set();
      for (const slot of (bank.slots || [])) {
        if (slot.kind === "scene" && slot.name) bankScenes.add(slot.name);
        else if (slot.kind === "chase" && slot.name) bankChases.add(slot.name);
      }
    }
  }
  const lists = [
    ["scenes-list", bankScenes],
    ["chases-list", bankChases],
    ["fixtures-list", null],   // fixtures are never bank-filtered
  ];
  for (const [list, bankSet] of lists) {
    document.querySelectorAll(`#${list} li`).forEach(li => {
      const name = li.dataset.name || li.textContent;
      const lname = name.toLowerCase();
      const textHit = f === "" || lname.includes(f);
      const bankHit = bankSet === null || bankSet.has(name);
      li.classList.toggle("hidden", !(textHit && bankHit));
    });
  }
  // Update counts to reflect the visible items.
  const visible = (id) => document.querySelectorAll(`#${id} li:not(.hidden)`).length;
  const total = (arr) => (arr || []).length;
  const sCount = $("scenes-count"); if (sCount) sCount.textContent = `(${visible("scenes-list")}/${total(state.stage?.scenes)})`;
  const cCount = $("chases-count"); if (cCount) cCount.textContent = `(${visible("chases-list")}/${total(state.stage?.chases)})`;
}

// ----------------------------------------------------------------- shadow

let shadowFetching = false;
async function refreshShadow() {
  if (shadowFetching) return;
  shadowFetching = true;
  try {
    const r = await fetch("/api/shadow");
    if (!r.ok) return;
    const data = await r.json();
    drawShadow(atob(data.frame_b64));
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
  for (let i = 0; i < 512; i++) {
    const v = byteString.charCodeAt(i);
    ctx.fillStyle = `rgb(${v}, ${v}, ${v})`;
    ctx.fillRect(i * 2, 0, 2, h);
  }
}

// ----------------------------------------------------------------- sim view

let simFetching = false;
async function refreshSim() {
  if (simFetching) return;
  simFetching = true;
  try {
    const r = await fetch("/api/sim_state");
    if (!r.ok) return;
    drawSim(await r.json());
  } finally {
    simFetching = false;
  }
}

// Group fixtures by render-kind into rows. Bar/moving heads on top,
// effect bars in the middle, pars on the bottom. Within a group, sort
// by tag so head-1..head-4 stay left-to-right and cameo-1..3 stay in
// numeric order.
function _layoutFixtures(fixtures) {
  const tops = [], mids = [], bots = [];
  for (const f of fixtures) {
    if (f.kind === "moving_head") tops.push(f);
    else if (f.kind === "effect_bar" || f.tags?.includes("beam_bar")) mids.push(f);
    else bots.push(f);
  }
  const byName = (a, b) => a.name.localeCompare(b.name, "en", { numeric: true });
  tops.sort(byName);
  mids.sort(byName);
  bots.sort(byName);
  return [tops, mids, bots];
}

function drawSim(state) {
  const canvas = $("sim-canvas");
  if (!canvas) return;
  // High-DPI awareness
  const cssW = canvas.clientWidth, cssH = canvas.clientHeight;
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== cssW * dpr || canvas.height !== cssH * dpr) {
    canvas.width = cssW * dpr; canvas.height = cssH * dpr;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const fixtures = state.fixtures || [];
  if (fixtures.length === 0) {
    ctx.fillStyle = "#666"; ctx.font = "14px sans-serif";
    ctx.fillText("(no fixtures loaded)", 20, 30);
    return;
  }

  const rows = _layoutFixtures(fixtures);
  const rowYs = [cssH * 0.22, cssH * 0.55, cssH * 0.83];
  const radius = 28;

  for (let r = 0; r < rows.length; r++) {
    const row = rows[r];
    if (row.length === 0) continue;
    const y = rowYs[r];
    const stepX = cssW / (row.length + 1);
    for (let i = 0; i < row.length; i++) {
      const f = row[i];
      const x = stepX * (i + 1);
      _drawFixture(ctx, f, x, y, radius);
    }
  }
}

function _drawFixture(ctx, f, x, y, r) {
  const [cr, cg, cb] = f.color || [200, 200, 200];
  const intensity = Math.max(0, Math.min(1, f.intensity || 0));
  // Visible color = (color * intensity) on a neutral fixture body.
  const lit = `rgb(${Math.round(cr * intensity)}, ${Math.round(cg * intensity)}, ${Math.round(cb * intensity)})`;

  // RX350 / effect-bar: 4-LED horizontal strip rendering.
  if (f.kind === "effect_bar") {
    _drawEffectBar(ctx, f, x, y, r, lit);
    return;
  }

  // Outer ring (chassis)
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = "#1a1c22";
  ctx.fill();
  ctx.strokeStyle = "#333";
  ctx.lineWidth = 2;
  ctx.stroke();

  // Inner glowing lens
  if (intensity > 0.01) {
    const grad = ctx.createRadialGradient(x, y, 1, x, y, r * 0.95);
    grad.addColorStop(0, lit);
    grad.addColorStop(0.55, lit);
    grad.addColorStop(1, `rgba(${cr}, ${cg}, ${cb}, 0)`);
    ctx.beginPath();
    ctx.arc(x, y, r * 1.6 * intensity + r * 0.3, 0, Math.PI * 2);
    ctx.fillStyle = grad;
    ctx.fill();
  }

  // Inner solid disk for the actual lens
  ctx.beginPath();
  ctx.arc(x, y, r * 0.62, 0, Math.PI * 2);
  ctx.fillStyle = lit;
  ctx.fill();

  // Moving-head pan/tilt indicator
  if (f.kind === "moving_head" && f.pan != null && f.tilt != null) {
    // Map pan 0..255 → -1..+1, tilt 0..255 → -1..+1
    const px = (f.pan - 128) / 128;
    const py = (f.tilt - 128) / 128;
    // Pointer line from centre toward (px, py), max length r*0.55
    const len = r * 0.55;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + px * len, y + py * len);
    ctx.strokeStyle = intensity > 0.05 ? "rgba(255,255,255,0.85)" : "rgba(255,255,255,0.25)";
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    ctx.stroke();
    // small dot at tip
    ctx.beginPath();
    ctx.arc(x + px * len, y + py * len, 3, 0, Math.PI * 2);
    ctx.fillStyle = "white"; ctx.fill();
  }

  // Strobe overlay flash
  if (f.strobe > 0.05) {
    const flashOn = (Date.now() / (50 + (1 - f.strobe) * 200)) % 1 < 0.5;
    if (flashOn) {
      ctx.beginPath();
      ctx.arc(x, y, r * 0.62, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      ctx.fill();
    }
  }

  // Label
  ctx.fillStyle = "#aab";
  ctx.font = "11px ui-monospace, monospace";
  ctx.textAlign = "center";
  ctx.fillText(f.name, x, y + r + 16);
  ctx.textAlign = "start";
}

// Draw the RX350 (and other effect-bars) as a horizontal 4-LED strip.
// For combo modes (red+green, red+blue, …) we synthesise the per-LED
// colours from the macro value so the user can tell them apart at a
// glance. Not photometrically correct — just visually distinctive.
function _drawEffectBar(ctx, f, x, y, r, lit) {
  const w = r * 4.2, h = r * 0.95;
  const left = x - w / 2, top = y - h / 2;
  // Chassis
  ctx.fillStyle = "#1a1c22";
  ctx.fillRect(left, top, w, h);
  ctx.strokeStyle = "#333";
  ctx.lineWidth = 2;
  ctx.strokeRect(left, top, w, h);

  // Per-LED colour mix for combined modes — read the raw macro value
  // and split into a 4-LED pattern.
  const macro = f.raw_macro != null ? f.raw_macro : 0;
  const ledColors = _rx350LedSplit(macro, f.color);
  const intensity = Math.max(0, Math.min(1, f.intensity || 0));

  // 4 LEDs, evenly spaced along the bar
  const ledR = h * 0.32;
  for (let i = 0; i < 4; i++) {
    const cx = left + (w / 5) * (i + 1);
    const cy = y;
    const [cr, cg, cb] = ledColors[i];
    const on = intensity > 0.01 && (cr + cg + cb) > 0;
    const fill = on
      ? `rgb(${Math.round(cr * intensity)}, ${Math.round(cg * intensity)}, ${Math.round(cb * intensity)})`
      : "#080a0e";
    if (on) {
      const grad = ctx.createRadialGradient(cx, cy, 1, cx, cy, ledR * 2.4);
      grad.addColorStop(0, fill);
      grad.addColorStop(1, `rgba(${cr}, ${cg}, ${cb}, 0)`);
      ctx.beginPath();
      ctx.arc(cx, cy, ledR * 2.4, 0, Math.PI * 2);
      ctx.fillStyle = grad; ctx.fill();
    }
    ctx.beginPath();
    ctx.arc(cx, cy, ledR, 0, Math.PI * 2);
    ctx.fillStyle = fill;
    ctx.fill();
  }

  // Strobe overlay
  if (f.strobe > 0.05) {
    const flashOn = (Date.now() / (50 + (1 - f.strobe) * 200)) % 1 < 0.5;
    if (flashOn) {
      ctx.fillStyle = "rgba(255,255,255,0.7)";
      ctx.fillRect(left + 2, top + 2, w - 4, h - 4);
    }
  }

  // Label below
  ctx.fillStyle = "#aab";
  ctx.font = "11px ui-monospace, monospace";
  ctx.textAlign = "center";
  ctx.fillText(`${f.name} · m=${macro}`, x, top + h + 16);
  ctx.textAlign = "start";
}

// Given the raw RX350 macro value and the resolved single-colour from
// the backend, produce 4 per-LED colours. Combined modes (e.g. red+blue)
// alternate between the two component colours; pure modes use the same
// colour on every LED. "all" mode (mode 11) cycles through 4 distinct
// colours so the user can see it differs from pure white.
function _rx350LedSplit(macro, fallback) {
  const RED = [255, 0, 0], GREEN = [0, 220, 0], BLUE = [40, 60, 255];
  const YELLOW = [255, 230, 0], WHITE = [255, 255, 255];
  if (macro <= 0) return [[0,0,0], [0,0,0], [0,0,0], [0,0,0]];
  if (macro <= 22)  return [RED, RED, RED, RED];
  if (macro <= 45)  return [GREEN, GREEN, GREEN, GREEN];
  if (macro <= 68)  return [BLUE, BLUE, BLUE, BLUE];
  if (macro <= 91)  return [YELLOW, YELLOW, YELLOW, YELLOW];
  if (macro <= 114) return [WHITE, WHITE, WHITE, WHITE];
  if (macro <= 137) return [YELLOW, WHITE, YELLOW, WHITE];          // yellow + white
  if (macro <= 160) return [RED, GREEN, RED, GREEN];                 // red + green
  if (macro <= 183) return [RED, BLUE, RED, BLUE];                   // red + blue
  if (macro <= 206) return [GREEN, BLUE, GREEN, BLUE];               // green + blue
  if (macro <= 229) return [RED, GREEN, BLUE, RED];                  // rgb together
  if (macro <= 252) return [RED, GREEN, BLUE, YELLOW];               // all on
  // music — pulse magenta-ish, fall back to single color from server
  return [fallback, fallback, fallback, fallback];
}

// ----------------------------------------------------------------- env

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

async function refreshStage() {
  const st = await get("/api/stage");
  onStage(st);
}

// ----------------------------------------------------------------- play mode

function setPlayMode(on) {
  state.playMode = !!on;
  $("play-mode-toggle").textContent = `Play Mode: ${on ? "ON" : "OFF"}`;
  $("play-mode-toggle").classList.toggle("on", on);
  $("play-mode-indicator").style.display = on ? "" : "none";
  $("play-mode-hint").textContent = on
    ? `Active. Show: ${state.selectedShow || "(none)"}. Custom keys override default shortcuts.`
    : "When ON, the show's keybindings drive the keyboard.";
  // Re-render lists to update kbd badges
  if (state.stage) onStage(state.stage);
}

// ----------------------------------------------------------------- key handler

function handleKey(e) {
  const tag = e.target.tagName;
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;

  // Universal safety: BLACKOUT and Esc always work
  if (e.key === " ") { e.preventDefault(); cmd("blackout"); return; }
  if (e.key === "Escape") { cmd("release_blackout"); return; }

  if (state.playMode && state.selectedShow) {
    // Lookup show keybindings
    const sh = (state.stage?.shows || []).find(s => s.name === state.selectedShow);
    if (sh) {
      const lookupKey = e.key.length === 1 ? e.key.toUpperCase() : e.key;
      const binding = (sh.keybindings || {})[lookupKey];
      if (binding) {
        e.preventDefault();
        firePlayBinding(binding);
        return;
      }
    }
    // In play mode, do NOT fall through to default 1-9 bank-slot bindings —
    // the user opted into the show's vocabulary.
    return;
  }

  // Default keyboard mode
  if (e.key >= "1" && e.key <= "9") {
    const id = parseInt(e.key);
    cmd("fire_slot", { bank: state.selectedBank, slot_id: id });
  }
  if (e.key === "t" || e.key === "T") cmd("tap");
}

function firePlayBinding(b) {
  if (b.kind === "scene") cmd("snap_scene", { scene: b.name });
  else if (b.kind === "chase") {
    const isActive = state.status?.active_chases?.some(k => k.startsWith(`chase:${b.name}:`));
    cmd(isActive ? "stop_chase" : "start_chase", { chase: b.name });
  }
  else if (b.kind === "blackout") cmd("blackout");
  else if (b.kind === "release_blackout") cmd("release_blackout");
  else if (b.kind === "stop_all_chases") cmd("stop_all_chases");
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
  $("audio-btn").onclick = () => {
    const src = state.status?.bpm_source || "";
    cmd(src.startsWith("audio") ? "stop_audio" : "start_audio");
  };
  $("bpm-genre").onchange = (e) => {
    const opt = e.target.selectedOptions[0];
    const lo = opt?.dataset.min, hi = opt?.dataset.max;
    if (lo && hi) cmd("set_bpm_range", { min: parseFloat(lo), max: parseFloat(hi) });
    else cmd("set_bpm_range", {});  // empty = clear
  };
  $("pause-on-silence").onchange = (e) => {
    cmd("set_pause_on_silence", { enabled: e.target.checked });
  };
  $("all-off-btn").onclick = () => cmd("all_off");
  $("master-slider").oninput = (e) => cmd("set_master", { value: parseFloat(e.target.value) });
  $("blackout-btn").onclick = () => cmd("blackout");
  $("release-blackout-btn").onclick = () => cmd("release_blackout");
  $("stop-all-btn").onclick = () => cmd("stop_all_chases");

  $("reload-btn").onclick = async () => {
    const r = await post("/api/reload");
    if (!r.ok) alert("Reload failed:\n" + (r.errors || []).join("\n"));
    await refreshStage();
  };
  $("env-select").onchange = async (e) => {
    const r = await post(`/api/environments/${encodeURIComponent(e.target.value)}`);
    if (!r.ok) alert("Switch failed:\n" + (r.errors || []).join("\n"));
    state.currentEnv = e.target.value;
    $("env-label").textContent = `env: ${state.currentEnv}`;
    await refreshStage();
  };

  // Show controls
  $("show-select").onchange = (e) => {
    state.selectedShow = e.target.value || null;
    if (state.stage) onStage(state.stage);
    setPlayMode(state.playMode);  // refresh hint
  };
  $("show-play-btn").onclick = async () => {
    if (!state.selectedShow) { alert("Pick a show first."); return; }
    await post(`/api/show/${encodeURIComponent(state.selectedShow)}/play`);
  };
  $("show-pause-btn").onclick = () => post("/api/show/pause");
  $("show-resume-btn").onclick = () => post("/api/show/resume");
  $("show-reset-btn").onclick = () => post("/api/show/reset");
  $("show-stop-btn").onclick = () => post("/api/show/stop");
  // Reload — forces a stage rebuild from disk. The engine remembers the
  // running show and auto-replays it once the stage swap is done.
  $("show-reload-btn").onclick = () => post("/api/reload");

  const tl = $("show-timeline");
  if (tl) {
    // While the user drags, suppress server-driven slider updates so the
    // thumb doesn't jump back to the playhead between mousemoves. Seek
    // only on release.
    tl.addEventListener("pointerdown", () => { state.draggingTimeline = true; });
    tl.addEventListener("input", () => {
      // Live label update during drag, but no server hit yet.
      const total = (state.status?.show?.length_seconds) || 0;
      const seconds = parseFloat(tl.value) / 10;
      const estTag = state.status?.show?.length_is_estimate ? " (est.)" : "";
      const lbl = $("show-timeline-label");
      if (lbl) lbl.textContent = `${_fmtTime(seconds)} / ${_fmtTime(total)}${estTag}`;
    });
    const commit = () => {
      if (!state.draggingTimeline) return;
      state.draggingTimeline = false;
      const seconds = parseFloat(tl.value) / 10;
      const refInput = $("show-refbpm");
      const ref = refInput ? parseFloat(refInput.value) : undefined;
      cmd("seek_show", { target_seconds: seconds, reference_bpm: ref });
    };
    tl.addEventListener("pointerup", commit);
    tl.addEventListener("pointercancel", commit);
    tl.addEventListener("change", commit);
  }
  const refInput = $("show-refbpm");
  if (refInput) {
    refInput.addEventListener("change", () => {
      const v = parseFloat(refInput.value);
      if (v > 0) cmd("set_show_reference_bpm", { bpm: v });
    });
  }
  $("play-mode-toggle").onclick = () => setPlayMode(!state.playMode);

  $("bank-select").onchange = (e) => { state.selectedBank = e.target.value; renderBankSlots(); };
  $("bank-filter").onchange = (e) => { state.bankFilter = e.target.value; applyFilter(); };
  $("trigger-filter").oninput = (e) => { state.filter = e.target.value; applyFilter(); };

  document.addEventListener("keydown", handleKey);
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

// ----------------------------------------------------------------- boot

async function refreshBpmGenres() {
  try {
    const data = await get("/api/bpm_genres");
    const sel = $("bpm-genre");
    if (!sel) return;
    // Keep the current selection across refreshes if still present.
    const prev = sel.value;
    sel.innerHTML = '<option value="">— no genre —</option>';
    for (const g of (data.genres || [])) {
      const o = document.createElement("option");
      o.value = g.name;
      o.textContent = `${g.name} (${g.min}-${g.max})`;
      o.dataset.min = g.min;
      o.dataset.max = g.max;
      sel.appendChild(o);
    }
    if (prev) sel.value = prev;
  } catch (e) { /* genre file dir missing — leave dropdown with just "no genre" */ }
}

(async () => {
  bind();
  await refreshEnvs();
  await refreshStage();
  await refreshBpmGenres();
  connectWs();
})();
