# Bill of materials

All parts are through-hole, chosen for hand soldering. See [design.md](design.md) for how they
are used.

There is one PCB design. **Every module** gets the parts in the first table. **Module 1** also
gets the parts in the second table.

The **Status** column says whether a part is already on hand (**Have**), still to buy (**Order**),
or left off the board (**Not fitted**). **Listed** means [aliexpress.md](aliexpress.md) has a
listing for it.

## Every module

| Ref       | Qty | Part                                  | Value / type                  | Package                   | Example part number     | Status |
|-----------|-----|---------------------------------------|-------------------------------|---------------------------|-------------------------|--------|
| U1        | 1   | 8-bit PISO shift register (switches)  | 74HC165                       | DIP-16                    | TI SN74HC165N           | Order · listed |
| U2        | 1   | 8-bit SIPO shift register (LEDs)      | 74HC595                       | DIP-16                    | TI SN74HC595N           | Order · listed |
| (sockets) | 2   | IC socket for U1 and U2               | 16-pin                        | DIP-16                    | generic                 | Order · listed |
| D1        | 1   | RGB LED, 4-lead, diffused             | **common anode**              | 5 mm THT                  | generic                 | Order · listed |
| Q1–Q3     | 3   | NPN transistor (LED channel drivers)  | 2N2222A                       | TO-92                     | PN2222A / 2N2222A       | Have |
| R16–R18   | 3   | Base resistor (Q1–Q3)                 | 4.7 kΩ, 1/4 W                 | axial                     | generic                 | Order · listed |
| SW1       | 1   | Footswitch, momentary                 | DPDT, 1 pole used             | 6 PCB pins, 12 mm thread  | PBS24-202P (momentary)  | Order · listed |
| R9        | 1   | Pull-up resistor (footswitch)         | 10 kΩ, 1/4 W (4.7–47 kΩ is fine) | axial                  | generic                 | Have |
| R1        | 1   | Resistor (LED red)                    | 560 Ω, 1/4 W                  | axial                     | generic                 | Have |
| R2, R3    | 2   | Resistor (LED green, blue)            | 390 Ω, 1/4 W                  | axial                     | generic                 | Order · listed |
| R4        | 1   | Resistor (SW_DATA end-of-chain pull-down) | 10 kΩ, 1/4 W              | axial                     | generic                 | Have |
| C1, C2    | 2   | Decoupling capacitor (U1, U2, on 3V3) | 100 nF, 50 V, ceramic         | radial, 5.08 mm pitch     | generic                 | Have |
| C3        | 1   | Footswitch debounce capacitor         | 100 nF, 50 V, ceramic         | radial, 5.08 mm pitch     | generic                 | Have |
| C4        | 1   | Bulk capacitor (5V)                   | 10 µF, 16 V, electrolytic     | radial, 2.0 mm pitch      | generic                 | Have (10 µF 25 V) |
| J1, J2    | 2   | Chain connector, IN and OUT (main board: OUT only, no J1) | 2×4 shrouded box header       | 2.54 mm, vertical         | generic                 | Order · listed |

R9 is the footswitch's pull-up to 3V3. The 165's six unused inputs are tied straight to 3V3,
so they need no resistors.

Buy **common-anode** RGB LEDs: the anode goes to 5V and the transistors switch the cathodes.
R1–R3 set about 5 mA per channel. Lower values make the LED brighter, up to about 20 mA per
channel.

