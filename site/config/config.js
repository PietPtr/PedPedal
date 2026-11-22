// The config page: a UI on top of the footswitch library (footswitch.js, from driver-js/).
// Pedals are numbered from 1 and MIDI channels 1–16 here, as on most MIDI gear; the library
// counts both from 0.

import {
  COLOR_NAMES, Footswitch, PORT_NAME, defaultPedal, isValidPedal, requestAccess,
} from "./footswitch.js";

const $ = (id) => document.getElementById(id);

// Screen colours for the LED colours (index = colour value).
const LED_CSS = ["#000", "#ff3b3b", "#36e07a", "#ffd23f", "#4a7dff", "#e24bff", "#3fe0ff", "#f4f4f8"];
const NOTE_NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];
const POLL_MS = 100;

let access = null; // MIDIAccess, kept so plugging the pedal in reconnects
let fs = null; // the open Footswitch
let cards = []; // one per shown pedal: { el, index, config, timer }
let connecting = false;
let dirty = false;
let pollGen = 0; // bumped to stop the polling loop
let shownCount = -1; // connected pedals, as last loaded

// ---- connect / disconnect ----

function showConnect(title, msg, { error = false, button = "Connect" } = {}) {
  $("device").hidden = true;
  $("connect").hidden = false;
  $("connect").classList.toggle("error", error);
  $("connect-title").textContent = title;
  $("connect-msg").textContent = msg;
  $("connect-btn").textContent = button;
  $("connect-btn").disabled = false;
}

async function connect() {
  if (connecting || fs) return;
  connecting = true;
  $("connect-btn").disabled = true;
  try {
    if (!access) {
      access = await requestAccess();
      access.addEventListener("statechange", onPortChange);
    }
    fs = await Footswitch.open({ access });
    await loadDevice();
    startPolling();
  } catch (e) {
    fs = null;
    if (e.kind === "not-found") {
      const others = [...access.inputs.values()].map((p) => p.name);
      showConnect(
        "No footswitch found",
        others.length
          ? `Is it plugged in? Other MIDI devices: ${others.join(", ")}. It connects by itself when it appears.`
          : "Is it plugged in? It connects by itself when it appears.",
        { error: true, button: "Try again" },
      );
    } else if (e.kind === "timeout") {
      showConnect("The footswitch doesn't answer", "Unplug it and plug it back in, or reload this page. On Windows, close other programs that use it (like your DAW) first.", { error: true, button: "Try again" });
    } else {
      showConnect("Can't use MIDI", e.message, { error: true, button: "Try again" });
    }
  } finally {
    connecting = false;
  }
}

function disconnect(title, msg) {
  pollGen++;
  const old = fs;
  fs = null;
  old?.close();
  cards.forEach((c) => clearTimeout(c.timer));
  cards = [];
  $("pedals").replaceChildren();
  setDirty(false, false);
  showConnect(title, msg);
}

function onPortChange(e) {
  if (!e.port.name?.includes(PORT_NAME)) return;
  if (e.port.state === "disconnected" && fs) {
    disconnect("Footswitch unplugged", "Plug it back in and it connects by itself. Changes you didn't save are gone.");
  } else if (e.port.state === "connected" && !fs) {
    // Both the input and output port appear; give the second one a moment.
    setTimeout(connect, 300);
  }
}

// ---- device ----

async function loadDevice() {
  const info = await fs.info();
  const settings = await fs.settings();
  $("d-port").textContent = fs.portName;
  $("d-fw").textContent = info.firmwareVersion.join(".");
  $("invert").checked = settings.invertSwitches;
  await loadPedals(info.connectedPedals);
  $("connect").hidden = true;
  $("device").hidden = false;
  setDirty(false, false);
}

async function loadPedals(count) {
  shownCount = count;
  $("d-count").textContent = `${count} connected`;
  $("no-modules").hidden = count > 0;
  // Show at least one pedal, so the settings are visible with no modules detected.
  const n = Math.max(count, 1);
  const configs = [];
  for (let i = 0; i < n; i++) configs.push(await fs.pedal(i));
  cards.forEach((c) => clearTimeout(c.timer));
  cards = configs.map((cfg, i) => makeCard(i, cfg));
  $("pedals").replaceChildren(...cards.map((c) => c.el));
}

function setDirty(d, showSaved = !d) {
  dirty = d;
  $("dirty").hidden = !d;
  $("saved").hidden = d || !showSaved;
}

// ---- pedal cards ----

