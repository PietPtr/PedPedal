// Protocol tests. The byte vectors come from the Rust `footswitch-core` encoder, so these check
// that the port produces and reads exactly the same bytes. Run with `node --test`.
import assert from "node:assert/strict";
import test from "node:test";
import {
  Color, Command, Mode, Status, decodePedal, decodeResponse, defaultPedal, encodePedal,
  encodeRequest, isValidPedal,
} from "./footswitch.js";

const hex = (s) => s.split(" ").map((x) => parseInt(x, 16));

test("requests encode like the Rust core", () => {
  const cases = [
    [{ command: Command.GetInfo }, "F0 7D 46 53 01 F7"],
    [{ command: Command.GetPedal, index: 7 }, "F0 7D 46 53 02 07 F7"],
    [
      { command: Command.SetPedal, index: 15, config: { mode: Mode.Latch, color: Color.Magenta, message: { kind: "note", channel: 9, note: 38, velocity: 127 } } },
      "F0 7D 46 53 03 0F 01 05 01 09 26 7F 00 F7",
    ],
    [{ command: Command.SetPedal, index: 2, config: defaultPedal(2) }, "F0 7D 46 53 03 02 00 01 02 00 68 7F 00 F7"],
    [
      { command: Command.SetPedal, index: 0, config: { mode: Mode.Momentary, color: Color.Off, message: { kind: "pc", channel: 15, program: 127 } } },
      "F0 7D 46 53 03 00 00 00 03 0F 7F 00 00 F7",
    ],
    [
      { command: Command.SetPedal, index: 1, config: { mode: Mode.Latch, color: Color.White, message: { kind: "none" } } },
      "F0 7D 46 53 03 01 01 07 00 00 00 00 00 F7",
    ],
    [{ command: Command.SetSettings, settings: { invertSwitches: true } }, "F0 7D 46 53 05 01 F7"],
    [{ command: Command.GetState }, "F0 7D 46 53 06 F7"],
    [{ command: Command.Save }, "F0 7D 46 53 07 F7"],
    [{ command: Command.ResetDefaults }, "F0 7D 46 53 08 F7"],
    [{ command: Command.EnterBootloader }, "F0 7D 46 53 09 F7"],
  ];
  for (const [req, bytes] of cases) assert.deepEqual(encodeRequest(req), hex(bytes));
});

test("responses decode like the Rust core", () => {
  const ok = Status.Ok;
  assert.deepEqual(decodeResponse(hex("F0 7D 46 53 41 00 01 00 01 02 10 04 F7")), {
    command: Command.GetInfo, status: ok,
    response: { protocolVersion: 1, firmwareVersion: [0, 1, 2], maxPedals: 16, connectedPedals: 4 },
  });
  assert.deepEqual(decodeResponse(hex("F0 7D 46 53 42 00 02 00 01 02 00 68 7F 00 F7")), {
    command: Command.GetPedal, status: ok, response: { index: 2, config: defaultPedal(2) },
  });
  assert.deepEqual(decodeResponse(hex("F0 7D 46 53 44 00 01 F7")), {
    command: Command.GetSettings, status: ok, response: { invertSwitches: true },
  });
  assert.deepEqual(decodeResponse(hex("F0 7D 46 53 46 00 10 43 4B 02 7F 7F 03 F7")), {
    command: Command.GetState, status: ok, response: { connected: 16, active: 0xa5c3, pressed: 0xffff },
  });
  assert.deepEqual(decodeResponse(hex("F0 7D 46 53 47 00 F7")), { command: Command.Save, status: ok, response: {} });
  assert.deepEqual(decodeResponse(hex("F0 7D 46 53 43 03 F7")), { command: Command.SetPedal, status: Status.BadIndex, response: null });
  // Uint8Array input, as Web MIDI delivers it.
  assert.equal(decodeResponse(new Uint8Array(hex("F0 7D 46 53 47 00 F7"))).command, Command.Save);
});

test("not ours or malformed", () => {
  assert.equal(decodeResponse(hex("F0 41 10 F7")), null); // other manufacturer
  assert.equal(decodeResponse(hex("F0 7D 46 53 01 F7")), null); // a request
  assert.equal(decodeResponse(hex("F0 7D 46 53 41 00 01 F7")), null); // short payload
  assert.equal(decodeResponse(hex("F0 7D 46 53 43 03 01 F7")), null); // error with payload
});

test("pedal decode rejects bad values", () => {
  assert.equal(decodePedal([2, 1, 2, 0, 1, 2, 3]), null); // mode
  assert.equal(decodePedal([0, 8, 2, 0, 1, 2, 3]), null); // colour
  assert.equal(decodePedal([0, 1, 4, 0, 1, 2, 3]), null); // kind
  assert.equal(decodePedal([0, 1, 2, 16, 1, 2, 3]), null); // channel
  assert.equal(decodePedal([0, 1, 1, 0, 60, 0, 0]), null); // velocity 0
  assert.equal(decodePedal([0, 1, 2, 0, 1, 2]), null); // short
  const cfg = { mode: Mode.Latch, color: Color.Cyan, message: { kind: "note", channel: 9, note: 36, velocity: 100 } };
  assert.deepEqual(decodePedal(encodePedal(cfg)), cfg);
  assert.ok(!isValidPedal({ ...cfg, message: { kind: "cc", channel: 0, controller: 128, onValue: 0, offValue: 0 } }));
});
