# Bill of materials

All parts are through-hole, chosen for hand soldering. See [design.md](design.md) for how they
are used.

There is one PCB design. **Every module** gets the parts in the first table. **Module 1** also
gets the parts in the second table.

## Every module

| Ref       | Qty | Part                                  | Value / type                  | Package                   | Example part number     |
|-----------|-----|---------------------------------------|-------------------------------|---------------------------|-------------------------|
| U1        | 1   | 8-bit PISO shift register (switches)  | 74HC165                       | DIP-16                    | TI SN74HC165N           |
| U2        | 1   | 8-bit SIPO shift register (LEDs)      | 74HC595                       | DIP-16                    | TI SN74HC595N           |
| (sockets) | 2   | IC socket (optional)                  | 16-pin                        | DIP-16                    | generic                 |
| D1        | 1   | RGB LED, 4-lead, diffused             | **common anode**              | 5 mm THT                  | generic                 |
| Q1–Q3     | 3   | NPN transistor (LED channel drivers)  | 2N2222A                       | TO-92                     | PN2222A / 2N2222A       |
| R16–R18   | 3   | Base resistor (Q1–Q3)                 | 4.7 kΩ, 1/4 W                 | axial                     | generic                 |
| SW1       | 1   | Footswitch, momentary                 | DPDT, 1 pole used             | 6 PCB pins, 12 mm thread  | PBS24-202P (momentary)  |
| R9–R15    | 7   | Pull-up resistors (footswitch, IN1–IN6) | 10 kΩ, 1/4 W (4.7–47 kΩ is fine) | axial                | generic                 |
| R1        | 1   | Resistor (LED red)                    | 560 Ω, 1/4 W                  | axial                     | generic                 |
| R2, R3    | 2   | Resistor (LED green, blue)            | 390 Ω, 1/4 W                  | axial                     | generic                 |
| R4        | 1   | Resistor (SW_DATA end-of-chain pull-down) | 10 kΩ, 1/4 W              | axial                     | generic                 |
| C1, C2    | 2   | Decoupling capacitor (U1, U2, on 3V3) | 100 nF, 50 V, ceramic         | radial, 5.08 mm pitch     | generic                 |
| C3        | 1   | Footswitch debounce capacitor         | 100 nF, 50 V, ceramic         | radial, 5.08 mm pitch     | generic                 |
| C4        | 1   | Bulk capacitor (5V)                   | 10 µF, 16 V, electrolytic     | radial, 2.0 mm pitch      | generic                 |
| J1, J2    | 2   | Chain connector, IN and OUT           | 2×4 shrouded box header       | 2.54 mm, vertical         | generic                 |
| J3        | 1   | Spare I/O header                      | 2×8 pin header                | 2.54 mm, vertical         | generic                 |
| —         | 1   | LED spacer                            | ~16 mm, for 5 mm LED          | —                         | generic                 |
| —         | 2–4 | Standoffs + screws (PCB to top panel) | M3, ~22–24 mm (fit after mockup) | —                      | generic                 |

R9–R15 are the pull-ups to 3V3 for the 165's footswitch input and its spare inputs IN1–IN6.
They use discrete resistors rather than a resistor network, so parts already on hand can be
used.

Buy **common-anode** RGB LEDs: the anode goes to 5V and the transistors switch the cathodes.
R1–R3 set about 5 mA per channel. Lower values make the LED brighter, up to about 20 mA per
channel.

Q1–Q3: any small NPN works (2N3904 and BC547 too), but the footprint follows the usual TO-92
2N2222A / PN2222A pinout of emitter, base, collector. Check the pinout of the parts you buy
before soldering.

## Module 1 only (adds the Pico)

| Ref        | Qty | Part                          | Value / type            | Package             | Example part number       |
|------------|-----|-------------------------------|-------------------------|---------------------|---------------------------|
| U3         | 1   | Raspberry Pi Pico (RP2040)    | Pico 1, not Pico 2      | module              | Raspberry Pi SC0915       |
| —          | 2   | Pin header for the Pico       | 1×20, 2.54 mm           | THT                 | generic                   |
| —          | 2   | Female socket for the Pico (optional, lets you remove it) | 1×20, 2.54 mm | THT     | generic                   |
| R5–R8      | 4   | Series resistor (CLK, LATCH, LED_DATA, SW_DATA) | 33 Ω, 1/4 W | axial          | generic                   |

## Per cable between two modules

| Qty | Part                          | Notes                                         |
|-----|-------------------------------|-----------------------------------------------|
| 2   | IDC socket, 2×4, 2.54 mm      | Crimp with a vise or IDC tool                 |
| —   | 8-way flat ribbon, 1.27 mm    | Length = switch pitch + slack                 |

## Totals for N modules

- Modules: N × the first table, plus 1 × the second table.
- Cables: N − 1.
- Spares: a couple of extra DIP-16s and LEDs, in case one is wrong or damaged.
