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
  // Audio diagnostics: only show when detector is running.
  // Helps debug "audio (silent)" by showing actual RMS / confidence vs thresholds.
  const audioDiag = $("audio-diag");
  if (audioDiag) {
    if (s.audio && s.audio.running) {
      const a = s.audio;
      const rmsBad = a.rms < a.rms_threshold;
      const confBad = a.confidence < a.confidence_threshold;
      audioDiag.style.display = "";
      audioDiag.innerHTML =
        `<span title="audio level (root-mean-square)">RMS: <b style="color:${rmsBad ? 'var(--red)' : 'var(--green)'}">${a.rms.toFixed(4)}</b> ` +
        `<span class="muted-hint">/ thr ${a.rms_threshold}</span></span>` +
        `<span title="aubio beat-tracking confidence (0..1)">  Conf: <b style="color:${confBad ? 'var(--red)' : 'var(--green)'}">${a.confidence.toFixed(2)}</b> ` +
        `<span class="muted-hint">/ thr ${a.confidence_threshold}</span></span>` +
        `<span class="muted-hint">  raw BPM: ${a.bpm_raw.toFixed(1)}</span>` +
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
}

function renderShowState(showState) {
  const el = $("show-state");
  if (!showState) {
    el.innerHTML = '<span class="state-label">no show running</span>';
    return;
  }
  const stateClass = "state-" + showState.state;
  const elapsed = showState.elapsed_seconds || 0;
  const mins = Math.floor(elapsed / 60);
  const secs = (elapsed % 60).toFixed(1);
  el.innerHTML = `
    <span class="${stateClass}">${showState.state.toUpperCase()}</span>
    <span><b>${escapeHtml(showState.name)}</b></span>
    <span>elapsed: ${mins}:${secs.padStart(4, "0")}</span>
    <span>action: ${escapeHtml(showState.current_action || "—")}</span>
    ${showState.waiting ? `<span class="muted-hint">${escapeHtml(showState.waiting)}</span>` : ""}
  `;
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

(async () => {
  bind();
  await refreshEnvs();
  await refreshStage();
  connectWs();
})();
