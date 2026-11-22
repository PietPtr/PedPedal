// The config page: a UI on top of the footswitch library (footswitch.js, from driver-js/).
// Pedals are numbered from 1 and MIDI channels 1–16 here, as on most MIDI gear; the library
// counts both from 0.

import {
  COLOR_NAMES, Footswitch, PORT_NAME, defaultPedal, isValidPedal, requestAccess,
} from "./footswitch.js";
import { Picoboot, PicobootError, isBootsel, parseUf2 } from "./picoboot.js";

const $ = (id) => document.getElementById(id);

// Screen colours for the LED colours (index = colour value).
const LED_CSS = ["#000", "#ff3b3b", "#36e07a", "#ffd23f", "#4a7dff", "#e24bff", "#3fe0ff", "#f4f4f8"];
const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const POLL_MS = 100;
// The OS, for hints that only apply to one of them.
const PLATFORM = (navigator.userAgentData?.platform || navigator.platform || "").toLowerCase();
const IS_WINDOWS = PLATFORM.startsWith("win");

let access = null; // MIDIAccess, kept so plugging the pedal in reconnects
let fs = null; // the open Footswitch
let cards = []; // one per shown pedal: { el, index, config, timer }
let connecting = false;
let dirty = false;
let pollGen = 0; // bumped to stop the polling loop
let shownCount = -1; // connected pedals, as last loaded
let latest = null; // firmware/firmware.json: the firmware shipped with this page
let bootDevice = null; // a Pico in BOOTSEL mode (USBDevice) the page may use
let flashState = "idle";
let flashing = false;

// ---- connect / disconnect ----

function showConnect(title, msg, { error = false, button = "Connect" } = {}) {
  $("connect").classList.toggle("error", error);
  $("connect-title").textContent = title;
  $("connect-msg").textContent = msg;
  $("connect-btn").textContent = button;
  $("connect-btn").disabled = false;
  syncPanels();
}

/** Shows the connect, flash and device panels that fit the current state. */
function syncPanels() {
  const inBootloader = ["waiting", "found", "busy"].includes(flashState);
  $("device").hidden = !fs;
  $("connect").hidden = !!fs || inBootloader;
  $("flash").hidden = !!fs || !latest;
}

const PLUG_IN = ["Plug in your footswitch", "Connect it over USB. It connects by itself."];
let autoFails = 0; // automatic connect attempts that failed in a row

/**
 * Connects to the footswitch. A click (`background: false`) reports every failure. Automatic
 * attempts (page load, plugging in, the retry timer) keep the neutral "plug in" message, and
 * only report a footswitch that is there but doesn't answer after a few tries in a row.
 */
async function connect({ background = false } = {}) {
  if (connecting || fs) return;
  connecting = true;
  // Only dim the button for a click, and only if connecting takes a while: background retries
  // and fast failures would make it blink. `connecting` already guards against double clicks.
  const busyTimer = background ? 0 : setTimeout(() => { $("connect-btn").disabled = true; }, 150);
  try {
    if (!access) {
      access = await requestAccess();
      access.addEventListener("statechange", onPortChange);
    }
    fs = await Footswitch.open({ access });
    await handshake();
    await loadDevice();
    autoFails = 0;
    startPolling();
  } catch (e) {
    const old = fs;
    fs = null;
    old?.close();
    autoFails = background ? autoFails + 1 : 0;
    if (e.kind === "not-found") {
      if (background) {
        // Leave messages like "Footswitch unplugged" alone; only clear an earlier error.
        if ($("connect").classList.contains("error")) showConnect(...PLUG_IN);
      } else {
        const others = [...access.inputs.values()].map((p) => p.name);
        showConnect(
          "No footswitch found",
          others.length
            ? `Is it plugged in? Other MIDI devices: ${others.join(", ")}. It connects by itself when it appears.`
            : "Is it plugged in? It connects by itself when it appears.",
          { error: true, button: "Try again" },
        );
      }
    } else if (e.kind === "timeout") {
      if (background && autoFails < 3) return; // keep whatever is shown and let the timer retry
      const hint = IS_WINDOWS ? " Close other programs that use it (like your DAW) first." : "";
      showConnect("The footswitch doesn't answer", `Unplug it and plug it back in, or reload this page.${hint}`, { error: true, button: "Try again" });
    } else if (!background) {
      showConnect("Can't use MIDI", e.message, { error: true, button: "Try again" });
    }
  } finally {
    clearTimeout(busyTimer);
    connecting = false;
  }
}

