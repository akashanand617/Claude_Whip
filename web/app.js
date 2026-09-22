/* Whip ring console. Vanilla JS, no build step, one websocket. */
"use strict";

const $ = (id) => document.getElementById(id);
const api = async (method, path, body) => {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
};

/* ---------------------------------------------------------------- tabs */
document.querySelectorAll("nav .tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav .tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    ["live", "flash", "settings"].forEach((name) => {
      $("tab-" + name).hidden = name !== btn.dataset.tab;
    });
  });
});

/* ---------------------------------------------------------------- state */
let state = "idle";

function renderState(status) {
  state = status.state;
  const pill = $("state-pill");
  pill.textContent = state;
  pill.className = "pill " + state;
  $("device-line").textContent = status.device
    ? `${status.device.name || "ring"} (fw ${status.device.firmware || "?"})` : "";
  $("battery-line").textContent = status.battery != null ? `🔋 ${status.battery}%` : "";
  $("btn-connect").hidden = state !== "idle";
  $("btn-disconnect").hidden = state === "idle" || state === "flashing";
  const stream = $("btn-stream");
  stream.disabled = !(state === "connected" || state === "streaming");
  stream.textContent = state === "streaming" ? "Stop tracking" : "Start tracking";
  const mode = { gesture: "Gesture firmware (25 Hz) — ready for tracking",
                 stock: "Stock firmware — flash the gesture image to track gestures",
                 unknown: "Firmware not recognised" }[status.mode || "unknown"];
  $("mode-line").textContent = status.device ? `Current mode: ${mode}` : "Connect to see the ring's current firmware.";
}

$("btn-connect").addEventListener("click", async () => {
  $("btn-connect").disabled = true;
  try { renderState(await api("POST", "/api/connect", {})); }
  catch (e) { alertBox(e.message); }
  finally { $("btn-connect").disabled = false; }
});
$("btn-disconnect").addEventListener("click", async () => {
  try { renderState(await api("POST", "/api/disconnect")); } catch (e) { alertBox(e.message); }
});
$("btn-stream").addEventListener("click", async () => {
  try {
    renderState(await api("POST", state === "streaming" ? "/api/stream/stop" : "/api/stream/start"));
  } catch (e) { alertBox(e.message); }
});

function alertBox(message) {
  const li = document.createElement("li");
  li.className = "error";
  li.textContent = message;
  $("events").prepend(li);
}

/* ---------------------------------------------------------------- live */
const wave = $("wave");
const ctx = wave.getContext("2d");
let trace = [];             // recent [t, x, y, z] in counts

