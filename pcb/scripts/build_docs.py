#!/usr/bin/env python3
"""Generate the build instructions, docs/build.md, and their images in docs/build/.

    python3 pcb/scripts/build_docs.py [--board pcb/footswitch.kicad_pcb] [--quality high|basic]
                                      [--no-images]

The step texts live in STEPS below. Everything else comes from the board:
- Parts tables: values and refs are read from the footprints, and resistor colour codes are
  worked out from the values.
- Images: for each step, the board is copied with the 3D models of parts not yet fitted
  hidden, then rendered with kicad-cli. The new parts are outlined: the step is also rendered
  without them, and the pixels that changed are outlined.

Edit this script, not docs/build.md: the next run overwrites it.

The texts describe positions and orientations ("flat side down", "+ on the left"). Those
facts are checked against the board in CHECKS. If the layout changes, the run fails until
the text and CHECKS are brought up to date. Every footprint must belong to a step (or to
NOT_IN_STEPS), so a new part can't be left out of the instructions without notice.

Renders are cached in ~/.cache/footswitch-build-docs, keyed on the board variant and render
settings, so a run where only the text changed re-renders nothing.
"""
import argparse, copy, hashlib, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sx
from sx import Sym, find, find1

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'footswitch-build-docs'

# Camera: tilted towards the viewer, as if looking at the board on the bench from the front.
RENDER_ARGS = ['--width', '1600', '--height', '1300', '--rotate', '-35,0,0', '--perspective',
               '--background', 'transparent']
OUT_WIDTH = 1000          # px, final image width
NEW_COLOUR = (255, 40, 200)     # outline around the parts of this step
EMPTY_COLOUR = (255, 150, 0)    # outline around positions left empty
# A chip in its socket. The socket footprint only has the socket's model.
CHIP_MODEL = '${KICAD10_3DMODEL_DIR}/Package_DIP.3dshapes/DIP-16_W7.62mm.step'
CHIP_Z = 3.0              # mm, lifts the chip onto the socket