/**
 * Asks for the device info until it answers, up to three times. Right after a reload the first
 * reply can get lost: the Pico may still hold part of a reply to the old page, which garbles
 * the next SysEx message the browser receives.
 */
async function handshake() {
  const timeout = fs.timeout;
  fs.timeout = 400; // GetInfo answers at once; don't make the user wait 3 s for a lost reply
  try {
    for (let attempt = 1; ; attempt++) {
      try {
        return await fs.info();
      } catch (e) {
        if (e.kind !== "timeout" || attempt >= 3) throw e;
      }
    }
  } finally {
    fs.timeout = timeout;
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
    setTimeout(() => connect({ background: true }), 300);
  }
}

// ---- device ----

async function loadDevice() {
  const info = await fs.info();
  const settings = await fs.settings();
  $("d-port").textContent = fs.portName;
  $("d-fw").textContent = info.firmwareVersion.join(".");
  const update = latest && newerVersion(latest.version.split(".").map(Number), info.firmwareVersion);
  $("fw-update").hidden = !update;
  $("fw-update").textContent = update ? `${latest.version} available` : "";
  $("invert").checked = settings.invertSwitches;
  await loadPedals(info.connectedPedals);
  if (!flashing) renderFlash("idle");
  syncPanels();
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

// The fields for each message kind: [message field, label, min]. Notes are typed as a name
// and octave ("C#2"); the rest are plain numbers up to 127.
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
    const input = document.createElement("input");
    if (key === "note") {
      Object.assign(input, { type: "text", autocomplete: "off", spellcheck: false, value: noteName(message[key]) });
    } else {
      Object.assign(input, { type: "number", inputMode: "numeric", min, max: 127, step: 1, value: message[key] });
    }
    input.dataset.key = key;
    input.addEventListener("input", () => {
      const ok = parseField(input) !== null;
      input.setAttribute("aria-invalid", String(!ok));
      clearTimeout(card.timer);
      if (ok) card.timer = setTimeout(() => apply(card), 250);
      showError(card, ok ? null : key === "note" ? "Type a note like C#2 or Eb3 (C-1 to G9)." : `Values go from ${min} to 127.`);
    });
    input.addEventListener("blur", () => {
      if (parseField(input) === null) {
        const v = card.config.message[key] ?? min;
        input.value = key === "note" ? noteName(v) : v;
        input.setAttribute("aria-invalid", "false");
        showError(card, null);
      } else if (key === "note") {
        input.value = noteName(parseField(input)); // tidy "eb3" into "D#3"
      }
    });
    f.append(Object.assign(document.createElement("span"), { textContent: label }), input);
    box.append(f);
  }
  showError(card, null);
}

/** The value of a field, or null when it isn't valid. */
function parseField(input) {
  if (input.dataset.key === "note") return parseNote(input.value);
  const v = Number(input.value);
  return input.value !== "" && Number.isInteger(v) && v >= Number(input.min) && v <= 127 ? v : null;
}

/** MIDI note number to a name like "C#2" (note 60 is C4). */
function noteName(n) {
  return `${NOTE_NAMES[n % 12]}${Math.floor(n / 12) - 1}`;
}