function drawWave() {
  const w = wave.width = wave.clientWidth;
  const h = wave.height;
  ctx.clearRect(0, 0, w, h);
  if (trace.length < 2) return;
  const colours = ["#e05252", "#52a852", "#5277e0"];
  const scale = h / 2 / 33000;   // full-scale counts
  for (let axis = 0; axis < 3; axis++) {
    ctx.beginPath();
    ctx.strokeStyle = colours[axis];
    trace.forEach((s, i) => {
      const x = (i / (trace.length - 1)) * w;
      const y = h / 2 - s[axis + 1] * scale;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }
}

function renderProbs(probs) {
  const box = $("probs");
  box.innerHTML = "";
  Object.entries(probs).forEach(([name, p]) => {
    const row = document.createElement("div");
    row.className = "prob-row";
    row.innerHTML = `<span class="prob-name">${name}</span>
      <div class="bar"><div class="fill${name === "none" ? " none" : ""}"
           style="width:${(p * 100).toFixed(1)}%"></div></div>
      <span class="prob-val">${(p * 100).toFixed(0)}%</span>`;
    box.appendChild(row);
  });
}

function renderEvent(ev) {
  const li = document.createElement("li");
  const dir = ev.direction && ev.direction !== "none" ? ` <strong>${ev.direction.toUpperCase()}</strong>` : "";
  const action = ev.action ? ` → <strong>${ev.action.toUpperCase()}</strong>` : "";
  const lat = ev.latency_s != null ? ` <span class="conf">decided ${ev.latency_s.toFixed(2)}s after onset</span>` : "";
  li.innerHTML = `<span class="t">${ev.t_s.toFixed(1)}s</span>
    <span class="gesture">${ev.name.replace("_", " ")}${dir}</span>
    <span class="conf">${(ev.confidence * 100).toFixed(0)}%</span>${action}${lat}`;
  $("events").prepend(li);
  while ($("events").children.length > 40) $("events").lastChild.remove();
}

/* A movement the decoder judged but did not turn into a gesture. Shown so
   "nothing happened" and "that was one long movement" look different. */
const BURST_REASONS = {
  too_long: "one continuous movement, too long for a gesture",
  no_consensus: "movement, but the windows did not agree on a gesture",
  no_votes: "movement too close to another to judge on its own",
};
function renderBurst(b) {
  if (!(b.outcome in BURST_REASONS)) return;   // outcomes that are gestures arrive as events
  const li = document.createElement("li");
  li.className = "movement";
  li.innerHTML = `<span class="t">${b.on_s.toFixed(1)}s</span>
    <span class="gesture">movement ${b.duration_s.toFixed(1)}s</span>
    <span class="conf">${BURST_REASONS[b.outcome]}</span>`;
  $("events").prepend(li);
  while ($("events").children.length > 40) $("events").lastChild.remove();
}

/* ---------------------------------------------------------------- flash */
let chosenTarget = null;

async function loadTargets() {
  const targets = await api("GET", "/api/flash/targets");
  const box = $("targets");
  box.innerHTML = "";
  Object.entries(targets).forEach(([name, spec]) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<h3>${spec.title}</h3><p>${spec.description}</p>
      <p class="muted">${spec.image}</p><button>Choose</button>`;
    card.querySelector("button").addEventListener("click", () => {
      chosenTarget = name;
      $("flash-flow").hidden = false;
      $("flash-title").textContent = spec.title;
      $("validate-result").textContent = "";
      $("confirm-word").value = "";
      $("confirm-word").disabled = true;
      $("btn-flash").disabled = true;
      $("step-confirm").classList.add("dim");
      $("flash-log").hidden = true;
      $("flash-log").textContent = "";
      $("flash-progress").hidden = true;
    });
    box.appendChild(card);
  });
}

$("btn-validate").addEventListener("click", async () => {
  $("validate-result").textContent = "validating…";
  try {
    const out = await api("POST", "/api/flash/validate", { target: chosenTarget });
    $("validate-result").textContent =
      `✓ ${out.chunks} chunks, ${out.ble_writes} BLE writes verified` +
      (out.armed ? "" : ` — ${out.note}`);
    if (out.armed) {
      $("confirm-word").disabled = false;
      $("step-confirm").classList.remove("dim");
    }
  } catch (e) { $("validate-result").textContent = "✗ " + e.message; }
});

$("confirm-word").addEventListener("input", () => {
  $("btn-flash").disabled = $("confirm-word").value.trim() !== "FLASH";
});

$("btn-flash").addEventListener("click", async () => {
  $("btn-flash").disabled = true;
  $("flash-log").hidden = false;
  $("flash-progress").hidden = false;
  try {
    await api("POST", "/api/flash", { target: chosenTarget, confirm: $("confirm-word").value.trim() });
  } catch (e) { flashLog("ABORTED: " + e.message); }
});

function flashLog(line) {
  const log = $("flash-log");
  log.hidden = false;
  log.textContent += line + "\n";
  log.scrollTop = log.scrollHeight;
}

function renderFlash(msg) {
  if (msg.stage === "fact") flashLog(`${msg.name}: ${msg.value}`);
  else if (msg.stage === "data") {
    $("flash-progress").hidden = false;
    $("flash-progress").value = (msg.done / msg.total) * 100;
    if (msg.done === msg.total) flashLog("all data frames acknowledged");
  } else if (msg.stage === "frame") flashLog(`${msg.frame}: ${msg.message}`);
  else if (msg.stage === "message") flashLog(msg.message);
  else if (msg.stage === "done") flashLog("✓ " + msg.message + " Reconnect once it has rebooted.");
  else if (msg.stage === "aborted") flashLog("✗ " + msg.message);
}

/* -------------------------------------------------------------- settings */
let mappings = {};

function renderMappings() {
  const body = $("mappings").querySelector("tbody");
  body.innerHTML = "";
  Object.entries(mappings).forEach(([gesture, action]) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><code>${gesture}</code></td><td>${action}</td>
      <td><button class="small">remove</button></td>`;
    tr.querySelector("button").addEventListener("click", () => {
      delete mappings[gesture];
      renderMappings();
    });
    body.appendChild(tr);
  });
}

$("btn-add-mapping").addEventListener("click", () => {
  const gesture = $("map-gesture").value.trim();
  const action = $("map-action").value.trim();
  if (!gesture || !action) return;
  mappings[gesture] = action;
  $("map-gesture").value = ""; $("map-action").value = "";
  renderMappings();
});

$("threshold").addEventListener("input", () => {
  $("threshold-value").textContent = Number($("threshold").value).toFixed(2);
});

$("btn-save-settings").addEventListener("click", async () => {
  try {
    await api("PUT", "/api/config", { mappings, threshold: Number($("threshold").value) });
    $("settings-result").textContent = "saved ✓";
    setTimeout(() => { $("settings-result").textContent = ""; }, 2000);
  } catch (e) { $("settings-result").textContent = e.message; }
});

async function loadSettings() {
  const config = await api("GET", "/api/config");
  mappings = config.mappings || {};
  renderMappings();
  $("threshold").value = config.threshold;
  $("threshold-value").textContent = Number(config.threshold).toFixed(2);
}

async function loadModel() {
  const model = await api("GET", "/api/model");
  $("model-line").textContent = model.available
    ? `model: ${model.labels.join(", ")}`
    : `no model — ${model.reason}`;
}

/* ---------------------------------------------------------------- socket */
function connectSocket() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (raw) => {
    const msg = JSON.parse(raw.data);
    if (msg.type === "state") { renderState(msg); renderCalibrationFromStatus(msg); }
    else if (msg.type === "live") {
      trace = trace.concat(msg.samples).slice(-400);
      drawWave();
      renderProbs(msg.probabilities || {});
      noteEngineFrame(msg.frame);
    } else if (msg.type === "calibration") renderCalibration(msg);
    else if (msg.type === "event") renderEvent(msg);
    else if (msg.type === "flash") renderFlash(msg);
    else if (msg.type === "error") alertBox(msg.message);
  };
  ws.onclose = () => setTimeout(connectSocket, 1500);
}