# ------------------------------------------------------------------------------------ steps
# refs:      footprints fitted in this step (their 3D models appear from this step on).
# highlight: extra footprints to outline without fitting anything (e.g. the test header).
# chips:     sockets that get their chip in this step.
# extra:     parts that are not footprints on the board, as (qty, description).
# main_only: skipped on extension boards.
STEPS = [
    dict(slug='10k', title='10 kΩ resistors, left bank', refs=['R4', 'R9', 'R10', 'R11', 'R12',
         'R13', 'R14', 'R15'], text="""
1. Bend the leads and push the resistors into all 8 positions of the **left resistor bank**.
2. Solder. Cut the leads.

They are all the same value, and direction doesn't matter.
"""),
    dict(slug='led-resistors', title='LED resistors, right bank', refs=['R1', 'R2', 'R3'], text="""
1. **R1** (leftmost position of the right bank): 560 Ω.
2. **R2, R3** (the next two): 390 Ω.
3. Solder. Cut the leads.

Check the colour bands before soldering: R1 is the odd one out.
"""),
    dict(slug='base-resistors', title='Transistor base resistors', refs=['R16', 'R17', 'R18'],
         text="""
1. Fit **R16, R17, R18**, the three resistors lying across the middle of the board.
2. Solder. Cut the leads.
"""),
    dict(slug='33r', title='Pico series resistors (main board only)', main_only=True,
         refs=['R5', 'R6', 'R7', 'R8'], text="""
1. Fill the **4 rightmost** positions of the right bank (R8, R7, R6, R5).
2. Solder. Cut the leads.
"""),
    dict(slug='ceramic', title='Ceramic capacitors', refs=['C1', 'C2', 'C3'], text="""
1. Fit **C3** and **C1** (left of U1) and **C2** (right of U2).
2. Solder. Cut the leads.

Direction doesn't matter.
"""),
    dict(slug='sockets', title='IC sockets', refs=['U1', 'U2'],
         extra=[(2, '16-pin DIP socket')], text="""
1. Fit sockets at **U1** and **U2**, with the notch **up**, matching the notch in the outline.
2. Solder two opposite corner pins, check that the socket sits flat, then solder the rest.

Don't insert the chips yet.
"""),
    dict(slug='transistors', title='Transistors', refs=['Q1', 'Q2', 'Q3'], text="""
1. Fit at **Q1, Q2, Q3**, with the **flat side down** (towards the footswitch), matching the
   outline. Leave a few mm of lead under the body; don't push them all the way down.
2. Solder. Cut the leads.

The footprint expects the usual pinout: emitter, base, collector from left to right, seen
from the flat side. The emitter goes in the square pad. Check the pinout of your parts first
(a multimeter's diode test finds the base: it conducts to both other leads).
"""),
    dict(slug='electrolytic', title='Electrolytic capacitor', refs=['C4'], text="""
1. Fit at **C4**, right of the LED. The **long lead (+)** goes in the **square pad**, on the
   left, next to the **+** mark. The stripe on the can marks the **−** side.
2. Solder. Cut the leads.
"""),
    dict(slug='headers', title='Headers', refs=['J1', 'J2', 'J3'], text="""
1. **J2** (`OUT`, left) and **J1** (`IN`, right): both go the same way round, with the
   **notch** in the shroud on the **left**, matching the outline.
2. **J3** (top left): the 2×8 pin header.
3. For each: solder one pin, check that it sits flat and straight, then solder the rest.
"""),
    dict(slug='pico', title='Pico (main board only)', main_only=True, refs=['U3'],
         extra=[(2, '1×20 pin header'), (2, '1×20 female socket (optional)')], text="""
1. *Optional:* solder the two female sockets into the **U3** rows on the board. That lets you
   take the Pico out again.
2. Push the pin headers into the board (or the sockets), long pins down. Put the Pico on top,
   **components up, USB connector at the right**, over the board edge.
3. Solder all 40 pins on top of the Pico.
4. Without sockets: also solder all 40 pins on the bottom of the board.
"""),
    dict(slug='power-check', title='Power check (main board only)', main_only=True, refs=[],
         highlight=['J3'], text="""
1. Plug USB into the Pico. No chips are fitted yet.
2. Measure on **J3** (pin 1 is the square pad):
   - pin 14 to pin 16: about **5 V**
   - pin 13 to pin 16: about **3.3 V**
3. Unplug USB.

If either is wrong, stop and look for solder bridges.
"""),
    dict(slug='led', title='LED', refs=['D1'], extra=[(1, 'LED spacer, ~16 mm')], text="""
The LED must be **common anode**.

1. Slide the spacer over the leads.
2. Fit at **D1**: the **red** lead goes in the **square pad** (left), the **longest lead**
   (common anode) in the **second** hole. The holes are staggered, so bend the leads slightly
   to fit.
3. Push the spacer down to the board, check that the LED stands straight, solder, and cut the
   leads.
"""),
    dict(slug='footswitch', title='Footswitch and standoffs', refs=['SW1'],
         highlight=['H1', 'H2', 'H3', 'H4'], extra=[(4, 'M3 standoff + screw, ~22–24 mm')], text="""
1. Screw a standoff into each corner hole (**H1–H4**).
2. Put the switch's 6 pins through **SW1**. Pin 1 of the switch goes in the **square pad**
   (bottom right).
3. Solder all 6 pins, even the unused ones: they hold the switch.
4. **Test** with the meter on the bottom row of SW1 pads, from the middle pad to the left
   pad: open when released, closed when pressed. If it's the other way round, the switch is
   turned the wrong way.

*Tip:* for a perfect fit, mount the switch and standoffs in the top panel first, lay the
board on them, and solder the switch in place.

The footswitch has no 3D model, so the picture shows only its pads.
"""),
    dict(slug='chips', title='Chips', refs=[], chips=['U1', 'U2'], text="""
1. Bend the chip legs slightly inwards on a table so they fit the socket.
2. **74HC165 → U1** (left), **74HC595 → U2** (right). Notch **up**, matching the socket.
3. Press in firmly. Check that no leg folded under.

Both chips run at 3.3 V, but they do different jobs: don't swap them.
"""),
]