function makeCard(index, config) {
  const el = $("pedal-tpl").content.firstElementChild.cloneNode(true);
  const card = { el, index, config, timer: 0 };
  const name = `p${index}`;
  el.querySelector(".p-num").textContent = index + 1;

  for (const r of el.querySelectorAll(".seg input")) {
    r.name = `${name}-mode`;
    r.checked = Number(r.value) === config.mode;
    r.addEventListener("change", () => apply(card));
  }

  const row = el.querySelector(".swatch-row");
  COLOR_NAMES.forEach((cname, value) => {
    const label = document.createElement("label");
    label.className = `swatch${value === 0 ? " off" : ""}`;
    label.title = cname[0].toUpperCase() + cname.slice(1);
    label.style.setProperty("--c", LED_CSS[value]);
    const input = Object.assign(document.createElement("input"), {
      type: "radio", name: `${name}-color`, value, checked: value === config.color,
    });
    input.setAttribute("aria-label", label.title);
    input.addEventListener("change", () => apply(card));
    label.append(input, document.createElement("span"));
    row.append(label);
  });

  const ch = el.querySelector(".m-ch");
  for (let c = 1; c <= 16; c++) ch.add(new Option(c, c - 1));
  const kind = el.querySelector(".m-kind");
  kind.value = config.message.kind;
  ch.value = config.message.channel ?? 0;
  kind.addEventListener("change", () => {
    renderFields(card, defaultsFor(card, kind.value));
    apply(card);
  });
  ch.addEventListener("change", () => apply(card));

  renderFields(card, config.message);
  updateLed(card, false, false);
  return card;
}

/** A sensible message of a new kind, keeping the channel and any values that carry over. */
function defaultsFor(card, kind) {
  const old = card.config.message;
  const channel = old.channel ?? 0;
  switch (kind) {
    case "note": return { kind, channel, note: 36 + card.index, velocity: old.velocity ?? 127 };
    case "cc": return { kind, channel, ...ccOf(defaultPedal(card.index).message), ...(old.kind === "cc" ? ccOf(old) : {}) };
    case "pc": return { kind, channel, program: card.index };
    default: return { kind: "none" };
  }
}
const ccOf = (m) => ({ controller: m.controller, onValue: m.onValue, offValue: m.offValue });

// The number fields for each message kind: [message field, label, min].
const FIELDS = {
  cc: [["controller", "Controller", 0], ["onValue", "On value", 0], ["offValue", "Off value", 0]],
  note: [["note", "Note", 0], ["velocity", "Velocity", 1]],
  pc: [["program", "Program", 0]],
  none: [],
};

function renderFields(card, message) {
  const box = card.el.querySelector(".m-fields");
  box.replaceChildren();
  card.el.querySelector(".m-ch").closest(".field").hidden = message.kind === "none";
  for (const [key, label, min] of FIELDS[message.kind]) {
    const f = document.createElement("label");
    f.className = "field";
    const input = Object.assign(document.createElement("input"), {
      type: "number", inputMode: "numeric", min, max: 127, step: 1, value: message[key],
    });
    input.dataset.key = key;
    input.addEventListener("input", () => {
      const ok = validNumber(input);
      input.setAttribute("aria-invalid", String(!ok));
      clearTimeout(card.timer);
      if (ok) card.timer = setTimeout(() => apply(card), 250);
      else describe(card, null);
    });
    input.addEventListener("blur", () => {
      if (!validNumber(input)) {
        input.value = card.config.message[key] ?? min;
        input.setAttribute("aria-invalid", "false");
        describe(card, card.config.message);
      }
    });
    f.append(Object.assign(document.createElement("span"), { textContent: label }), input);
    box.append(f);
  }
  describe(card, message);
}

function validNumber(input) {
  const v = Number(input.value);
  return input.value !== "" && Number.isInteger(v) && v >= Number(input.min) && v <= 127;
}

function noteName(n) {
  return `${NOTE_NAMES[n % 12]}${Math.floor(n / 12) - 1}`;
}

function describe(card, m) {
  const p = card.el.querySelector(".m-desc");
  if (!m) { p.textContent = "Values go from 0 to 127."; return; }
  const ch = `channel ${(m.channel ?? 0) + 1}`;
  p.textContent = {
    cc: () => `CC ${m.controller}: ${m.onValue} when on, ${m.offValue} when off, ${ch}.`,
    note: () => `${noteName(m.note)} (note ${m.note}), velocity ${m.velocity}, ${ch}. Note off when the pedal turns off.`,
    pc: () => `Program ${m.program} when the pedal turns on, ${ch}.`,
    none: () => "Sends no MIDI. The LED still lights.",
  }[m.kind]();
}