/* ---------------------------------------------------------- calibration */
/* The gate every tracking session passes through, and the one place the
   wearer is told WHY a pose is not being accepted: moving, or fingers not at
   the floor (with the angle), or simply not held long enough yet. */
let calFrame = null;

function setCheck(id, state, detail) {
  const li = $(id);
  li.className = state;
  li.querySelector(".detail").textContent = detail || "";
}

function wearingText(frame, wearing) {
  return wearing === "canonical"
    ? "ring worn the trained way (sensor below the finger)"
    : `ring worn the other way round — corrected automatically (${frame})`;
}

function renderCalibration(msg) {
  const card = $("cal");
  const status = msg.status;
  card.className = "card cal " + (status === "ok" ? "ok" : status === "retry" ? "retry" : "hold");
  $("cal-progress").hidden = false;
  $("cal-checks").hidden = false;
  $("cal-result").hidden = status !== "ok";
  $("btn-recal").hidden = status !== "ok";
  $("events").classList.toggle("held", status !== "ok");
  const frac = Math.max(0, Math.min(1, (msg.held_s || 0) / (msg.hold_s || 3)));
  $("cal-fill").style.width = `${(frac * 100).toFixed(0)}%`;
  const left = Math.max(0, (msg.hold_s || 3) - (msg.held_s || 0));

  if (status === "ok") {
    calFrame = msg.frame;
    $("cal-title").textContent = "Calibrated";
    $("cal-msg").textContent = "Pose accepted — tracking is live. Bring the hand back up slowly.";
    setCheck("chk-still", "pass", `${msg.motion} g of motion`);
    setCheck("chk-down", "pass", `${msg.off_deg}° off vertical`);
    setCheck("chk-hold", "pass", "held for 3 s");
    $("cal-result").innerHTML = `${wearingText(msg.frame, msg.wearing)}`
      + ` <span class="frame">— events are held again if you press Recalibrate (ring changed hands or was re-worn)</span>`;
    return;
  }
  $("cal-title").textContent = msg.restarted ? "Recalibrating" : "Calibrating";
  if (status === "collecting") {
    $("cal-msg").textContent = "Let the arm hang, fingers at the floor, hold still…";
    setCheck("chk-still", "wait", "reading");
    setCheck("chk-down", "wait", "reading");
    setCheck("chk-hold", "wait", "");
  } else if (status === "retry") {
    if (msg.reason === "moving") {
      $("cal-msg").textContent = `Hold still — the hand is moving (${msg.motion} g). The 3 s restarts once it is still.`;
      setCheck("chk-still", "fail", `${msg.motion} g, needs under 0.25 g`);
      setCheck("chk-down", msg.off_deg <= 25 ? "pass" : "fail", `${msg.off_deg}° off vertical`);
    } else {
      $("cal-msg").textContent = `Point the fingers straight at the floor — they are ${msg.off_deg}° off vertical. Let the wrist go limp.`;
      setCheck("chk-still", "pass", `${msg.motion} g`);
      setCheck("chk-down", "fail", `${msg.off_deg}° off vertical, needs under 26°`);
    }
    setCheck("chk-hold", "wait", "restarts when both pass");
  } else {  // hold
    $("cal-msg").textContent = `Good — keep it there, ${left.toFixed(1)} s to go.`;
    setCheck("chk-still", "pass", `${msg.motion} g`);
    setCheck("chk-down", "pass", `${msg.off_deg}° off vertical`);
    setCheck("chk-hold", "wait", `${(msg.held_s || 0).toFixed(1)} / ${msg.hold_s} s`);
  }
}

