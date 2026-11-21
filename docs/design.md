# Footswitch board design

A modular USB MIDI footswitch controller. Every module is the same PCB, and each carries one
footswitch and one RGB LED. Modules are chained with short ribbon cables. Only the
first module has a Raspberry Pi Pico (RP2040) fitted. The Pico's USB port is the MIDI interface.
Firmware and host software are written in Rust.

All boards sit in one enclosure. Everything is through-hole and hand-soldered.

## Files

- `pcb/footswitch.kicad_pro`, `pcb/footswitch.kicad_sch`, `pcb/footswitch.kicad_pcb`: the
  KiCad project, the schematic (one A3 sheet) and the board.
- `pcb/footswitch.kicad_dru`: a custom design rule. GND pads that also have a track need only
  one thermal spoke to the ground pour.
- `pcb/footswitches.pretty/PBS24-202P.kicad_mod`: footprint for the footswitch. It isn't in
  the KiCad library. The project's `fp-lib-table` registers it as `footswitches`.
- `mech/plates.py`: generates the laser-cut front and back plate DXFs in `mech/out/`. Run it
  with `uv run` (the repository's `pyproject.toml` holds the Python dependencies).
- `pcb/scripts/`: the scripts that generated the schematic and the board and ran the
  autorouter. They rebuild the files from scratch, so they overwrite any edits made in KiCad.
- `firmware/`, `driver/`, `core/`: the Pico firmware, the host driver library with its
  `fsctl` command-line tool, and the code they share. See [firmware.md](firmware.md).

In the schematic, the 165's inputs are named D0–D7 (KiCad's symbol) rather than A–H:
D7 = H, D6 = G, D5…D0 = F…A. The Pico is U3.

ERC passes with no errors or warnings. DRC (with the schematic-parity check) finds no
unconnected pads. The only remaining item is a harmless warning: KiCad clips the LED
footprint's silkscreen circle where it crosses a pad.

## Overview

```
                    ribbon                     ribbon                USB (MIDI)
 ┌────────────────┐  ◄──    ┌────────────────┐  ◄──    ┌────────────────┐  │
 │ Module 3       │ IN  OUT │ Module 2       │ IN  OUT │ Module 1       ├──┘
 │ no Pico        │         │ no Pico        │         │ Pico fitted    │
 │ 165 + 595      │         │ 165 + 595      │         │ 165 + 595      │
 │ switch + RGB   │         │ switch + RGB   │         │ switch + RGB   │
 └────────────────┘         └────────────────┘         └────────────────┘
```

Module 1 carries the Pico and sits at the right-hand end. The Pico's USB port points out of
the right edge. The chain extends to the left: each module's OUT connector goes to the next
module's IN connector. Both connectors sit side by side in the top-left corner, OUT left of
IN, so a cable runs about 88 mm along the top edge to the next module.

Each module has two shift registers, both powered from **3V3**:

- **74HC165**, parallel in, serial out. It reads the footswitch and a board-present bit.
  Its other 6 inputs are unused and tied to 3V3. The 165s form a chain whose data flows back toward the Pico.
- **74HC595**, serial in, parallel out. It drives the red, green and blue LED channels
  through three NPN transistors. Its other 5 outputs are unused. The 595s form a chain whose data
  flows away from the Pico.

Both chains share one clock line and one latch line. A full scan is: pulse LATCH, then clock
8 × N bits, where N is the number of modules. The Pico's PIO does the scan.

### Why these supply voltages

- All logic runs at **3.3 V**, the same as the RP2040. CLK, LATCH and the data lines are
  3.3 V signals on every module, so there are no level shifters. The 165's serial output
  reaches an RP2040 pin, and the RP2040 is not 5 V tolerant.
