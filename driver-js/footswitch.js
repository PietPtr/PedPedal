// Host driver for the USB MIDI footswitch, for the browser (Web MIDI).
//
// A port of the Rust `footswitch` crate (driver/src/lib.rs) and the parts of `footswitch-core`
// it uses (core/src/protocol.rs, core/src/config.rs). Same API, in camelCase and async.
//
// The device shows up as a USB MIDI port called "Footswitch". It sends its pedal messages on
// that port, and the same port takes configuration as SysEx. No OS driver is needed.
//
//   import { Color, Footswitch, Mode } from "./footswitch.js";
//
//   const fs = await Footswitch.open();
//   console.log(`${(await fs.info()).connectedPedals} pedals connected`);
//
//   // Pedal 0 (the module with the Pico): latching, green, sends CC 64 on channel 1.
//   await fs.setMode(0, Mode.Latch);
//   await fs.setColor(0, Color.Green);
//   await fs.setMessage(0, { kind: "cc", channel: 0, controller: 64, onValue: 127, offValue: 0 });
//   await fs.save(); // keep it after power-off
//
// Pedal indices start at 0 (the module with the Pico) and MIDI channels are 0–15 (channel 1 is
// 0). Changes apply at once; call `save()` to keep them in flash.
//
// SysEx needs permission: browsers ask the user the first time, and only on https:// or
// localhost. Web MIDI works in Chrome, Edge and Firefox, not in Safari. Outside the browser,
// pass any object with the Web MIDI `MIDIAccess` interface as `access`.
//
// On Windows a MIDI port can only be open in one program at a time, so close the DAW (or
// disable the port in it) while configuring.

// ---- constants ----

/** Substring of the USB product name that `Footswitch.open` looks for in port names. */
export const PORT_NAME = "Footswitch";

/** How long to wait for a reply, in ms. Saving to flash takes about 50 ms. */
export const DEFAULT_TIMEOUT = 1000;

/** The most pedals (modules) the firmware scans. */
export const MAX_PEDALS = 16;

export const HEADER = [0xf0, 0x7d, 0x46, 0x53];
export const SYSEX_END = 0xf7;
export const PROTOCOL_VERSION = 1;
const RESPONSE_FLAG = 0x40;

// ---- config types (core/src/config.rs) ----

/** LED colour. The value is the 74HC595 bit pattern: bit 0 red, bit 1 green, bit 2 blue. */
export const Color = Object.freeze({
  Off: 0,
  Red: 1,
  Green: 2,
  Yellow: 3,
  Blue: 4,
  Magenta: 5,
  Cyan: 6,
  White: 7,
});

/** Lower-case colour names, indexed by colour value. */
export const COLOR_NAMES = Object.freeze([
  "off", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
]);

/** How the pedal reacts to the (momentary) footswitch. */
export const Mode = Object.freeze({
  /** Active while held down: "on" message on press, "off" on release. */
  Momentary: 0,
  /** Each press toggles: "on" when it turns on, "off" when it turns off. */
  Latch: 1,
});

// The MIDI message a pedal sends is a plain object, one of:
//   { kind: "none" }                                          send nothing (the LED still works)
//   { kind: "note", channel, note, velocity }                 Note On when on, Note Off when off
//   { kind: "cc", channel, controller, onValue, offValue }    Control Change with on/off value
//   { kind: "pc", channel, program }                          Program Change when on
// Channels are 0–15, everything else 0–127, note velocity 1–127.
//
// A pedal config is { mode, color, message }. Device settings are { invertSwitches }.

const isByte7 = (v) => Number.isInteger(v) && v >= 0 && v < 128;
const isChannel = (v) => Number.isInteger(v) && v >= 0 && v < 16;

/** True if every field is in range (channel 0–15, data 0–127, note velocity 1–127). */
export function isValidMessage(m) {
  switch (m?.kind) {
    case "none":
      return true;
    case "note":
      return isChannel(m.channel) && isByte7(m.note) && isByte7(m.velocity) && m.velocity >= 1;
    case "cc":
      return isChannel(m.channel) && isByte7(m.controller) && isByte7(m.onValue) && isByte7(m.offValue);
    case "pc":
      return isChannel(m.channel) && isByte7(m.program);
    default:
      return false;
  }
}

export function isValidPedal(cfg) {
  return (
    (cfg?.mode === Mode.Momentary || cfg?.mode === Mode.Latch) &&
    Number.isInteger(cfg.color) && cfg.color >= 0 && cfg.color < 8 &&
    isValidMessage(cfg.message)
  );
}

/**
 * The factory default for pedal `index`: momentary, red, and CC 102 + index on channel 1,
 * value 127 on / 0 off.
 */