function renderCalibrationFromStatus(status) {
  // A page opened mid-session, or the state changing: show what is known.
  const card = $("cal");
  if (status.state !== "streaming") {
    card.className = "card cal idle";
    $("cal-title").textContent = "Calibration";
    $("cal-msg").textContent = "Every tracking session starts with a 3 s pose so the console learns which way round the ring is on. No event is shown until the pose is accepted.";
    ["cal-progress", "cal-checks", "cal-result", "btn-recal"].forEach((id) => { $(id).hidden = true; });
    $("events").classList.remove("held");
    calFrame = null;
    return;
  }
  if (status.calibrated && status.calibration) {
    renderCalibration({ status: "ok", held_s: 3, hold_s: 3, ...status.calibration });
  } else if (!status.calibrated) {
    renderCalibration({ status: "collecting", held_s: 0, hold_s: 3 });
  }
}

function noteEngineFrame(frame) {
  // The engine also watches for the pose on its own; if it changes the frame
  // outside a calibration, say so rather than silently tracking in a new frame.
  if (!frame || calFrame === null || frame === calFrame) return;
  calFrame = frame;
  $("cal-result").innerHTML = `frame changed mid-session to <code>${frame}</code> — a fingers-down pose was seen.`
    + ` <span class="frame">If the ring changed hands, press Recalibrate to be sure.</span>`;
}

$("btn-recal").addEventListener("click", async () => {
  try { renderCalibrationFromStatus(await api("POST", "/api/calibrate")); }
  catch (e) { alertBox(e.message); }
});

/* ---------------------------------------------------------------- boot */
(async function boot() {
  connectSocket();
  const status = await api("GET", "/api/status");
  renderState(status);
  renderCalibrationFromStatus(status);
  await Promise.all([loadTargets(), loadSettings(), loadModel()]);
})().catch((e) => alertBox(e.message));