# Footprints that are not fitted in any step (only highlighted, or nothing to fit).
NOT_IN_STEPS = {'H1', 'H2', 'H3', 'H4'}

# Facts the step texts rely on: ref -> footprint rotation in degrees.
CHECKS = {
    'SW1': 180,                         # pin 1 square pad bottom right; test pads on bottom row
    'D1': 0,                            # square pad (red) on the left
    'C4': 0,                            # + pad on the left
    'Q1': 0, 'Q2': 0, 'Q3': 0,          # flat side down
    'U1': 0, 'U2': 0,                   # notch up
    'J1': 0, 'J2': 0,                   # notch on the left
    'U3': -90,                          # USB to the right
}
# Facts the step texts rely on: refs that must sit left-to-right in this order, same row.
ROW_CHECKS = [['R1', 'R2', 'R3', 'R8', 'R7', 'R6', 'R5'], ['U1', 'D1', 'C4', 'U2'],
              ['J2', 'U1'], ['U2', 'J1']]

# ------------------------------------------------------------------------------- the board
class Board:
    def __init__(self, path):
        self.path = Path(path)
        self.tree = sx.parse(self.path.read_text())
        self.fps = {}
        for f in find(self.tree, 'footprint'):
            props = {p[1]: p[2] for p in find(f, 'property')}
            at = find1(f, 'at')
            self.fps[props['Reference']] = dict(
                value=props.get('Value', ''), lib=f[1], x=float(at[1]), y=float(at[2]),
                rot=float(at[3]) if len(at) > 3 else 0.0)

    def variant(self, fitted, present, chips=()):
        """Board text with only `present` footprints, and 3D models only for `fitted` ones."""
        t = copy.deepcopy(self.tree)
        out = [t[0]]
        for e in t[1:]:
            if isinstance(e, list) and e and e[0] == 'footprint':
                ref = next(p[2] for p in find(e, 'property') if p[1] == 'Reference')
                if ref not in present:
                    continue
                for m in find(e, 'model'):
                    if ref not in fitted:
                        h = find1(m, 'hide')
                        if h: h[1:] = [Sym('yes')]
                        else: m.insert(2, [Sym('hide'), Sym('yes')])
                if ref in chips:
                    sock = next(m for m in find(e, 'model') if not find1(m, 'hide'))
                    chip = copy.deepcopy(sock)
                    chip[1] = CHIP_MODEL
                    find1(find1(chip, 'offset'), 'xyz')[3] = CHIP_Z
                    e.append(chip)
            out.append(e)
        return sx.dump(out) + '\n'


def check(board):
    errs = []
    step_refs = [r for s in STEPS for r in s['refs']]
    for r in sorted(set(step_refs)):
        if step_refs.count(r) > 1: errs.append(f'{r} is fitted in more than one step')
    used = set(step_refs) | {r for s in STEPS for r in s.get('highlight', []) + s.get('chips', [])}
    for r in sorted(used - set(board.fps)):
        errs.append(f'{r} is in STEPS but not on the board')
    for r in sorted(set(board.fps) - set(step_refs) - NOT_IN_STEPS):
        errs.append(f'{r} ({board.fps[r]["value"]}) is on the board but in no step')
    for r, rot in CHECKS.items():
        if r in board.fps and (board.fps[r]['rot'] - rot) % 360:
            errs.append(f'{r} is rotated {board.fps[r]["rot"]:g}°, the text assumes {rot}°')
    for row in ROW_CHECKS:
        xs = [board.fps[r]['x'] for r in row if r in board.fps]
        if xs != sorted(xs):
            errs.append(f'expected left to right: {", ".join(row)}')
    if errs:
        sys.exit('The board no longer matches the step texts:\n  ' + '\n  '.join(errs) +
                 '\nUpdate STEPS / CHECKS in ' + __file__)