export function defaultPedal(index) {
  return {
    mode: Mode.Momentary,
    color: Color.Red,
    message: { kind: "cc", channel: 0, controller: 102 + index, onValue: 127, offValue: 0 },
  };
}

export const PEDAL_ENCODED_LEN = 7;

/**
 * Layout: [mode, color, kind, channel, a, b, c], where kind is 0 none, 1 note, 2 CC,
 * 3 program change, and a/b/c are note/velocity/0, controller/on/off or program/0/0.
 */
export function encodePedal(cfg) {
  const m = cfg.message;
  let fields;
  switch (m.kind) {
    case "note": fields = [1, m.channel, m.note, m.velocity, 0]; break;
    case "cc": fields = [2, m.channel, m.controller, m.onValue, m.offValue]; break;
    case "pc": fields = [3, m.channel, m.program, 0, 0]; break;
    default: fields = [0, 0, 0, 0, 0];
  }
  return [cfg.mode, cfg.color, ...fields].map((v) => v & 0x7f);
}

/** Decodes `encodePedal`'s output. Returns null if anything is out of range. */
export function decodePedal(bytes) {
  if (bytes.length < PEDAL_ENCODED_LEN) return null;
  const [mode, color, kind, channel, a, b, c] = bytes;
  let message;
  switch (kind) {
    case 0: message = { kind: "none" }; break;
    case 1: message = { kind: "note", channel, note: a, velocity: b }; break;
    case 2: message = { kind: "cc", channel, controller: a, onValue: b, offValue: c }; break;
    case 3: message = { kind: "pc", channel, program: a }; break;
    default: return null;
  }
  const cfg = { mode, color, message };
  return isValidPedal(cfg) ? cfg : null;
}

export function encodeSettings(s) {
  return [s.invertSwitches ? 1 : 0];
}

export function decodeSettings(bytes) {
  if (bytes[0] === 0) return { invertSwitches: false };
  if (bytes[0] === 1) return { invertSwitches: true };
  return null;
}

// ---- protocol (core/src/protocol.rs) ----
//
// Request (host → device):  F0 7D 46 53 <command> <payload…> F7
// Response (device → host): F0 7D 46 53 <command | 0x40> <status> <payload…> F7

export const Command = Object.freeze({
  GetInfo: 0x01,
  GetPedal: 0x02,
  SetPedal: 0x03,
  GetSettings: 0x04,
  SetSettings: 0x05,
  GetState: 0x06,
  Save: 0x07,
  ResetDefaults: 0x08,
  EnterBootloader: 0x09,
});

/** Result code in every response. */
export const Status = Object.freeze({
  Ok: 0,
  UnknownCommand: 1,
  /** Payload too short, too long or with out-of-range values. */
  Malformed: 2,
  /** Pedal index not below the device's maximum. */
  BadIndex: 3,
  /** Writing the flash failed or read back wrong. */
  FlashError: 4,
});

const nameOf = (table, value) =>
  Object.keys(table).find((k) => table[k] === value) ?? `0x${value.toString(16)}`;
export const commandName = (c) => nameOf(Command, c);
export const statusName = (s) => nameOf(Status, s);

// A request is { command } plus `index` (GetPedal, SetPedal), `config` (SetPedal) or
// `settings` (SetSettings).

/** The complete SysEx message for a request, F0 to F7. */
export function encodeRequest(req) {
  const out = [...HEADER, req.command];
  switch (req.command) {
    case Command.GetPedal:
      out.push(req.index & 0x7f);
      break;
    case Command.SetPedal:
      out.push(req.index & 0x7f, ...encodePedal(req.config));
      break;
    case Command.SetSettings:
      out.push(...encodeSettings(req.settings));
      break;
  }
  out.push(SYSEX_END);
  return out;
}

const u16From7bit = (b) => b[0] | (b[1] << 7) | (b[2] << 14);

/**
 * Decodes a complete SysEx response. Returns null if it isn't a well-formed response in this
 * protocol, otherwise { command, status, response }. `response` is null unless status is Ok:
 *   GetInfo:     { protocolVersion, firmwareVersion: [major, minor, patch], maxPedals, connectedPedals }
 *   GetPedal:    { index, config }
 *   GetSettings: { invertSwitches }
 *   GetState:    { connected, active, pressed }   (bit i of active/pressed is pedal i)
 *   the others:  {}
 */
