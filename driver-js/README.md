# footswitch (JavaScript)

Configure the PedPedal USB MIDI footswitch from the browser over Web MIDI: each pedal's MIDI
message, momentary/latch mode and LED colour. A straight port of the Rust `footswitch` crate in
`driver/`; see [docs/firmware.md](../docs/firmware.md) for the protocol. The config page in
`site/config/` is built on it.

One ES module with no dependencies: `footswitch.js`.

```js
import { Color, Footswitch, Mode } from "./footswitch.js";

const fs = await Footswitch.open();          // asks for MIDI SysEx permission
console.log(await fs.info());                // firmware version, connected pedals
await fs.setMode(0, Mode.Latch);             // pedal index from 0
await fs.setColor(0, Color.Green);
await fs.setMessage(0, { kind: "note", channel: 9, note: 36, velocity: 100 });  // channel 0–15
await fs.setMessage(1, { kind: "cc", channel: 0, controller: 64, onValue: 127, offValue: 0 });
await fs.save();                             // keep it after power-off
```

Messages are `{ kind: "none" }`, `{ kind: "note", channel, note, velocity }`,
`{ kind: "cc", channel, controller, onValue, offValue }` or `{ kind: "pc", channel, program }`.

Also: `pedal`, `pedals`, `setPedal`, `updatePedal`, `setAllColors`, `settings`, `setSettings`,
`states`, `resetDefaults`, `enterBootloader`, `close`, `listPorts`, `allPortNames`. Every
method returns a promise; requests are sent one at a time. Errors are `FootswitchError` with a
`kind` (`"not-found"`, `"timeout"`, `"rejected"`, …).

Web MIDI with SysEx works in Chrome, Edge and Firefox, on https:// or localhost. Outside the
browser, pass any object with the Web MIDI `MIDIAccess` interface:
`Footswitch.open({ access })`.

Tests: `node --test`.