# ---------------------------------------------------------------------------- parts tables
DIGITS = ['black', 'brown', 'red', 'orange', 'yellow', 'green', 'blue', 'violet', 'grey', 'white']
MULT = {-2: 'silver', -1: 'gold', **dict(enumerate(DIGITS))}


def ohms(v):
    m = re.fullmatch(r'(\d+)([RkM]?)(\d*)', v.replace('Ω', '').strip())
    if not m: return None
    a, unit, b = m.groups()
    return float(f'{a}.{b or 0}') * {'': 1, 'R': 1, 'k': 1e3, 'M': 1e6}[unit]


def fmt_ohms(r):
    for div, u in ((1e6, 'MΩ'), (1e3, 'kΩ'), (1, 'Ω')):
        if r >= div: return f'{r / div:g} {u}'


def bands(r, n):
    """Colour bands for n significant digits, e.g. 4700 -> yellow-violet-red (n=2)."""
    e = 0
    while round(r / 10 ** e) >= 10 ** n: e += 1
    while round(r / 10 ** e) < 10 ** (n - 1): e -= 1
    digits = str(round(r / 10 ** e))
    return '-'.join([DIGITS[int(d)] for d in digits] + [MULT[e]])


def describe(ref, value):
    p = re.match(r'[A-Z]+', ref).group()
    if p == 'R':
        r = ohms(value)
        return (f'{fmt_ohms(r)} resistor: {bands(r, 2)} (4 bands) or '
                f'{bands(r, 3)} (5 bands)')
    if p == 'C':
        if value.endswith('n') and value[:-1].isdigit():
            pf = int(value[:-1]) * 1000          # marked with 2 digits + number of zeros, in pF
            return f'{value[:-1]} nF ceramic capacitor (marked `{str(pf)[:2]}{len(str(pf)) - 2}`)'
        if value.endswith('u'): return f'{value[:-1]} µF electrolytic capacitor'
    if p == 'Q': return f'{value} NPN transistor, TO-92'
    if p == 'D': return '5 mm RGB LED, 4 leads, **common anode**'
    if p == 'SW': return f'{value} footswitch, momentary'
    if ref in ('J1', 'J2'): return '2×4 shrouded box header'
    if ref == 'J3': return '2×8 pin header'
    if value.startswith('RaspberryPi_Pico'): return 'Raspberry Pi Pico'
    return value


def natural(r):
    m = re.match(r'([A-Z]+)(\d+)', r)
    return (m.group(1), int(m.group(2))) if m else (r, 0)


def ref_list(refs):
    """['R9','R10','R11','R4'] -> 'R4, R9–R11'."""
    refs = sorted(refs, key=natural)
    out, i = [], 0
    while i < len(refs):
        j = i
        while (j + 1 < len(refs) and natural(refs[j + 1])[0] == natural(refs[i])[0]
               and natural(refs[j + 1])[1] == natural(refs[j])[1] + 1):
            j += 1
        out.append(refs[i] if j - i < 2 else f'{refs[i]}–{refs[j]}')
        if j - i == 1: out.append(refs[j])
        i = j + 1
    return ', '.join(out)


def parts_table(board, step):
    groups = {}
    for r in step['refs']:
        groups.setdefault(describe(r, board.fps[r]['value']), []).append(r)
    rows = [(len(rs), d, ref_list(rs)) for d, rs in groups.items()]
    rows.sort(key=lambda row: natural(sorted(groups[row[1]], key=natural)[0]))
    for c in step.get('chips', []):
        rows.append((1, board.fps[c]['value'], c))
    rows += [(q, d, '') for q, d in step.get('extra', [])]
    if not rows: return ''
    s = '| Part | Qty | Where |\n|------|-----|-------|\n'
    return s + ''.join(f'| {d} | {q} | {w} |\n' for q, d, w in rows)

