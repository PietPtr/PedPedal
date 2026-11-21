# Build instructions

TODO: add images to each step, rendered from kicad

Every board is the same PCB. The **main board** gets a Pico and four extra resistors.
**Extension boards** leave those out.

All parts go on the **top side** (the side with the white labels). Solder on the bottom.
Build from the lowest parts to the tallest, so the board lies flat while you solder.

**Board orientation used below:** labels readable, Pico area at the top, footswitch at the
bottom.

## Tools

Soldering iron, solder, side cutters, multimeter. A vise or IDC tool for the cables.

---

## Main board

### Step 1: 10 kΩ resistors, left row

| Part | Qty |
|------|-----|
| 10 kΩ resistor (brown-black-orange) | 8 |

1. Bend the leads, push into the 8 positions of the **left resistor row** (R4, R15 … R9).
2. Solder. Cut the leads.

Direction doesn't matter.

### Step 2: LED resistors, right row

| Part | Qty |
|------|-----|
| 560 Ω resistor (green-blue-brown) | 1 |
| 390 Ω resistor (orange-white-brown) | 2 |

1. **R1** (leftmost of the right row): 560 Ω.
2. **R2, R3** (next two): 390 Ω.
3. Solder. Cut the leads.

### Step 3: Pico resistors, right row (main board only)

| Part | Qty |
|------|-----|
| 33 Ω resistor (orange-orange-black) | 4 |

1. Fill the **4 rightmost** positions of the right row (R8, R7, R6, R5).
2. Solder. Cut the leads.

### Step 4: Ceramic capacitors

| Part | Qty |
|------|-----|
| 100 nF ceramic capacitor (marked `104`) | 3 |

1. Fit at **C3** and **C1** (left of U1) and **C2** (right of U2).
2. Solder. Cut the leads.

Direction doesn't matter.

### Step 5: LED jumper JP1

No parts. Bridge two of the three pads (below the LED) with a blob of solder:

- **Common anode LED**: bridge the middle pad to the **left** pad (`CA 5V`).
- **Common cathode LED**: bridge the middle pad to the **right** pad (`GND CC`).

Never bridge all three. Check your LED type before you do this.

### Step 6: IC sockets

| Part | Qty |
|------|-----|
| 16-pin DIP socket | 2 |

1. Fit at **U1** and **U2**, notch **up** (matching the notch in the outline).
2. Solder two opposite corner pins, check the socket is flat, then solder the rest.

Don't insert the chips yet.

### Step 7: Electrolytic capacitor

| Part | Qty |
|------|-----|
| 10 µF electrolytic capacitor | 1 |

1. Fit at **C4**. The **long lead (+)** goes in the hole marked **+** (top).
   The stripe on the can is the **−** side.
2. Solder. Cut the leads.

### Step 8: Headers

| Part | Qty |
|------|-----|
| 2×4 shrouded box header | 2 |
| 2×8 pin header | 1 |

1. **J2** (left, `OUT`) and **J1** (right, `IN`): the **notch** in the shroud faces the
   board edge, matching the outline.
2. **J3** (top left): 2×8 pin header.
3. For each: solder one pin, check it sits flat and straight, then solder the rest.

### Step 9: Pico (main board only)

| Part | Qty |
|------|-----|
| Raspberry Pi Pico | 1 |
| 1×20 pin header | 2 |
| 1×20 female socket (optional) | 2 |

1. *Optional:* solder the two female sockets into the **U3** rows on the board.
2. Push the pin headers into the board (or sockets), long pins down. Put the Pico on top,
   **components up, USB connector at the right**, over the `USB` label.
3. Solder all 40 pins on the Pico.
4. Without sockets: solder all 40 pins on the bottom of the board too.

### Step 10: Power check (main board only)

1. Plug USB into the Pico. No chips are fitted yet.
2. Measure on **J3** (pin 1 is the square pad):
   - pin 14 to pin 16: about **5 V**
   - pin 13 to pin 16: about **3.3 V**
