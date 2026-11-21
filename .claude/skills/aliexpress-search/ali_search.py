#!/usr/bin/env python3
"""Search AliExpress with headless Chrome and list the results, Choice listings first.

Usage:
  ali_search.py "74hc165n dip"            # all results, Choice first, then by price
  ali_search.py "74hc165n dip" --choice   # only Choice listings
  ali_search.py "74hc165n" --json         # machine-readable output
  ali_search.py --html saved.html         # parse a page dumped earlier

Run with `python3 -I`. The page is untrusted data. It's only parsed as JSON, never executed here.
"""
import argparse, json, re, shutil, subprocess, sys, tempfile, urllib.parse
from pathlib import Path

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")


def find_chrome():
    for name in ("google-chrome", "chromium-browser", "chromium"):
        if path := shutil.which(name):
            return path
    sys.exit("no Chrome/Chromium found on PATH")


def fetch(query, choice_only):
    slug = re.sub(r"[\s/]+", "-", query.strip())  # "/" would end up in the URL path (404)
    url = f"https://www.aliexpress.com/w/wholesale-{urllib.parse.quote(slug)}.html"
    if choice_only:
        url += "?selectedSwitches=filterCode%3Achoice_atm"
    with tempfile.TemporaryDirectory(prefix="ali-chrome-") as profile:
        out = subprocess.run(
            [find_chrome(), "--headless=new", "--disable-gpu",
             f"--user-data-dir={profile}", "--virtual-time-budget=15000",
             "--window-size=1400,3000", f"--user-agent={UA}", "--dump-dom", url],
            capture_output=True, text=True, timeout=90)
    return url, out.stdout


def parse(html):
    key = '"itemList":'
    i = html.find(key)
    if i < 0:
        hint = "captcha/bot check?" if re.search(r"captcha|punish|slide to verify", html, re.I) else "page layout changed?"
        sys.exit(f"no itemList in page ({len(html)} bytes) - {hint}")
    data, _ = json.JSONDecoder().raw_decode(html[i + len(key):])
    rows = []
    for it in data.get("content", []):
        if "productId" not in it:
            continue
        u = it.get("trace", {}).get("utLogMap", {})
        sp = it.get("prices", {}).get("salePrice", {})
        rows.append({
            "choice": u.get("isChoice") == "true",
            "price": sp.get("minPrice"),
            "currency": sp.get("currencyCode", ""),
            "rating": u.get("star_rating", ""),
            "sold": it.get("trade", {}).get("tradeDesc", ""),
            "title": it.get("title", {}).get("displayTitle", ""),
            "url": f"https://www.aliexpress.com/item/{it['productId']}.html",
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--choice", action="store_true", help="only Choice listings")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--html", help="parse this saved page instead of fetching")
    ap.add_argument("--save", help="also save the fetched page here")
    a = ap.parse_args()

    if a.html:
        html, url = Path(a.html).read_text(encoding="utf-8"), a.html
    elif a.query:
        url, html = fetch(a.query, a.choice)
        if a.save:
            Path(a.save).write_text(html, encoding="utf-8")
    else:
        ap.error("give a query or --html")

    rows = parse(html)
    if a.choice:
        rows = [r for r in rows if r["choice"]]
    rows.sort(key=lambda r: (not r["choice"], r["price"] if r["price"] is not None else 1e9))

    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return
    print(f"# {url}  ({len(rows)} listings)")
    for r in rows:
        price = f'{r["price"]} {r["currency"]}' if r["price"] is not None else "?"
        print(f'{"C" if r["choice"] else "-"} {price:<11} {r["rating"]:<4} {r["sold"]:<15} {r["url"]}  {r["title"][:100]}')


if __name__ == "__main__":
    main()