# -------------------------------------------------------------------------------- rendering
class Renderer:
    def __init__(self, board, quality):
        self.board, self.quality = board, quality
        self.tmp = Path(tempfile.mkdtemp(prefix='build-docs-'))
        CACHE.mkdir(parents=True, exist_ok=True)

    def render(self, fitted, present, chips=()):
        text = self.board.variant(fitted, present, chips)
        args = RENDER_ARGS + ['--quality', self.quality]
        key = hashlib.sha1((text + repr(args)).encode()).hexdigest()
        png = CACHE / f'{key}.png'
        if not png.exists():
            pcb = self.tmp / 'board.kicad_pcb'
            pcb.write_text(text)
            res = subprocess.run(['kicad-cli', 'pcb', 'render', str(pcb), '-o', str(png)] + args,
                                 capture_output=True, text=True)
            if res.returncode or not png.exists():
                sys.exit(f'kicad-cli render failed:\n{res.stdout}\n{res.stderr}')
            print('.', end='', flush=True)
        return np.asarray(Image.open(png).convert('RGBA')).astype(np.int16)


def outline(img, before, after, colour):
    """Draw a ring round every region where `before` and `after` differ, on top of img."""
    diff = np.abs(after - before).max(axis=2) > 40
    m = Image.fromarray((diff * 255).astype(np.uint8))
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))   # drop specks
    inner = m.filter(ImageFilter.MaxFilter(17))
    ring = np.asarray(inner.filter(ImageFilter.MaxFilter(7))) > np.asarray(inner)
    out = img.copy()
    out[ring] = (*colour, 255)
    return out


def save(arr, crop, path):
    im = Image.fromarray(arr.clip(0, 255).astype(np.uint8), 'RGBA').crop(crop)
    im = im.resize((OUT_WIDTH, round(im.height * OUT_WIDTH / im.width)), Image.LANCZOS)
    im.save(path, optimize=True)

# ----------------------------------------------------------------------------------- output
def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--board', default=ROOT / 'pcb' / 'footswitch.kicad_pcb')
    ap.add_argument('--quality', default='high', choices=['high', 'basic'])
    ap.add_argument('--no-images', action='store_true', help='only write the text')
    ap.add_argument('--out', default=ROOT / 'docs', help='writes OUT/build.md and OUT/build/')
    a = ap.parse_args()

    board = Board(a.board)
    check(board)
    docs = Path(a.out)
    imgdir = docs / 'build'
    allrefs = set(board.fps)
    main_only = {r for s in STEPS if s.get('main_only') for r in s['refs']}

    images = {}         # name -> (fitted, present, chips, highlight refs, colour)
    fitted, chips = set(), set()
    for i, s in enumerate(STEPS, 1):
        new = set(s['refs']) | set(s.get('highlight', [])) | set(s.get('chips', []))
        fitted |= set(s['refs']); chips |= set(s.get('chips', []))
        s['img'] = f'{i:02d}-{s["slug"]}.png'
        images[s['img']] = (set(fitted), allrefs, set(chips), new, NEW_COLOUR)
    images['main-done.png'] = (set(fitted), allrefs, set(chips), set(), None)
    images['extension-done.png'] = (fitted - main_only, allrefs, set(chips), main_only,
                                    EMPTY_COLOUR)

    if not a.no_images:
        r = Renderer(board, a.quality)
        print('rendering', end='', flush=True)
        full = r.render(fitted, allrefs, chips)
        ys, xs = np.nonzero(full[:, :, 3])
        pad = 20
        crop = (max(xs.min() - pad, 0), max(ys.min() - pad, 0),
                min(xs.max() + pad, full.shape[1]), min(ys.max() + pad, full.shape[0]))
        imgdir.mkdir(parents=True, exist_ok=True)
        for name, (fit, present, ch, hl, colour) in images.items():
            after = r.render(fit, present, ch)
            if hl:
                # "before": the highlighted footprints gone entirely (pads, silk and models).
                # For the extension board: the main-only footprints gone, vs. present but empty.
                before = r.render(fit - hl, present - hl, ch - hl)
                after = outline(after, before, after, colour)
            save(after, crop, imgdir / name)
        for f in imgdir.glob('*.png'):
            if f.name not in images: f.unlink()
        shutil.rmtree(r.tmp)
        print(' done')

    write_md(board, docs / 'build.md', main_only)
    print(f'wrote {docs / "build.md"}' + ('' if a.no_images else f' and {len(images)} images'))


