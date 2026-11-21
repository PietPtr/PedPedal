# Firmware and driver

All in Rust. The Pico on module 1 shows up on the computer as a USB MIDI device called
**Footswitch**. It sends MIDI when the pedals are pressed. The same MIDI port takes
configuration from the driver, so the computer needs no extra driver.

## Layout

| Directory   | Crate                 | What it is |
|-------------|-----------------------|------------|
| `core/`     | `footswitch-core`     | Shared by both sides, `no_std`: the config types, the SysEx protocol, USB-MIDI packets and the pedal state machine (debounce, momentary/latch, LEDs). Has the unit tests. |
| `firmware/` | `footswitch-firmware` | The Pico firmware. Started from [rp2040-project-template](https://github.com/rp-rs/rp2040-project-template). |
| `driver/`   | `footswitch`          | Host library to configure the device, plus the `fsctl` command-line tool. |

The repository root is a Cargo workspace with `core` and `driver`. The firmware builds for
another target (`thumbv6m-none-eabi`), so it is left out of the workspace and built from its
own directory.

```sh
cargo test                     # in the root: core unit tests + driver
cd firmware && cargo build --release
```

## Behaviour

- **Scan:** PIO0 scans the module chain every 1 ms (GP16 CLK, GP17 LATCH, GP18 LED_DATA,
  GP19 SW_DATA; see [design.md](design.md#scan-timing)). It always clocks 16 bytes. The first
  byte whose marker bit (165 input H) is 0 ends the chain, so the module count needs no setting.
  Modules can be added or removed while the device is running.
- **Switch:** the footswitch is momentary hardware (PBS24-202P, momentary type). Latching is
  done in firmware.
- **Debounce:** a change has to be read on 2 scans in a row (filters glitches on the ribbon).
  After that, further changes are held back for 20 ms (contact bounce). The first edge is not
  delayed, so latency is about 2 ms.
- **Momentary mode:** the pedal is on while the switch is held down. It sends its "on" message
  on press and its "off" message on release.
- **Latch mode:** each press toggles the pedal. It sends "on" when it turns on and "off" when
  it turns off. Releasing the switch does nothing.
- **LED:** lit in the pedal's colour while the pedal is on, off otherwise. There are 7 colours:
  red, green, yellow, blue, magenta, cyan and white. Colour `off` keeps the LED dark.
- **MIDI messages**, one per pedal:
  - **Note**: Note On (with the set velocity) when on, Note Off when off.
  - **CC**: the controller with the "on" value when on, the "off" value when off.
  - **Program change**: sent when the pedal turns on. Nothing is sent when it turns off.
  - **None**: no MIDI. The LED still works.
- **Defaults**, for a new Pico or after `fsctl reset`: every pedal is momentary and red, and
  sends CC 102 + n on channel 1 (pedal 1 = CC 102, pedal 2 = CC 103, …), 127 on and 0 off.
  CCs 102–119 are undefined in the MIDI spec, so they don't clash with what synths already
  listen to.
- **Changing a pedal while it is on:** the device first sends the old "off" message, so no
  note or CC is left hanging.
- **Unplugging a module** while its pedal is held counts as a release.
- **A switch held down at power-on** is ignored until it is released and pressed again.
- **Inverted switches:** if a switch's NO and NC pins turn out to be swapped (the pedal reads
  pressed while up), `fsctl invert on` flips every switch input.
- **Storage:** changes apply at once but live in RAM. `fsctl save` writes them to the last
  4 KiB sector of the Pico's flash (`memory.x` keeps the program out of that sector). Saving
  takes about 50 ms, and the pedals are not scanned during that time, so don't save
  mid-song.
- **Pico LED (GP25):** on while the computer has the USB device set up. It is only visible
  with the enclosure open.

## Flashing

The runner in `firmware/.cargo/config.toml` is `elf2uf2-rs -d`. It writes to the Pico's
RPI-RP2 USB drive.

1. **First time:** hold BOOTSEL on the Pico while plugging in USB.
   **Later:** run `fsctl bootloader`. The Pico reboots into the bootloader, so the enclosure
   doesn't need to be opened.
2. `cd firmware && cargo run --release`

**elf2uf2-rs 2.1.1 (the version on this machine) fails with `Unrecognized ABI`.** The current
Rust toolchain marks the ELF with OS/ABI "GNU", which only newer versions accept. 2.2.0
works. Update it with `cargo install elf2uf2-rs --force`.

With a debug probe, switch the runner to the `probe-rs` line instead. You then also get the
defmt log output.

## fsctl

Pedals are numbered from 1 (the module with the Pico), and MIDI channels 1–16.

```sh
cargo install --path driver       # or: cargo run -p footswitch --bin fsctl -- …

fsctl show                                  # firmware, connected pedals, every pedal's config
fsctl set 1 --mode latch --color green      # options not given are kept
fsctl set 2 --cc 64 --on 127 --off 0 --channel 1
fsctl set 3 --note 36 --velocity 100 --channel 10
fsctl set 4 --pc 5
fsctl set 5 --no-midi
fsctl set all --color blue
fsctl set 1 --color cyan --save             # set and save in one go
fsctl state --watch                         # live view of pedals on / held
fsctl save                                  # keep the config after power-off
fsctl reset                                 # factory defaults (then save to keep them)
fsctl invert on|off                         # for switches with swapped contacts
fsctl bootloader                            # reboot into the USB bootloader
fsctl ports                                 # list MIDI ports; --port NAME picks another
```

On Windows, only one program can have a MIDI port open at a time. Close the DAW, or turn the
port off in it, while running fsctl. Linux and macOS allow sharing.

## Library

```rust
use footswitch::{Color, Footswitch, Message, Mode};

let mut fs = Footswitch::open()?;            // first port with "Footswitch" in its name
let n = fs.info()?.connected_pedals;
fs.set_mode(0, Mode::Latch)?;                // pedal index from 0
fs.set_color(0, Color::Green)?;
fs.set_message(0, Message::Note { channel: 9, note: 36, velocity: 100 })?; // channel 0–15
fs.save()?;
```

There are also `pedal`, `pedals`, `set_pedal`, `update_pedal`, `set_all_colors`, `settings`,
`set_settings`, `states`, `reset_defaults` and `enter_bootloader`. See `driver/src/lib.rs`.

## Protocol

SysEx on the same USB MIDI port, with manufacturer ID `7D` (non-commercial) and device ID
`46 53` ("FS"):

```
request:  F0 7D 46 53 <command> <payload> F7
response: F0 7D 46 53 <command|40> <status> <payload> F7
```

The commands, payloads and status codes are in `core/src/protocol.rs`. Every request gets
exactly one response.

## USB IDs

VID:PID `16C0:05E4`. This is the free pair that VOTI shares among hobby USB MIDI devices; hosts
tell devices apart by name. The product string is "Footswitch" and the manufacturer "DIY".

## Testing status

- `cargo test` runs the unit tests in `core`: config and flash format, protocol, USB-MIDI
  packets, and the pedal logic (debounce, momentary, latch, inversion, unplugging).
- The driver and fsctl were tested over real ALSA MIDI against a simulated device: a virtual
  MIDI port that answers the protocol using the `core` crate.
- **Not yet tested on hardware:** the PIO scan, flash saving, USB enumeration and the
  bootloader reboot. Things to check at bring-up:
  - `fsctl show` lists the right number of modules.
  - Each LED lights in its colour when its pedal is pressed. A wrong colour means the LED's
    lead order differs from the footprint.
  - `fsctl save` survives a power cycle.