- The green and blue LED channels need about 3.0–3.2 V forward voltage, which is too much for
  a 3.3 V supply. The LED therefore runs from **5V** (the Pico's VBUS pin). The 595 switches
  each channel through an NPN transistor (2N2222A). The 5 V never reaches a logic pin.
- An earlier version used a 74HCT595 at 5 V, which accepts 3.3 V inputs. That part is hard to
  source, so it was replaced by the 74HC595 at 3.3 V with transistor drivers.

## Chain connector

There are two 2×4 shrouded IDC box headers, 2.54 mm pitch: **IN** (J1, from the Pico side)
and **OUT** (J2, away from the Pico). They sit side by side in the top-left corner, left of
the Pico, with OUT on the left and IN 12 mm to its right. Both use the same pinout and the
same orientation. A straight 8-way ribbon cable with IDC sockets connects one module's OUT
to the next module's IN. Crimp both sockets the same way round, so the cable lies flat between
the two connectors.

| Pin | Signal   | Direction (seen from the Pico)                     |
|-----|----------|----------------------------------------------------|
| 1   | 5V       | Supply, from Pico VBUS                             |
| 2   | GND      |                                                    |
| 3   | 3V3      | Supply, from Pico 3V3 out                          |
| 4   | GND      |                                                    |
| 5   | CLK      | Out to all modules                                 |
| 6   | LATCH    | Out to all modules                                 |
| 7   | LED_DATA | Out. IN pin → 595 SER; 595 QH' → OUT pin           |
| 8   | SW_DATA  | In. OUT pin → 165 SER; 165 QH → IN pin             |

CLK, LATCH, 5V, 3V3 and GND connect straight through from IN to OUT on each module.

On module 1, the Pico connects to the same nets that the IN connector carries, so the IN
header (J1) is not fitted there: nothing would plug into it, and leaving it off means no one
can plug a cable in there by mistake. No jumpers are needed to make a module the "master"
board: fitting the Pico is all it takes.

## Pico connections (module 1 only)

| Pico pin   | Net      | Notes                                               |
|------------|----------|-----------------------------------------------------|
| GP16 (21)  | CLK      | 33 Ω series resistor. PIO side-set pin 0            |
| GP17 (22)  | LATCH    | 33 Ω series resistor. PIO side-set pin 1            |
| GP18 (24)  | LED_DATA | 33 Ω series resistor. PIO OUT pin                   |
| GP19 (25)  | SW_DATA  | 33 Ω series resistor. PIO IN pin                    |
| VBUS (40)  | 5V       | USB 5 V; budget about 500 mA                        |
| 3V3 (36)   | 3V3      | Pico regulator; budget about 300 mA                 |
| GND        | GND      |                                                     |

These four GPIOs are on the Pico's inner pin row, which faces the rest of the board. That
keeps their tracks short.

The four 33 Ω resistors damp ringing on the ribbon cables. They are only fitted on module 1.

## Shift register bit assignment

**74HC165** (3V3). SH/LD̅ = LATCH, CLK = CLK, CLK INH = GND, SER = SW_DATA from the OUT
connector (10 kΩ pull-down, so the end of the chain reads 0), QH = SW_DATA to the IN
connector.

| 165 input | Use                                                                 |
|-----------|---------------------------------------------------------------------|
| H         | **Board-present marker**, tied to 3V3, so it always reads 1         |
| G         | **Footswitch**, active low: 10 kΩ pull-up, switch to GND, 100 nF to GND (RC ≈ 1 ms) |
| F … A     | Unused, tied to 3V3, so they always read 1                          |

H is shifted out first, so the first bit of each module's byte is the marker. When the
firmware reads a byte whose marker bit is 0, it has reached the end of the chain. That gives
the module count without any configuration.

**74HC595** (3V3). SRCLK = CLK, RCLK = LATCH, OE̅ = GND, SRCLR̅ = 3V3, SER = LED_DATA from
the IN connector, QH' = LED_DATA to the OUT connector.

| 595 output | Use                                                  |
|------------|------------------------------------------------------|
| QA         | LED red, through Q1                                  |
| QB         | LED green, through Q2                                |
| QC         | LED blue, through Q3                                 |
| QD … QH    | Unused, not connected                                |

A 1 bit turns an LED channel on.

### Scan timing

1. LATCH goes low. The 165s load their inputs.
2. LATCH goes high. The rising edge makes every 595 copy what was shifted in during the
   previous scan to its outputs. The 165s stop loading, and each one presents its H bit
   on QH.
3. Repeat 8 × N times: set LED_DATA, sample SW_DATA, then pulse CLK high.

LED data goes out with the last module's byte first. Switch data arrives with module 1's byte
first.

A 74HC part at 3.3 V is slower than at 5 V, but still clocks well above 10 MHz. A 4 MHz scan
clock leaves plenty of margin.

## RGB LED

The LED is a 5 mm through-hole RGB LED with 4 leads (R, common, G, B). It must be
**common anode**. The anode goes to 5V. Each cathode goes through its series resistor to the
collector of an NPN transistor (Q1–Q3, 2N2222A in TO-92), whose emitter is on GND. A 595
output drives each base through a 4.7 kΩ resistor (R16–R18). The base resistor is required:
without it, the transistor's base would clamp the 595 output at about 0.7 V.

```
 5V ── LED anode
       LED cathode R/G/B ── R1/R2/R3 ── collector Q1/Q2/Q3
 595 QA/QB/QC ── 4.7 kΩ ── base         emitter ── GND
```

Base current is (3.3 − 0.7) V / 4.7 kΩ ≈ 0.55 mA. That is ten times what a 5 mA collector
current needs, so the transistor is fully on and drops only about 0.1 V.

Check the lead order of the LEDs you buy against the footprint (KiCad
`LED_D5.0mm-4_RGB_Staggered_Pins`: pad 1 R, 2 common, 3 G, 4 B). Most 5 mm RGB LEDs use the
order R, common (longest lead), G, B. The staggered pads are larger and easier to solder than
the inline version; bend the leads slightly to fit.

Check the transistor pinout too. TO-92 2N2222A / PN2222A parts are usually emitter, base,
collector (flat side facing you, leads down), but not all makers follow that. A multimeter's
diode test finds the base: it conducts to both other leads.

Series resistors, from 5 V at about 5 mA per channel:

| Channel | Vf (typical) | Resistor | Current                              |
|---------|--------------|----------|--------------------------------------|
| Red     | 2.0 V        | 560 Ω    | (5 − 2.0 − 0.1) / 560 ≈ 5.2 mA       |
| Green   | 3.1 V        | 390 Ω    | (5 − 3.1 − 0.1) / 390 ≈ 4.6 mA       |
| Blue    | 3.1 V        | 390 Ω    | (5 − 3.1 − 0.1) / 390 ≈ 4.6 mA       |

The transistors can handle far more current than this, so the resistors only set brightness.
Lower values make the LED brighter; stay under 20 mA per channel, which is the usual LED
rating. Change values to balance the colours.

**Colour depth:** each channel is either on or off, which gives 7 colours plus off. The
current firmware does just that. For more shades, the firmware could use bit-angle
modulation, repeating the scan quickly with different on-times. For example, 8 modules at a 4 MHz clock take about 16 µs per scan, which is fast
enough for about 6 bits per channel without visible flicker.

An earlier version brought the unused inputs and outputs out to a 2×8 spare I/O header (J3),
with 10 kΩ pull-ups on the inputs. Nothing used it, so the header and its pull-ups are gone.

## Power budget

- **5V:** the LED current, at most about 15 mA per module with all three channels on. Ten
  modules draw about 150 mA from USB, well below the 500 mA limit.
- **3V3:** both shift registers, plus about 0.55 mA of base current per lit channel. That is
  under 2 mA per module, so ten modules add well under 30 mA to the Pico's 3V3 output. The
  Pico's regulator can supply about 300 mA. The LED current itself comes from 5V, not 3V3.

## PCB layout

The board is 80 × 86 mm. Seen from the top (component side, facing the enclosure's top panel):

- **Footswitch** at the bottom centre, with the **LED** straight above it, about 35 mm
  higher.
- **The LED drivers** sit between the LED and the switch: Q1–Q3 in a row under the LED, and
  the base resistors R16–R18 below them. The 10 µF capacitor C4 is next to the LED.
- **The shift registers** (U1 left, U2 right) are mirrored about the centre line, each with
  its decoupling capacitor on the outer side.
- **The resistors** stand upright in two banks either side of the switch: the footswitch
  pull-up R9 and the chain pull-down R4 on the left, and the LED resistors R1–R3 on the
  right.
- **The Pico** sits along the top edge on the right, with its USB port at the right edge.
  There is a 10 mm routing channel between the Pico and the ICs.
- **The chain connectors** sit side by side in the top-left corner, left of the Pico: OUT/J2
  at the left edge and IN/J1 12 mm to its right, both with pin 1 at the top left. The Pico
  series resistors R5–R8 lie flat under them, next to the Pico's GP16–GP19 pins.
- **Four M3 mounting holes**, 4 mm in from the side edges. The top pair is just under the
  Pico (27.2 mm from the top edge), so the Pico end of the board isn't left overhanging; the
  bottom pair is near the bottom corners (82 mm).
- Two copper layers, with a GND pour on both. Routed with Freerouting: signal tracks 0.3 mm,
  power 0.6 mm, 0.2 mm clearance, vias 0.8/0.4 mm.

## Mechanical

- **Pitch: 10 cm** between switches. The PCB is 80 mm wide, so there is a gap of 20 mm
  between boards. The chain cable runs from OUT at one module's top-left corner to IN on the
  next module, 88 mm away (centre to centre); see *Cable length* under
  [Enclosure](#enclosure).
- **Footswitch: PBS24-202P, momentary type.** This is a DPDT switch with 6 straight PCB pins
  in 2 rows of 3. It mounts through the enclosure top with its nut, and the PCB is soldered to
  its pins underneath. Standoffs from the PCB to the top panel take the load, so stomping
  does not stress the solder joints.
  - Datasheet (from the seller's listing):
    - Thread: M12×0.75, 12 mm long. Two nuts (14 mm across flats, 2.2 mm thick) and two
      washers are included.
    - Body below the thread: 17.4 × 14.3 mm, 20.6 mm tall.
    - Pins: 1.2 × 0.8 mm blades, 6 mm long. 2 rows of 3, 7.1 mm apart within a row
      (14.2 mm between the outer pins), with the rows 4.65 mm apart. The rows run along the
      17.4 mm side.
    - Contacts: pin 2 is common. 1–2 is closed at rest, and 2–3 is closed while pressed.
    - Operating force 2.8 ± 0.8 kgf, life ≥ 10,000 cycles. Rated 250 V AC 2 A.
  - **Wiring:** one pole only, pin 2 (common) → GND and pin 3 (NO) → the 165's G input.
    Pin 1 and the other pole's three pins go to unconnected pads, soldered only for
    mechanical strength. If pins 1 and 3 turn out to be swapped, the switch reads inverted,
    which the firmware can correct.
  - **Footprint:** round holes, 1.8 mm drill (the blade diagonal is 1.44 mm), 3.2 mm pads.
  - **Height:** the PCB sits 20.6 mm below the switch body's shoulder. See
    [Enclosure](#enclosure) for how this sets the standoff length.
- **LED:** pokes up into a 5.2 mm hole in the front plate, on a **19 mm LED spacer** (see
  [Enclosure](#enclosure)).
- **Pico:** on module 1, mounted on pin headers, USB port at the board's right edge. The
  enclosure needs a USB cutout there.

## Enclosure

The enclosure is a sandwich of two laser-cut 3 mm plates: the **front plate** on top and the
**back plate** underneath. The sides are open, so the USB port is reachable without a cutout.
There are no separate case spacers: each board's four mounting holes carry a **column** from
plate to plate. A 25 mm M3 **female-female standoff** runs from the front plate down to the
PCB. Under the PCB sits a 5 mm **male-female standoff** with its 6 mm stud pointing up
(3 mm bodies only come with a 3 mm stud, too short): the stud goes through the PCB's mounting hole into the long standoff and
clamps the board, without the back plate. An M3 × 6 screw from underneath holds the back
plate to the short standoff's female end. A stomp goes from the switch nut into the front plate, down the
columns next to the switch, and through the back plate into the feet, not through the solder
joints.

```
 front plate  ══[screw]═════════[nut+washer]════════════(LED)═════   3 mm
                  ║             [nut+washer]               │ │
                  ║  25 mm F-F   ┌────────┐ ─┬─ 4.4 mm    19 mm
                  ║  standoff    │ switch │  │            spacer
                  ║              │ body   │ 20.6 mm        │ │
 PCB          ════╬══════════════└────────┘══════════════════════   1.6 mm
                  ▓  5+6 mm M-F    leads cut to 3 mm or less
 back plate   ══[screw]══════════════════════════════════════════   3 mm (acrylic)
                 M3 × 6
               (foot)                                     (foot)
               front edge                              back edge
```

Overall: 37.6 mm from the back plate's underside to the front plate's top, plus the feet
(the case-spacer version was 46 mm), and 390 × 96 mm for 4 modules. The script also draws
this to scale for one module, in `mech/out/side_section.png`.

**3D model:** `uv run mech/assembly.py 4` writes `mech/out/assembly_4.step` (for CAD) and
`assembly_4.glb` (for viewers), with check renders `assembly_4_{front,inside,side}.png`. It
contains both plates, the columns (standoffs, spacers, screws), switch nuts and washers, LED
spacers, feet and chain cables, plus the boards with their components, exported from KiCad
with `kicad-cli pcb export step`. Module 1 (right-hand end) has the Pico and R5–R8; the others
don't. The LED is lifted onto its spacer in a temporary copy of the board before
the export. The IDC sockets and ribbons are simple blocks, placed where the estimates in this
section put them. KiCad's part models have uncut leads, so in the model they poke into the
back plate; on the real boards they are cut short (see *Under the PCB*).

- **Generator:** `uv run mech/plates.py 4 8` writes `mech/out/frontplate_N.dxf` and
  `backplate_N.dxf` for 4 and 8 modules. It reads the switch, LED, mounting-hole and
  chain-connector positions from `pcb/footswitch.kicad_pcb`, so the plates follow the board
  if parts move. Every dimension is a command-line option (`--help` lists them). Next to each
  DXF it writes two check renders: `*_preview.png` (the plate seen from above with the boards
  and parts in grey, and the feet under the back plate) and `*_dxf.png` (the DXF file itself,
  read back with ezdxf).
- **Columns:** at the board's mounting holes, 4 per module, 16 for 4 modules and 32 for 8.
  The hole rows are 27.2 and 82 mm from the board's back edge, so the front plate overhangs
  the back row by about 32 mm towards the back of the unit and the front row by about 9 mm.
  The stomp lands on the switch, 8 mm behind the front row of columns. Without case spacers,
  nothing supports the plate edges themselves. The plates will be acrylic, which may flex a
  little if someone stands on the back edge.
- **Under the PCB:** 5 mm from the PCB's underside to the back plate. **Cut every lead to
  3 mm or less** after soldering, including the footswitch pins (4.4 mm uncut) and the Pico
  header pins. That leaves at least 2 mm above the back plate. The back plate is acrylic, so
  a lead that touches it can't short anything. The short standoff's stud goes 4.4 mm into the
  long standoff, and the M3 × 8 top screw 5 mm from the other end. The M3 × 6 bottom screw
  goes 3 mm into the 5 mm short standoff. The script checks these.
- **Feet:** 2 per module under the back plate, one under each switch at the front edge
  (straight under the stomp) and one behind it at the back edge, so the unit can't tip when
  the overhanging back edge is stepped on. The script checks that no foot sits on a screw head.
- **DXF:** R2000, millimetres, one layer `CUT` (red). The outline is a closed polyline with
  arc corners, and the holes are circles: no splines, no duplicate lines.
- **Layout:** modules at 100 mm pitch, module 1 (Pico) at the right-hand end. 5 mm margin
  from the board edges to the plate edges. The footswitch side of the boards is the front
  edge (towards the player). Plate size: 390 × 96 mm for 4 modules, 790 × 96 mm for 8.
  Many hobby lasers have a bed smaller than 790 mm, so the 8-module plates may need a cutting
  service or a bigger machine. The back plate is the same size.
- **Holes:** front plate: 12.3 mm for the switch thread (M12 × 0.75), 5.2 mm for the LED and
  3.4 mm for the column screws. Back plate: only the column holes. The sizes are finished
  sizes. `--kerf` makes the outline larger and the holes smaller by half the beam width. Leave
  it at 0 if the cutting service compensates for kerf itself.
- **Stack-up:** 25 mm standoffs from the PCB to the plate's underside. The switch shoulder
  then sits 4.4 mm under the plate, room for one nut and washer, which clamp the plate
  together with the nut on top. That uses 10.4 mm of the 12 mm thread. The 19 mm LED spacer
  plus the 8.6 mm LED puts the LED tip level with the plate's top surface. The script checks
  these heights and the 2 mm minimum web between holes, and refuses to write a plate that
  fails.
- **Assembly:** screw the standoffs to the front plate and nut the switch in, lay the board
  on the standoffs (the switch pins through it), and solder the switch, so the switch and
  standoffs line up exactly. Screw the short standoffs up through the board into the long
  ones, cut the leads, then screw the back plate on with the M3 × 6 screws. (The build guide
  solders the switch first and fits the standoffs at the start of the mechanical assembly;
  that works too.)
- **Clearance under the plate:** the footswitch sets the height. Its body is 20.6 mm tall
  (confirmed by the 3D model in `pcb/footswitches.3dshapes/`), so the plate's underside can't
  be lower than about 21.4 mm (body plus a washer), and with the lower nut it is at 25 mm.
  The other tall parts:
  - **Chain connectors with the cable plugged in:** the box header is 9.1 mm tall (KiCad
    model). The FC socket body is 7.0 mm tall and its strain-relief clip adds up to 3.5 mm
    (Handsontec FC series drawing). Even if the socket sat on top of the shroud instead of
    inside it, that is 19.6 mm, which leaves 5.4 mm under the plate. In practice the socket
    sits inside the shroud and the clearance is closer to 10 mm. `plates.py` checks this.
  - **Ribbon direction:** the headers' long side runs front to back, so the ribbon leaves
    each socket sideways, at about 10–13 mm above the PCB, and runs straight along the top
    edge of the boards (the strip 5–15 mm from the back edge). From one module's OUT it goes
    left over the 20 mm gap and the next module's Pico area to that module's IN. On modules
    2 and up the Pico and R5–R8 aren't fitted, so it passes over bare board. On module 1 the
    IN connector is unused, so no cable runs over its Pico. The top mounting holes are 12 mm
    below the ribbon's edge.
  - **Cable length:** OUT of one module to IN of the next is 88 mm, centre to centre
    (100 mm pitch minus the 12 mm between OUT and IN). A 10 cm cable measured end to end,
    over both sockets (about 6 mm thick each), is about 94 mm centre to centre, so it has
    about 6 mm of slack and sags or bows slightly between the sockets. Shorter cables don't
    fit: a cable must be at least 88 mm centre to centre, about 94 mm end to end.
    If the 10 cm turns out to be the free ribbon between the sockets, there are about 18 mm
    of slack, which sags onto the next module's empty Pico area. That is harmless too.
  - **Pico** on module 1: about 15 mm on headers, more in sockets.
- **USB:** module 1's Pico USB port is at the board's right edge, 5 mm in from the plates'
  right edge. The sides are open, so the cable plugs straight in between the plates.

## Open items

- [ ] **Check the PBS24-202P against its datasheet** when the switches arrive: measure the pin
      spacing with calipers, and confirm with a multimeter that pin 2 is common and 2–3 closes
      when pressed. Cheap parts don't always match their drawings.
- [ ] **LED:** must be common anode. Check the lead order against the footprint.
- [ ] **Transistors:** check the 2N2222A pinout of the parts you buy.
- [ ] **Front plate:** before cutting the whole set, cut a one-module test piece
      (`uv run mech/plates.py 1`) and check the switch, LED and standoff fit.
- [ ] **Plate material:** choose it, and rerun the generator with `--panel-thickness` if it
      isn't 3 mm.