def write_md(board, path, main_only):
    md = ['<!-- Generated by pcb/scripts/build_docs.py. Edit that script, not this file. -->',
          '# Build instructions', '', """\
Every board is the same PCB. The **main board** gets a Pico and four extra resistors.
**Extension boards** leave those out.

All parts go on the **top side** (the side with the white labels). Solder on the bottom.
Build from the lowest parts to the tallest, so the board lies flat on its parts while you
solder.

**Board orientation used below:** labels readable, Pico area at the top, footswitch at the
bottom. The pictures look at the board from the bottom edge. In each picture, the parts of
that step are outlined.

## Tools

Soldering iron, solder, side cutters, multimeter. A vise or IDC crimp tool for the cables.

---

## Main board
"""]
    for i, s in enumerate(STEPS, 1):
        md += [f'### Step {i}: {s["title"]}', '']
        t = parts_table(board, s)
        if t: md += [t]
        md += [s['text'].strip(), '', f'![Step {i}](build/{s["img"]})', '']
    md += ['**Main board done.**', '', '![Finished main board](build/main-done.png)', '',
           '---', '', '## Extension board', '']
    skip = [i for i, s in enumerate(STEPS, 1) if s.get('main_only')]
    md += [f'Same PCB, same steps, but **skip steps {", ".join(map(str, skip[:-1]))} and '
           f'{skip[-1]}**. Leave {ref_list(main_only)} empty (outlined below).', '',
           '| Step | Do | Parts |', '|------|----|-------|']
    for i, s in enumerate(STEPS, 1):
        parts = ', '.join(
            [f'{len(rs)} × {d.split(":")[0]}' for d, rs in group(board, s['refs']).items()] +
            [f'{q} × {board.fps[c]["value"]}' for q, c in ((1, c) for c in s.get('chips', []))] +
            [f'{q} × {d}' for q, d in s.get('extra', [])]) or 'none'
        if s.get('main_only'):
            md.append(f'| ~~{i}~~ | ~~{s["title"]}~~ | skip |')
        else:
            md.append(f'| {i} | {s["title"]} | {parts} |')
    md += ['', '![Finished extension board](build/extension-done.png)', '',
           '**Repeat for every extension board.**', '', '---', '', CABLES]
    path.write_text('\n'.join(md))


def group(board, refs):
    g = {}
    for r in refs:
        g.setdefault(describe(r, board.fps[r]['value']), []).append(r)
    return g


CABLES = """\
## Cables and chaining

### Make a ribbon cable

| Part | Qty per cable |
|------|---------------|
| 2×4 IDC socket | 2 |
| 8-way ribbon, OUT-to-IN distance + 2–3 cm slack | 1 |

1. Cut the ribbon square.
2. Lay it in the IDC socket, with the **red wire on the pin 1 side** (marked ▼ on the socket).
3. Squeeze it closed in a vise until flat. Fit the strain-relief clip.
4. Do the same at the other end, **the same way round** (red wire on pin 1 at both ends).

**Repeat:** one cable per extension board.

### Connect

```
[Extension 2] IN ◄──cable── OUT [Extension 1] IN ◄──cable── OUT [Main board]
```

1. Main board **OUT** (J2, left) → first extension board **IN** (J1, right).
2. That board's **OUT** → the next board's **IN**. Repeat.
3. The main board's IN and the last board's OUT stay empty.
4. Plug USB into the Pico. Check J3 on the **last** board: pin 14 to pin 16 ≈ 5 V,
   pin 13 to pin 16 ≈ 3.3 V.
"""

if __name__ == '__main__':
    main()