/** Reads a card's controls into a pedal config. */
function readCard(card) {
  const el = card.el;
  const kind = el.querySelector(".m-kind").value;
  const message = { kind };
  if (kind !== "none") message.channel = Number(el.querySelector(".m-ch").value);
  for (const input of el.querySelectorAll(".m-fields input")) message[input.dataset.key] = Number(input.value);
  return {
    mode: Number(el.querySelector(".seg input:checked").value),
    color: Number(el.querySelector(".swatch input:checked").value),
    message,
  };
}

async function apply(card) {
  clearTimeout(card.timer);
  if (!fs) return;
  const cfg = readCard(card);
  if (!isValidPedal(cfg) || JSON.stringify(cfg) === JSON.stringify(card.config)) return;
  try {
    await fs.setPedal(card.index, cfg);
    card.config = cfg;
    describe(card, cfg.message);
    setDirty(true);
  } catch (e) {
    toast(`Pedal ${card.index + 1}: ${e.message}`, true);
  }
}

function updateLed(card, on, pressed) {
  const led = card.el.querySelector(".led");
  led.style.setProperty("--led", LED_CSS[card.config.color]);
  led.classList.toggle("on", on && card.config.color !== 0);
  led.classList.toggle("pressed", pressed);
}

// ---- live state ----

async function startPolling() {
  const gen = ++pollGen;
  let failures = 0;
  while (gen === pollGen && fs) {
    try {
      const s = await fs.states();
      failures = 0;
      if (gen !== pollGen) return;
      // Modules plugged in or out: reload the cards.
      if (s.connected !== shownCount) {
        await loadPedals(s.connected);
      }
      for (const c of cards) updateLed(c, (s.active >> c.index) & 1, (s.pressed >> c.index) & 1);
    } catch (e) {
      if (gen !== pollGen) return;
      if (++failures >= 3) {
        disconnect("Lost the footswitch", `It stopped answering (${e.message}). Plug it back in and it connects by itself.`);
        return;
      }
    }
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
}

// ---- buttons ----

async function run(btn, fn) {
  btn.disabled = true;
  try {
    await fn();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

$("connect-btn").addEventListener("click", connect);

$("save-btn").addEventListener("click", (e) => run(e.currentTarget, async () => {
  await fs.save();
  setDirty(false);
  toast("Saved. The pedal keeps these settings after unplugging.");
}));

$("invert").addEventListener("change", async (e) => {
  try {
    await fs.setSettings({ invertSwitches: e.target.checked });
    setDirty(true);
  } catch (err) {
    e.target.checked = !e.target.checked;
    toast(err.message, true);
  }
});

$("reset-btn").addEventListener("click", (e) => {
  if (!confirm("Reset every pedal to the factory defaults? Nothing is lost until you save.")) return;
  run(e.currentTarget, async () => {
    await fs.resetDefaults();
    await loadDevice();
    setDirty(true);
    toast("Defaults restored. Save to keep them.");
  });
});

$("boot-btn").addEventListener("click", async () => {
  if (!confirm("Reboot the footswitch into its bootloader for a firmware update? Unsaved changes are lost.")) return;
  const dev = fs;
  pollGen++;
  fs = null;
  await dev.enterBootloader().catch(() => {});
  disconnect("Bootloader mode", "Copy the firmware .uf2 file onto the RPI-RP2 drive. The footswitch restarts and reconnects by itself.");
});

window.addEventListener("beforeunload", (e) => {
  if (dirty) e.preventDefault();
});

let toastTimer = 0;
function toast(msg, error = false) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.toggle("error", error);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, error ? 6000 : 3500);
}

// Web MIDI doesn't report plugging in everywhere (statechange), so once MIDI is allowed, keep
// trying to connect in the background.
setInterval(() => {
  if (access && !fs && !connecting && !document.hidden) connect();
}, 2000);

// ---- start ----

if (!navigator.requestMIDIAccess) {
  showConnect(
    "This browser has no Web MIDI",
    "Open this page in Chrome, Edge or Firefox on a computer. Safari and iOS browsers don't support it.",
    { error: true },
  );
  $("connect-btn").hidden = true;
} else if (!window.isSecureContext) {
  showConnect("Needs a secure page", "Web MIDI only works over https:// or on localhost.", { error: true });
  $("connect-btn").hidden = true;
} else {
  // If MIDI was allowed before, connect without asking.
  navigator.permissions?.query({ name: "midi", sysex: true })
    .then((p) => { if (p.state === "granted") connect(); })
    .catch(() => {});
}
