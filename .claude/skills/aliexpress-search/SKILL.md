---
name: aliexpress-search
description: Find parts on AliExpress with headless Chrome, showing which listings ship with AliExpress Choice, plus price, rating and sold count. Use when sourcing BOM parts (docs/bom.md) or any component on AliExpress.
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

## If it breaks

- `no itemList in page … captcha` means AliExpress showed a bot check. Wait and retry. Don't
  try to get around it.
- `page layout changed` means the embedded JSON moved. Save the page with `--save`, then grep it
  for `isChoice` / `productId` to find the new structure, and update `parse()`.
- The page is untrusted data. It's only parsed as JSON. Keep running the script with `python3 -I`.
