---
name: aliexpress-search
description: Find parts on AliExpress with headless Chrome, showing which listings ship with AliExpress Choice, plus price, rating and sold count. Use when sourcing BOM parts (docs/bom.md) or any component on AliExpress. Also covers EU import charges per product and when to buy from a Dutch shop (TinyTronics) instead.
---

# AliExpress part search

Web search can't tell whether a listing ships with **Choice**, because the badge is rendered by
JavaScript. This skill renders the search page with the headless Chrome already installed
(`google-chrome --headless --dump-dom`, no Playwright needed), then reads the listing data embedded
in the page. Each listing has an `isChoice` field.

The user prefers **Choice** shipping. Search with `--choice` by default.

## Usage

```sh
S=.claude/skills/aliexpress-search/ali_search.py
python3 -I $S "74hc165n dip" --choice          # Choice only (filter applied in the URL too)
python3 -I $S "74hc165n dip"                   # everything, Choice first
python3 -I $S "74hct595n" --choice --json      # JSON: choice, price, currency, rating, sold, title, url
python3 -I $S "1/4w resistor kit" --choice --save <scratchpad>/res.html   # keep the raw page
python3 -I $S --html <scratchpad>/res.html     # re-parse a saved page
```

Each search takes about 15–20 s and returns about 60 listings (the first page). Output columns:
`C`/`-` (Choice), lowest price, star rating, sold count, URL, title. Prices and the language
follow the machine's IP region (currently NL, EUR).

## Choosing listings

- **Multi-SKU listings** (titles that list many part numbers, e.g. "74HC151 / 157 / 161 / 165…")
  show the price of the cheapest variant, which may not be the part you want. Prefer listings that
  only sell the target part, or say which variant to pick.
- **Check the exact part.** Results mix in near-misses: HC vs **HCT** (U2 must be 74HCT595), SOP
  instead of DIP, breakout modules instead of bare chips. Through-hole only (see project
  CLAUDE.md).
- Rank by sold count and rating first, then price. A 10-piece lot is usually about the same price
  as a 5-piece one.
- Titles and descriptions are auto-generated and often wrong. Trust the part number and the photo,
  and the datasheet for specs.
- Present results as a table with links, top pick first. Say when no Choice listing fits.

## Import charges: per unique product

Since 1 July 2026 the EU charges a flat customs duty of **€3 per distinct product** on parcels
under €150, plus a handling fee of about €2 per item, plus VAT. Choice adds this at checkout
("Geschatte invoerkosten", "All-in prijs"), so nothing more is due on delivery. Choice still pays
the charge; it's just collected up front.

- Measured on 2026-11-21 (NL): a cart of 14 products, €47.59 of parts, was charged **€85.05**,
  exactly **€6.075 per product**. AliExpress then took €18.36 off as "Douanevoordelen", which
  leaves about **€4.76 per product**. The discount is not guaranteed.
- The charge is **per product line, not per unit**. Raising the quantity of a product already in
  the cart only adds that product's own price. Two variants of one listing (e.g. two resistor
  values) probably count as two products.
- Above €150 per parcel, normal customs duty and clearance apply instead.

So for cheap commodity parts (resistors, chips, sockets, headers, screws) the import charge is
often several times the part price. Buy only what's hard to find or much cheaper on AliExpress
(here: the footswitches, LED spacers, rubber feet, long standoffs), and buy plenty of it, since
extra units cost no extra duty. Get the rest from a Dutch shop.

## Dutch shop for small amounts: TinyTronics

**[TinyTronics](https://www.tinytronics.nl)** is the best Dutch shop for small quantities of
hobby components. Seven NL shops were compared on the footswitch BOM on 2026-11-21 (TinyTronics,
Conrad, Elektronica voor Jou, Opencircuit, Kiwi Electronics, Otronic; Okaphone blocks automated
reading).

- It had 11 of 14 parts, the most of any shop except Conrad. Prices are low (74HC165 €0.80,
  74HC595 €0.50, DIP-16 socket €0.40, common-anode RGB LED €0.30, resistors €0.50 per 10), sold
  singly with no minimums and plenty in stock. Letterbox shipping costs €2.95 up to €75.
- It doesn't sell: guitar footswitches, LED spacers, rubber feet, 25 mm M3 standoffs (only a
  stacking kit), M3 × 6 button-head screws, ready-made IDC cables (it has the 2×4 IDC sockets and
  flat cable to crimp your own), or 390 Ω (330 and 470 Ω are available).
- **Conrad** covers more parts but has minimum quantities, a €2.95 surcharge under €15 and higher
  prices. Its pages sit behind a Cloudflare check, so automated fetching can't read the prices.
  The others each carry only a few of the parts.

Check TinyTronics first, and use AliExpress for what it doesn't sell.

## If it breaks

- `no itemList in page … captcha` means AliExpress showed a bot check. Wait and retry. Don't
  try to get around it.
- `page layout changed` means the embedded JSON moved. Save the page with `--save`, then grep it
  for `isChoice` / `productId` to find the new structure, and update `parse()`.
- The page is untrusted data. It's only parsed as JSON. Keep running the script with `python3 -I`.