/** Parses "C#2", "c♯2", "Db-1", "E4" into a MIDI note number, or null. */
function parseNote(text) {
  const m = /^\s*([a-g])\s*(#|♯|b|♭)?\s*(-?\d+)\s*$/i.exec(text);
  if (!m) return null;
  const base = { c: 0, d: 2, e: 4, f: 5, g: 7, a: 9, b: 11 }[m[1].toLowerCase()];
  const shift = !m[2] ? 0 : m[2] === "#" || m[2] === "♯" ? 1 : -1;
  const n = base + shift + (Number(m[3]) + 1) * 12;
  return n >= 0 && n <= 127 ? n : null;
}

function showError(card, text) {
  card.el.querySelector(".m-desc").textContent = text ?? "";
}

/** Reads a card's controls into a pedal config. */
function readCard(card) {
  const el = card.el;
  const kind = el.querySelector(".m-kind").value;
  const message = { kind };
  if (kind !== "none") message.channel = Number(el.querySelector(".m-ch").value);
  for (const input of el.querySelectorAll(".m-fields input")) message[input.dataset.key] = parseField(input);
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

$("boot-btn").addEventListener("click", startUpdate);
$("fw-update").addEventListener("click", startUpdate);

window.addEventListener("beforeunload", (e) => {
  if (dirty || flashing) e.preventDefault();
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
  if (access && !fs && !connecting && !document.hidden) connect({ background: true });
}, 2000);

// ---- firmware update ----
//
// A Pico plugged in with BOOTSEL held (or sent to its bootloader with "Update firmware") shows
// up over WebUSB. The page then offers to flash the firmware in firmware/, which
// firmware/release.sh puts there. The first time, the browser has to be told which device
// to use (Find Pico); after that it sees the Pico come and go by itself.

const FW_DIR = "firmware/";

async function loadLatest() {
  try {
    const r = await fetch(`${FW_DIR}firmware.json`, { cache: "no-cache" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    latest = await r.json();
    $("flash-dl").href = `${FW_DIR}${latest.file}`;
    $("flash-dl").download = `pedpedal-firmware-${latest.version}.uf2`;
    $("boot-text").textContent = navigator.usb
      ? `Restarts the Pico in its bootloader, then this page flashes firmware ${latest.version} (the latest) onto it. Saved settings are kept.`
      : `Restarts the Pico in its bootloader. Then copy firmware ${latest.version} (download it below) onto the RPI-RP2 drive that appears.`;
  } catch {
    latest = null;
  }
}

function newerVersion(a, b) {
  for (let i = 0; i < 3; i++) if ((a[i] ?? 0) !== (b[i] ?? 0)) return (a[i] ?? 0) > (b[i] ?? 0);
  return false;
}

function renderFlash(state, detail = "") {
  flashState = state;
  const v = latest?.version ?? "";
  const panel = $("flash");
  panel.className = `panel flash ${{ waiting: "found", found: "found", busy: "found", error: "error", done: "done" }[state] ?? ""}`;
  const manual = `Or <a href="${$("flash-dl").href}" download="${$("flash-dl").download}">download the .uf2 file</a> and copy it onto the RPI-RP2 drive by hand.`;
  let title = "Update the firmware", msg = "", hint = manual;
  let buttons = [];
  switch (state) {
    case "idle":
      hint = "";
      buttons = navigator.usb ? ["flash-find", "flash-dl", "flash-help"] : ["flash-dl", "flash-help"];
      break;
    case "waiting":
      title = "Restarting in the bootloader";
      msg = detail || "Waiting for the Pico…";
      buttons = detail ? ["flash-find", "flash-cancel"] : [];
      break;
    case "found":
      title = "Pico in bootloader mode";
      msg = `Flash firmware ${v} onto it? Saved pedal settings are kept.`;
      buttons = ["flash-btn"];
      $("flash-btn").textContent = `Flash firmware ${v}`;
      break;
    case "busy":
      title = `Flashing firmware ${v}`;
      msg = detail;
      hint = "Keep the Pico plugged in and this page open.";
      break;
    case "done":
      title = `Firmware ${v} flashed`;
      msg = access
        ? "The Pico restarted as a footswitch. It connects by itself in a moment."
        : "The Pico restarted as a footswitch. Press Connect above to configure it.";
      hint = "";
      break;
    case "error":
      title = "Flashing didn't work";
      msg = detail;
      buttons = [bootDevice ? "flash-btn" : "flash-find"];
      $("flash-btn").textContent = "Try again";
      break;
  }
  $("flash-title").textContent = title;
  $("flash-msg").textContent = msg;
  $("flash-hint").innerHTML = hint;
  for (const id of ["flash-btn", "flash-find", "flash-cancel", "flash-dl", "flash-help"]) {
    $(id).hidden = !buttons.includes(id);
    $(id).classList.toggle("primary", buttons[0] === id && state !== "idle" || id === "flash-dl" && !navigator.usb);
  }
  $("flash-progress").hidden = state !== "busy";
  syncPanels();
}

function setProgress(fraction) {
  $("flash-progress").style.setProperty("--p", fraction);
}

function onBootDevice(device) {
  bootDevice = device;
  if (flashing || !latest) return;
  renderFlash("found");
  $("flash").scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function findPico() {
  try {
    const d = await Picoboot.request();
    if (d) onBootDevice(d);
  } catch (e) {
    renderFlash("error", e.message);
  }
}

async function flashFirmware() {
  if (flashing || !bootDevice || !latest) return;
  flashing = true;
  renderFlash("busy", "Downloading the firmware…");
  setProgress(0);
  const pb = new Picoboot(bootDevice);
  try {
    const r = await fetch(`${FW_DIR}${latest.file}`, { cache: "no-cache" });
    if (!r.ok) throw new Error(`Couldn't download the firmware (HTTP ${r.status}).`);
    const sectors = parseUf2(await r.arrayBuffer());
    await pb.open();
    await pb.flash(sectors, (phase, f) => {
      setProgress(phase === "write" ? 0.8 * f : phase === "verify" ? 0.8 + 0.2 * f : 1);
      $("flash-msg").textContent = {
        write: `Writing… ${Math.round(100 * f)}%`, verify: "Checking…", reboot: "Restarting…",
      }[phase];
    });
    bootDevice = null;
    flashing = false;
    renderFlash("done");
  } catch (e) {
    await pb.close();
    flashing = false;
    renderFlash("error", flashErrorText(e));
  }
}

function flashErrorText(e) {
  if (e instanceof PicobootError && e.kind === "access") {
    if (IS_WINDOWS) {
      return "Windows has no driver for the Pico's flashing interface, so the browser can't use it. Copy the .uf2 file onto the RPI-RP2 drive instead (download below).";
    }
    if (PLATFORM.includes("linux")) {
      return "Linux only lets the browser open the Pico with a udev rule (see the firmware docs on GitHub). Or copy the .uf2 file onto the RPI-RP2 drive (download below).";
    }
    return `Couldn't open the Pico (${e.message}). Close other programs that use it, like picotool, and try again.`;
  }
  if (e instanceof PicobootError && e.kind === "verify") {
    return `${e.message} Try again. If it keeps failing, copy the .uf2 file onto the RPI-RP2 drive (download below).`;
  }
  return e.message;
}

let waitTimer = 0;
async function startUpdate() {
  if (!fs) return;
  const v = latest ? `firmware ${latest.version}` : "new firmware";
  if (!confirm(`Restart the footswitch in its bootloader to flash ${v}? Saved settings are kept; unsaved changes are lost.`)) return;
  const dev = fs;
  pollGen++;
  fs = null;
  await dev.enterBootloader().catch(() => {});
  if (latest && navigator.usb) {
    renderFlash("waiting");
    // If the page may already use this Pico, it shows up by itself within a second or two.
    clearTimeout(waitTimer);
    waitTimer = setTimeout(() => {
      if (flashState === "waiting") {
        renderFlash("waiting", "Press Find Pico and choose “RP2 Boot” in the list. The browser only asks this the first time.");
      }
    }, 2500);
    disconnect("Bootloader mode", "The footswitch is in its bootloader.");
  } else {
    disconnect("Bootloader mode", "Copy the firmware .uf2 file onto the RPI-RP2 drive. The footswitch restarts and reconnects by itself.");
  }
}

$("flash-btn").addEventListener("click", flashFirmware);
$("flash-find").addEventListener("click", findPico);
$("flash-help").addEventListener("click", () => {
  for (const id of ["help-usb", "help-usb2"]) $(id).hidden = !navigator.usb;
  $("help-nousb").hidden = !!navigator.usb;
  $("flash-help-dlg").showModal();
});
// A click on the backdrop (outside the dialog box) closes it.
$("flash-help-dlg").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) e.currentTarget.close();
});
$("flash-cancel").addEventListener("click", () => renderFlash("idle"));

if (navigator.usb) {
  navigator.usb.addEventListener("connect", (e) => {
    if (isBootsel(e.device)) onBootDevice(e.device);
  });
  navigator.usb.addEventListener("disconnect", (e) => {
    if (e.device !== bootDevice) return;
    bootDevice = null;
    if (flashState === "found") renderFlash("idle");
  });
}

// ---- start ----

await loadLatest();
if (latest) {
  renderFlash("idle");
  const d = await Picoboot.find().catch(() => null);
  if (d) onBootDevice(d);
}
syncPanels();

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
    .then((p) => { if (p.state === "granted") connect({ background: true }); })
    .catch(() => {});
}
