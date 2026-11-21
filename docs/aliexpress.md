# AliExpress sourcing

Listings found for parts in [bom.md](bom.md), preferring **AliExpress Choice** shipping. Found
with the `aliexpress-search` project skill on 2026-11-21. Prices are in EUR for the NL region, as
listed on that date. On multi-SKU listings (many part numbers or variants in one listing), the
search price is the cheapest variant and may differ for the one you need.

## Picks

| Ref | Part | Listing | Choice | Price | Rating / sold | Order |
|---|---|---|---|---|---|---|
| U1 | 74HC165, DIP-16 | [10 pcs 74HC165N DIP-16](https://www.aliexpress.com/item/32840140062.html) | ✅ | €2.65 / 10 | 4.9 / 500+ | 1 lot |
| U2 | 74HC595, DIP-16 | [10 pcs SN74HC595N DIP-16](https://www.aliexpress.com/item/1005006852374339.html) | ✅ | €1.98 / 10 | 5.0 / 642 | 1 lot |
| D1 | RGB LED 5 mm, common anode, diffused | [10 pcs 5 mm RGB, CA/CC, diffused/clear](https://www.aliexpress.com/item/1005004567358995.html) | ✅ | €1.79 / 10 | 5.0 / 243 | Variant: **common anode + diffused** |
| C4 | 10 µF ≥16 V electrolytic, 5 mm body | [10 pcs 10 µF 35 V, 5×7 mm](https://www.aliexpress.com/item/32549212762.html) | ✅ | €2.21 / 10 | 4.9 / 137 | 1 lot |
| J1, J2 | 2×4 shrouded box header, straight | [10 pcs DC3 straight box header](https://www.aliexpress.com/item/1005006955027637.html) | ✅ | €1.92 / 10 | 4.9 / 203 | Variant **2X4 8P**, 2 lots |
| SW1 | PBS24-202P, momentary | [10 pcs PBS24-202P, latching or momentary](https://www.aliexpress.com/item/1005009955228811.html) | ❌ | €13.49 / 10 | — | Variant **momentary type**. Not Choice, but about €1.35 each versus about €4.70–5 each on Choice |
| Cable | FC-8P to FC-8P ribbon, pin 1 to pin 1 | [TLZWLA FC flat cable](https://www.aliexpress.com/item/1005010330266180.html) | ✅ | about €2 each | 4.7 / 1,000+ | Variant **Type F**, 2x4Pin 8P, 10 cm. 1 per module pair + spares |

## Alternatives

| Ref | Listing | Choice | Price | Rating / sold | Notes |
|---|---|---|---|---|---|
| U1 | [10 pcs SN74HC165N DIP16, 8-bit](https://www.aliexpress.com/item/1005009627396281.html) | ✅ | €2.92 / 10 | 4.8 / 210 | Sells only the 165 |
| U2 | [10 pcs SN74HC595N DIP16](https://www.aliexpress.com/item/1005004856540723.html) | ✅ | €2.07 / 10 | 5.0 / 716 | Sells only the 595 |
| U2 | [10 pcs SN74HC595N DIP-16](https://www.aliexpress.com/item/32796581727.html) | ✅ | €2.26 / 10 | 4.8 / 312 | Sells only the 595 |
| D1 | [15/50 pcs 5 mm RGB, CA/CC, diffused/clear](https://www.aliexpress.com/item/1005006076342525.html) | ✅ | from €3.13 | 5.0 / 353 | Variant: common anode + diffused |
| D1 | [50/100 pcs 5 mm RGB, CA/CC, diffused ("fog")](https://www.aliexpress.com/item/1005006943069327.html) | ✅ | from €3.17 | 5.0 / 87 | Bigger lots |
| C4 | [10 pcs 10 µF 16 V, 5×11 mm](https://www.aliexpress.com/item/1005002396048673.html) | ✅ | €2.40 / 10 | 4.6 / 241 | Sells only this part |
| J1, J2 | [DC3 straight header **or** FC socket, 6–60 pin](https://www.aliexpress.com/item/1005010320848595.html) | ✅ | about €3 / 10 | 4.9 / 800+ | Variants "10PCS STRAIGHT TYPE" + 8P. The same listing sells FC-8P sockets for DIY cables |
| SW1 | [PBS24-202P, latching or momentary, per piece](https://www.aliexpress.com/item/1005008778272138.html) | ✅ | €4.99 each (€9.17 each for 2+ appears to be for another variant) | 4.8 / 322 | Variant momentary type. About 3.7× the price of the non-Choice 10-pack |
| SW1 | [PBS24-202P, latching or momentary, per piece](https://www.aliexpress.com/item/1005012829002757.html) | ✅ | €4.69 each | 5.0 / 33 | Variant momentary type. Few sales |
| Cable | [FC flat cable, "same direction" drawing](https://www.aliexpress.com/item/1005012338425904.html) | ✅ | from €1.89 | 4.9 / 337 | Variant (2x4)8Pin. Lengths start at 10 cm |

## Notes

- **D1:** most RGB listings sell common anode and cathode, diffused and clear, in one listing.
  Pick **common anode** and **diffused** explicitly. Skip the square "2×5×5 mm", straw-hat and
  piranha types. A diffused LED gives an even glow through the panel. Check the anode lead
  (longest) against the footprint when fitting.
- **C4:** a 5 mm body has a 2.0 mm lead pitch, which matches the footprint. Avoid 4×7 mm parts
  (1.5 mm pitch). Pitch was inferred from the body size in the titles. Check the photo once.
  The "Nichicon" branding on cheap listings is probably fake, which doesn't matter for a bulk
  capacitor on 5V.
- **J1, J2:** some listings also offer right-angle ("curved needle") headers. Pick straight.
  Several popular box header listings skip 8P entirely.
- **Cable type:** the TLZWLA listing has crimp types A–F. Choose by the pin-mapping picture, not
  the seller's "same/opposite direction" label. A, C and F are wired 1→1, and B, D and E are
  reversed. **Type F** has both sockets the same way round with a flat ribbon. It matches the
  board, where J1 and J2 have the same rotation.
- **Cable length:** on the PCB, CHAIN_OUT (J2) is on the left edge and CHAIN_IN (J1) on the
  right, viewed from the top of the PCB. At 10 cm pitch with module 2 left of module 1 (top
  view), the gap from OUT to the next IN is about 31 mm, so 10 cm is enough. If you chain the
  modules the other way, the gap is about 169 mm and you need 20 cm.
- **Not searched yet:** Q1–Q3 (2N2222A), resistors, 100 nF capacitors, IC sockets, J3 (2×8
  header), the Pico, Pico headers and sockets, the LED spacer, and standoffs.