The LED spacer, standoffs and screws are listed under
[Enclosure: plates and mounting hardware](#enclosure-plates-and-mounting-hardware).

Q1–Q3: any small NPN works (2N3904 and BC547 too), but the footprint follows the usual TO-92
2N2222A / PN2222A pinout of emitter, base, collector. Check the pinout of the parts you buy
before soldering.

## Module 1 only (adds the Pico)

| Ref        | Qty | Part                          | Value / type            | Package             | Example part number       | Status |
|------------|-----|-------------------------------|-------------------------|---------------------|---------------------------|--------|
| U3         | 1   | Raspberry Pi Pico (RP2040)    | Pico 1, not Pico 2      | module              | Raspberry Pi SC0915       | Have |
| —          | 2   | Pin header for the Pico       | 1×20, 2.54 mm           | THT                 | generic                   | Have |
| —          | 2   | Female socket for the Pico (optional, lets you remove it) | 1×20, 2.54 mm | THT     | generic                   | Optional |
| R5–R8      | 4   | Series resistor (CLK, LATCH, LED_DATA, SW_DATA) | 33 Ω, 1/4 W | axial          | generic                   | Have |

## Per cable between two modules

| Qty | Part | Notes | Status |
|-----|------|-------|--------|
| 1 | Prefab FC-8P to FC-8P ribbon cable, 2.54 mm, wired pin 1 to pin 1 | 10 cm: OUT to the next module's IN is 88 mm, centre to centre, so the cable runs nearly straight along the top edge. Not shorter. See aliexpress.md for the crimp type | Order · listed |

To build cables yourself instead, you need 2 FC-8P IDC sockets and 8-way 1.27 mm flat ribbon per
cable, crimped with a vise or an IDC tool.

## Enclosure: plates and mounting hardware

The enclosure is two laser-cut acrylic plates with open sides. There are no separate case
spacers: each board's four mounting holes carry a column from plate to plate. A 25 mm
female-female standoff goes from the front plate down to the PCB. Under the PCB sits a 5 mm
male-female standoff, stud up: the stud goes through the PCB into the long standoff and
clamps the board. An M3 × 6 screw holds the back plate to its female end. The stomp goes straight down the columns to the feet. The footswitch
is clamped in the front plate by its own nuts, and the LED pokes up into a 5 mm hole. The
plates are cut from `mech/out/frontplate_N.dxf` and `backplate_N.dxf`. See
[design.md](design.md#enclosure) for the stack-up.

Per module:

| Qty | Part | Size | Notes | Status |
|-----|------|------|-------|--------|
| 4 | Hex standoff, female-female | M3 × 25 mm | Brass or steel, not nylon: they carry the stomping load | Order · listed |
| 4 | Hex standoff, male-female, under the PCB | M3 × 5 mm + 6 mm stud | Brass. Stud up through the PCB into the 25 mm standoff. Cut all leads under the PCB to 3 mm or less, the switch pins too | Order · listed |
| 4 | Screw, front plate to standoff | M3 × 6 mm, button head (ISO 7380) | 3 mm plate + 3 mm into the 25 mm standoff. Same screw as the back plate, so one pack covers both. For flush heads, countersink the plate by hand and use countersunk M3 × 6 | Order · listed (pick 6 mm) |
| 4 | Screw, back plate to short standoff | M3 × 6 mm, button head (ISO 7380) | 3 mm plate + 3 mm into the 5 mm short standoff | Order · listed (pick 6 mm) |
| 1 | LED spacer, for 5 mm LED | 19 mm | Puts the LED tip level with the plate's top surface. 18 mm sits 1 mm lower; 20 mm sticks out 0.6 mm | Order · listed (pick the 19 mm variant) |
| 2 | Rubber foot, stick-on | 12 mm across, 3+ mm tall | Under the back plate: one under the switch at the front edge, one behind it at the back edge. Tall enough to clear the screw heads (about 1.7 mm) | Order · listed |
| — | Switch nuts and washers | M12 × 0.75 | 2 nuts + 2 washers come with each PBS24-202P: one nut and washer under the plate, one on top | Comes with the switch |

Per enclosure (4 modules / 8 modules):

| Qty | Part | Size | Notes | Status |
|-----|------|------|-------|--------|
| 1 | Front plate, laser cut | 390 × 96 mm / 790 × 96 mm | 3 mm acrylic, from `mech/out/frontplate_N.dxf` | Order |
| 1 | Back plate, laser cut | same | 3 mm, from `mech/out/backplate_N.dxf`. Only the column holes | Order |

Optional side walls, 3D printed from `mech/walls.py` (see
[design.md](design.md#side-walls)). The same prints fit any number of modules:

| Qty | Part | Size | Notes | Status |
|-----|------|------|-------|--------|
| 1 | Wall end cap, left | 98 × 102 × 37.6 mm | `mech/out/walls_N_end_left.stl`, PETG or PLA | Print |
| 1 | Wall end cap, right | same | `walls_N_end_right.stl`, with the USB cutout | Print |
| 2N − 4 | Wall, straight | 100 × 6 × 37.6 mm | `walls_N_straight.stl`: 4 for 4 modules, 12 for 8 | Print |
| 4N − 4 | Alignment pin | 1.75 mm filament, 11 mm | Two per joint | Have |

The lengths above are for 3 mm plates. For other sizes, run
`uv run mech/plates.py N --panel-thickness T --pcb-spacer L --top-screw S --bottom-screw S`: it prints the LED spacer, screw
and spacer numbers for that stack and refuses combinations that don't fit.

## Totals for N modules

[bom.ods](bom.ods) works these out with whole lots and prices: fill in the number of main and
extra boards at the top. Its *Scenarios* sheet lists the cost per board for 1–4 main boards and
0–32 extra boards. Update its prices and lot sizes when [aliexpress.md](aliexpress.md) changes.

- Modules: N × the first table, plus 1 × the second table.
- Box headers: 2N − 1, because the main board has no J1.
- Cables: N − 1.
- Enclosure: front and back plate, plus N × the per-module hardware above (8N standoffs, 8N screws, N LED spacers, 2N feet).
- Spares: a couple of extra DIP-16s and LEDs, in case one is wrong or damaged.