export function decodeResponse(msg) {
  const n = msg.length;
  if (n < HEADER.length + 3 || msg[n - 1] !== SYSEX_END) return null;
  for (let i = 0; i < HEADER.length; i++) if (msg[i] !== HEADER[i]) return null;
  const body = Array.from(msg.slice(HEADER.length, n - 1));
  if (body.some((b) => b >= 0x80)) return null;

  const [cmd, status, ...p] = body;
  if (!(cmd & RESPONSE_FLAG)) return null;
  const command = cmd & ~RESPONSE_FLAG;
  if (!Object.values(Status).includes(status)) return null;
  if (status !== Status.Ok) return p.length === 0 ? { command, status, response: null } : null;

  let response;
  switch (command) {
    case Command.GetInfo:
      if (p.length !== 6) return null;
      response = {
        protocolVersion: p[0],
        firmwareVersion: [p[1], p[2], p[3]],
        maxPedals: p[4],
        connectedPedals: p[5],
      };
      break;
    case Command.GetPedal: {
      if (p.length !== 1 + PEDAL_ENCODED_LEN) return null;
      const config = decodePedal(p.slice(1));
      if (!config) return null;
      response = { index: p[0], config };
      break;
    }
    case Command.GetSettings:
      if (p.length !== 1) return null;
      response = decodeSettings(p);
      if (!response) return null;
      break;
    case Command.GetState:
      if (p.length !== 7) return null;
      response = { connected: p[0], active: u16From7bit(p.slice(1, 4)), pressed: u16From7bit(p.slice(4, 7)) };
      break;
    case Command.SetPedal:
    case Command.SetSettings:
    case Command.Save:
    case Command.ResetDefaults:
    case Command.EnterBootloader:
      if (p.length !== 0) return null;
      response = {};
      break;
    default:
      return null;
  }
  return { command, status, response };
}

// ---- errors ----

/**
 * Every failure is a FootswitchError. `kind` is one of: "not-found", "midi", "timeout",
 * "rejected", "unexpected-reply", "bad-index", "invalid-config". `command` and `status` are
 * set where they apply.
 */
export class FootswitchError extends Error {
  constructor(kind, message, extra = {}) {
    super(message);
    this.name = "FootswitchError";
    this.kind = kind;
    Object.assign(this, extra);
  }
}

// ---- MIDI access ----

/** Asks the browser for MIDI access with SysEx. Prompts the user the first time. */
export async function requestAccess() {
  if (typeof navigator === "undefined" || !navigator.requestMIDIAccess) {
    throw new FootswitchError("midi", "Web MIDI is not available in this browser");
  }
  try {
    return await navigator.requestMIDIAccess({ sysex: true });
  } catch (e) {
    throw new FootswitchError("midi", `MIDI access denied: ${e.message ?? e}`);
  }
}

/** Lists the MIDI input port names that contain `PORT_NAME`. */
export async function listPorts(access) {
  return (await allPortNames(access)).filter((n) => n.includes(PORT_NAME));
}

/** Lists every MIDI input port name, footswitch or not. */
export async function allPortNames(access) {
  access ??= await requestAccess();
  return [...access.inputs.values()].map((p) => p.name);
}

// ---- the driver ----

function checkIndex(index) {
  if (Number.isInteger(index) && index >= 0 && index < MAX_PEDALS) return index;
  throw new FootswitchError("bad-index", `pedal index ${index} out of range (max ${MAX_PEDALS - 1})`);
}

/** An open connection to a footswitch. */
export class Footswitch {
  /** Opens the first port whose name contains `PORT_NAME`. Options: { access, timeout }. */
  static open(options = {}) {
    return Footswitch.openMatching(PORT_NAME, options);
  }

  /**
   * Opens the first port whose name contains `pattern`. Use this to pick one of several
   * footswitches, or a port with an unexpected name.
   */
  static async openMatching(pattern, { access, timeout = DEFAULT_TIMEOUT } = {}) {
    access ??= await requestAccess();
    const input = [...access.inputs.values()].find((p) => p.name?.includes(pattern));
    const output = [...access.outputs.values()].find((p) => p.name?.includes(pattern));
    if (!input || !output) {
      throw new FootswitchError("not-found", `no MIDI port matching "${pattern}" found (is the footswitch plugged in?)`);
    }
    try {
      await Promise.all([input.open(), output.open()]);
    } catch (e) {
      throw new FootswitchError("midi", `opening the MIDI port failed: ${e.message ?? e}`);
    }
    return new Footswitch(access, input, output, timeout);
  }

  constructor(access, input, output, timeout) {
    this.access = access;
    this.input = input;
    this.output = output;
    /** Reply timeout in ms. */
    this.timeout = timeout;
    this._replies = []; // SysEx messages received and not yet consumed
    this._wake = null; // resolves the request waiting for a reply
    this._queue = Promise.resolve(); // one request at a time
    this._onMessage = (ev) => {
      if (ev.data?.[0] !== 0xf0) return;
      this._replies.push(ev.data);
      this._wake?.();
    };
    input.addEventListener("midimessage", this._onMessage);
  }

  /** The name of the MIDI output port in use. */
  get portName() {
    return this.output.name ?? "";
  }