3. Unplug USB.

If either is wrong, stop and look for solder bridges.

### Step 11: LED

| Part | Qty |
|------|-----|
| 5 mm RGB LED, 4 leads | 1 |
| 16 mm LED spacer | 1 |

1. Slide the spacer over the leads.
2. Fit at **D1**: the **red** lead goes in the **square pad** (left), the **longest lead**
   (common) in the **second** hole.
3. Push the spacer down to the board, check the LED stands straight, solder, cut the leads.

### Step 12: Footswitch

| Part | Qty |
|------|-----|
| PBS24-202P footswitch | 1 |
| M3 standoff + screw, ~22–24 mm | 4 |

1. Screw a standoff into each corner hole (**H1–H4**).
2. Put the switch's 6 pins through **SW1**. Pin 1 of the switch goes in the **square pad**.
3. Solder all 6 pins. All six, even the unused ones: they hold the switch.
4. **Test** with the meter on the bottom row of SW1 pads, middle pad to left pad:
   open when released, closed when pressed. If it's the other way round, the switch is
   turned wrong.

*Tip:* for a perfect fit, mount the switch and standoffs in the top panel first, lay the
board on, and solder it in place.

### Step 13: Chips

| Part | Qty |
|------|-----|
| 74HC165 | 1 |
| 74**HCT**595 | 1 |

1. Bend the chip legs slightly inward on a table so they fit the socket.
2. **74HC165 → U1** (left), **74HCT595 → U2** (right). Notch **up**, matching the socket.
3. Press in firmly. Check that no leg folded under.

Don't swap them: the 165 runs at 3.3 V and the 595 at 5 V.

**Main board done.**

---

## Extension board

Same PCB, same steps, but **skip step 3, step 9 and step 10**. Leave the 4 rightmost
resistor positions and the Pico area empty.

| Step | Do | Parts |
|------|----|-------|
| 1 | 10 kΩ, left row | 8 × 10 kΩ |
| 2 | LED resistors R1–R3 | 1 × 560 Ω, 2 × 390 Ω |
| ~~3~~ | ~~33 Ω resistors~~ | skip, leave empty |
| 4 | Ceramic caps C1–C3 | 3 × 100 nF |
| 5 | Bridge JP1 | solder only |
| 6 | IC sockets U1, U2 | 2 × DIP-16 socket |
| 7 | Electrolytic C4 | 1 × 10 µF |
| 8 | Headers J1, J2, J3 | 2 × box header, 1 × 2×8 header |
| ~~9~~ | ~~Pico~~ | skip |
| ~~10~~ | ~~Power check~~ | skip (check after connecting, below) |
| 11 | LED + spacer | 1 × RGB LED, 1 × spacer |
| 12 | Footswitch + standoffs | 1 × switch, 4 × standoff |
| 13 | Chips | 1 × 74HC165, 1 × 74HCT595 |

**Repeat for every extension board.**

---

## Cables and chaining

### Step 14: Make a ribbon cable

| Part | Qty per cable |
|------|---------------|
| 2×4 IDC socket | 2 |
| 8-way ribbon, OUT-to-IN distance + 2–3 cm slack | 1 |

1. Cut the ribbon square.
2. Lay it in the IDC socket, the **red wire on the pin-1 side** (marked ▼ on the socket).
3. Squeeze closed in a vise until flat. Fit the strain-relief clip.
4. Same on the other end, **same orientation** (red wire on pin 1 at both ends).

**Repeat:** one cable per extension board.

### Step 15: Connect

```
[Main board] OUT ──cable──► IN [Extension 1] OUT ──cable──► IN [Extension 2] ...
```

1. Main board **OUT** (J2, left) → first extension board **IN** (J1, right).
2. That board's **OUT** → next board's **IN**. Repeat.
3. The main board's IN and the last board's OUT stay empty.
4. Plug USB into the Pico. Check J3 on the **last** board: pin 14 ≈ 5 V, pin 13 ≈ 3.3 V.
