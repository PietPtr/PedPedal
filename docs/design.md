# Footswitch board design

A modular USB MIDI footswitch controller. Every module is the same PCB, and each carries one
footswitch, one RGB LED and spare I/O. Modules are chained with short ribbon cables. Only the
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
- `pcb/scripts/`: the scripts that generated the schematic and the board and ran the
  autorouter. They rebuild the files from scratch, so they overwrite any edits made in KiCad.

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
the right edge. The chain extends to the left: each module's OUT connector (left edge) goes to
the next module's IN connector (right edge).

Each module has two shift registers, both powered from **3V3**:

- **74HC165**, parallel in, serial out. It reads the footswitch, a board-present bit and 6
  spare inputs. The 165s form a chain whose data flows back toward the Pico.
- **74HC595**, serial in, parallel out. It drives the red, green and blue LED channels
  through three NPN transistors, and has 5 spare outputs. The 595s form a chain whose data
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

There are two 2×4 shrouded IDC box headers, 2.54 mm pitch: **IN** (from the Pico side, on the
right edge) and **OUT** (away from the Pico, on the left edge). Both use the same pinout and
the same orientation. A straight 8-way ribbon cable with IDC sockets connects one module's OUT
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
connector is left unconnected there. No jumpers are needed to make a module the "master"
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
| F … A     | Spare inputs IN1–IN6: 10 kΩ pull-up, active low, **3.3 V max**      |

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
| QD … QH    | Spare outputs OUT1–OUT5, 3.3 V logic                 |

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

**Colour depth:** each channel is either on or off, which gives 7 colours plus off. For more
shades, the firmware uses bit-angle modulation, repeating the scan quickly with different
on-times. For example, 8 modules at a 4 MHz clock take about 16 µs per scan, which is fast
enough for about 6 bits per channel without visible flicker.

## Spare I/O header

There is a 2×8 pin header, 2.54 mm pitch, on every module.

| Pin | Signal | Pin | Signal |
|-----|--------|-----|--------|
| 1   | IN1    | 2   | OUT1   |
| 3   | IN2    | 4   | OUT2   |
| 5   | IN3    | 6   | OUT3   |
| 7   | IN4    | 8   | OUT4   |
| 9   | IN5    | 10  | OUT5   |
| 11  | IN6    | 12  | GND    |
| 13  | 3V3    | 14  | 5V     |
| 15  | GND    | 16  | GND    |

- **Inputs:** 3.3 V logic, pulled up, active low. Connect a switch between the input and GND.
  **Do not apply 5 V.**
- **Outputs:** 3.3 V logic, straight from the 595, a few mA each. To drive an LED from 5V,
  or anything bigger, add a transistor like the ones on the RGB channels.
- Pin 14 still supplies 5V, for example for LEDs driven that way.

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
- **The shift registers** (U1 left, U2 right) and **the chain connectors** (OUT/J2 on the
  left edge, IN/J1 on the right edge) are mirrored about the centre line. The decoupling
  capacitors sit between each IC and its connector.
- **The resistors** stand upright in two banks either side of the switch: the pull-ups and
  pull-down on the left, and the LED and Pico series resistors on the right.
- **The Pico** sits along the top edge on the right, with its USB port at the right edge. The
  spare I/O header (J3) is at the top left, with pin 1 at its bottom-left corner: the IN row
  faces the board and the OUT row faces the top edge. There is a 10 mm routing channel between
  the Pico and the ICs.
- **Four M3 mounting holes**, one near each corner.
- Two copper layers, with a GND pour on both. Routed with Freerouting: signal tracks 0.3 mm,
  power 0.6 mm, 0.2 mm clearance, vias 0.8/0.4 mm.

## Mechanical

- **Pitch: 10 cm** between switches. The PCB is 80 mm wide, so the ribbon cable bridges a gap
  of about 20 mm between boards.
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
  - **Height:** the PCB sits 20.6 mm below the switch body's shoulder. With a nut and washer
    under a ~2 mm panel, the panel's top surface is about 24–25 mm above the PCB.
- **LED:** must reach a 5 mm hole in the top panel, about 24–25 mm above the PCB (see the
  switch height above). A 5 mm LED body is about 8.6 mm tall, so it needs a **~16 mm LED
  spacer**, or long leads with the height set using a jig.
- **Pico:** on module 1, mounted on pin headers, USB port at the board's right edge. The
  enclosure needs a USB cutout there.

## Open items

- [ ] **Check the PBS24-202P against its datasheet** when the switches arrive: measure the pin
      spacing with calipers, and confirm with a multimeter that pin 2 is common and 2–3 closes
      when pressed. Cheap parts don't always match their drawings.
- [ ] **LED:** must be common anode. Check the lead order against the footprint.
- [ ] **Transistors:** check the 2N2222A pinout of the parts you buy.
- [ ] **Enclosure:** which box, its top-panel layout, and where the USB cutout goes.