  /** Stops listening and closes the ports. */
  async close() {
    this.input.removeEventListener("midimessage", this._onMessage);
    await Promise.allSettled([this.input.close(), this.output.close()]);
  }

  /** Firmware version, and how many pedals are connected. */
  async info() {
    return this.request({ command: Command.GetInfo });
  }

  /** The config of pedal `index`. */
  async pedal(index) {
    index = checkIndex(index);
    const r = await this.request({ command: Command.GetPedal, index });
    if (r.index !== index) throw unexpected(Command.GetPedal);
    return r.config;
  }

  /** The configs of the connected pedals, in order. */
  async pedals() {
    const n = (await this.info()).connectedPedals;
    const out = [];
    for (let i = 0; i < n; i++) out.push(await this.pedal(i));
    return out;
  }

  /**
   * Replaces pedal `index`'s config. If the pedal is on, the device first sends its old "off"
   * message and turns it off.
   */
  async setPedal(index, config) {
    index = checkIndex(index);
    if (!isValidPedal(config)) {
      throw new FootswitchError("invalid-config", `invalid pedal config: ${JSON.stringify(config)}`, { config });
    }
    await this.request({ command: Command.SetPedal, index, config });
  }

  /** Changes one pedal's mode, keeping its other settings. */
  setMode(index, mode) {
    return this.updatePedal(index, (p) => { p.mode = mode; });
  }

  /** Changes one pedal's LED colour (shown while the pedal is on). */
  setColor(index, color) {
    return this.updatePedal(index, (p) => { p.color = color; });
  }

  /** Changes the MIDI message one pedal sends. */
  setMessage(index, message) {
    return this.updatePedal(index, (p) => { p.message = message; });
  }

  /** Reads pedal `index`, applies `f` (which may change it in place) and writes it back. */
  async updatePedal(index, f) {
    const cfg = await this.pedal(index);
    f(cfg);
    await this.setPedal(index, cfg);
  }

  /** Sets the LED colour of every pedal. */
  async setAllColors(color) {
    for (let i = 0; i < MAX_PEDALS; i++) await this.setColor(i, color);
  }

  async settings() {
    return this.request({ command: Command.GetSettings });
  }

  async setSettings(settings) {
    await this.request({ command: Command.SetSettings, settings });
  }

  /** Which pedals are on and which switches are held down right now. */
  async states() {
    return this.request({ command: Command.GetState });
  }

  /** Writes the current config to flash, so it survives a power cycle. */
  async save() {
    await this.request({ command: Command.Save });
  }

  /**
   * Restores the factory defaults (every pedal momentary, red, CC 102 + index on channel 1).
   * Only in RAM: call `save()` to make it permanent.
   */
  async resetDefaults() {
    await this.request({ command: Command.ResetDefaults });
  }

  /**
   * Reboots the Pico into its USB bootloader (the RPI-RP2 drive) for a firmware update,
   * without pressing BOOTSEL. Closes the connection.
   */
  async enterBootloader() {
    try {
      await this.request({ command: Command.EnterBootloader });
    } catch (e) {
      // The reply can be lost when USB goes down; that is fine here.
      if (e.kind !== "timeout") throw e;
    } finally {
      await this.close();
    }
  }

  /**
   * Sends one request and waits for its reply; resolves to the decoded response payload.
   * Requests made while another is in flight wait their turn.
   */
  request(req) {
    const run = () => this._request(req);
    const p = this._queue.then(run, run);
    this._queue = p.catch(() => {});
    return p;
  }

  async _request(req) {
    // Drop stale replies (e.g. from an earlier request that timed out).
    this._replies.length = 0;
    try {
      this.output.send(encodeRequest(req));
    } catch (e) {
      throw new FootswitchError("midi", `sending to the device failed: ${e.message ?? e}`);
    }

    const deadline = performance.now() + this.timeout;
    for (;;) {
      while (this._replies.length) {
        const reply = decodeResponse(this._replies.shift());
        if (!reply || reply.command !== req.command) continue;
        if (reply.status !== Status.Ok) {
          throw new FootswitchError(
            "rejected",
            `the device rejected ${commandName(req.command)}: ${statusName(reply.status)}`,
            { command: req.command, status: reply.status },
          );
        }
        return reply.response;
      }
      const left = deadline - performance.now();
      if (left <= 0) {
        throw new FootswitchError("timeout", `no reply from the device to ${commandName(req.command)}`, { command: req.command });
      }
      await new Promise((resolve) => {
        const t = setTimeout(resolve, left);
        this._wake = () => { clearTimeout(t); resolve(); };
      });
      this._wake = null;
    }
  }
}

function unexpected(command) {
  return new FootswitchError("unexpected-reply", `unexpected reply to ${commandName(command)}`, { command });
}
