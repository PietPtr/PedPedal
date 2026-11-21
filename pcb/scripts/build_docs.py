#!/usr/bin/env python3
"""Generate the build instructions, docs/build.md, and their images in docs/build/.

    uv run pcb/scripts/build_docs.py [--board pcb/footswitch.kicad_pcb] [--quality high|basic]
                                   [--no-images] [--pdf]

The last section, the mechanical assembly, takes its texts from mech/assembly_steps.py; its
pictures are made by that script (uv run --group dev mech/assembly_steps.py).

The step texts live in STEPS below. Everything else comes from the board:
- Parts tables: values and refs are read from the footprints, and resistor colour codes are
  worked out from the values.
- Images: for each step, the board is copied with the 3D models of parts not yet fitted
  hidden, then rendered with kicad-cli. The new parts are outlined: the step is also rendered
  without them, and the pixels that changed are outlined. That comparison uses basic-quality
renders, which have no shadows.

Edit this script, not docs/build.md: the next run overwrites it.

The texts describe positions and orientations ("flat side down", "+ on the left"). Those
facts are checked against the board in CHECKS. If the layout changes, the run fails until
the text and CHECKS are brought up to date. Every footprint must belong to a step (or to
NOT_IN_STEPS), so a new part can't be left out of the instructions without notice.

Renders are cached in ~/.cache/footswitch-build-docs, keyed on the board variant and render
settings, so a run where only the text changed re-renders nothing. The finished images
(outlined, cropped, encoded) are cached there too, keyed on the renders they are made from and
on the code that makes them, so an unchanged image is just copied.
"""
import argparse, copy, hashlib, inspect, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sx
from sx import Sym, find, find1

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'footswitch-build-docs'

# Camera: tilted towards the viewer, as if looking at the board on the bench from the front.
RENDER_ARGS = ['--preset', 'follow_pcb_editor', '--width', '1600', '--height', '1300', '--rotate', '-35,0,0', '--perspective',
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
# ext_refs:  footprints fitted in this step on extension boards only (left empty on the main board).
STEPS = [
    dict(slug='10k', title='10 kΩ resistors, left bank', refs=['R4', 'R9'], text="""
1. Bend the leads and push the resistors into both positions of the **left resistor bank**,
   left of the footswitch.
2. Solder. Cut the leads.

They are the same value, and direction doesn't matter.
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
1. Fit **R5–R8**, the four resistors lying flat under the `J2 OUT` / `J1 IN` labels, next to
   the Pico.
2. Solder. Cut the leads.

They are all the same value, and direction doesn't matter.
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
    dict(slug='headers', title='Chain connector', refs=['J2'], ext_refs=['J1'], text="""
1. Fit **J2** (`OUT`, top-left corner) with the **notch** in the shroud on the **left**,
   matching the outline.
2. Solder one pin, check that it sits flat and straight, then solder the rest.

The main board gets **no J1** (`IN`, right of J2; outlined in orange): leave it empty. The
Pico drives those lines, so nothing plugs in there. Extension boards get both headers, the
same way round.
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
         highlight=['J2'], text="""
1. Plug USB into the Pico. No chips are fitted yet.
2. Measure on **J2** (`OUT`; pin 1 is the square pad, top left, and pin 2 is next to it):
   - pin 1 to pin 2: about **5 V**
   - pin 3 to pin 2: about **3.3 V**
3. Unplug USB.

If either is wrong, stop and look for solder bridges.
"""),
    dict(slug='led', title='LED', refs=['D1'], extra=[(1, 'LED spacer, 19 mm')], text="""
The LED must be **common anode**.

1. Slide the spacer over the leads.
2. Fit at **D1**: the **red** lead goes in the **square pad** (left), the **longest lead**
   (common anode) in the **second** hole. The holes are staggered, so bend the leads slightly
   to fit.
3. Push the spacer down to the board, check that the LED stands straight, solder, and cut the
   leads.
"""),
    dict(slug='footswitch', title='Footswitch', refs=['SW1'], text="""
1. Put the switch's 6 pins through **SW1**. Pin 1 of the switch goes in the **square pad**
   (bottom right).
2. Solder all 6 pins, even the unused ones: they hold the switch. Cut the pins to 3 mm or
   less: the back plate sits close under the board.
3. **Test** with the meter on the bottom row of SW1 pads, from the middle pad to the left
   pad: open when released, closed when pressed. If it's the other way round, the switch is
   turned the wrong way.

*Tip:* for a perfect fit, screw the 25 mm standoffs to the front plate and nut the switch in
first, lay the board on them, screw the short standoffs up through it (mechanical step M2),
and only then solder the switch.
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
ROW_CHECKS = [['R4', 'R9', 'SW1', 'R1', 'R2', 'R3'], ['U1', 'D1', 'C4', 'U2'],
              ['J2', 'J1', 'U3']]

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
        # The render runs from a temp dir, so point project-relative models at the project.
        return sx.dump(out).replace('${KIPRJMOD}', str(self.path.resolve().parent)) + '\n'

    def project_models(self, text):
        """Contents hash of the project's own 3D models used in `text`, for the cache key."""
        h = hashlib.sha1()
        d = str(self.path.resolve().parent)
        for f in sorted(set(re.findall(r'\(model "(' + re.escape(d) + r'/[^"]+)"', text))):
            if os.path.exists(f): h.update(Path(f).read_bytes())
        return h.hexdigest()


def check(board):
    errs = []
    step_refs = [r for s in STEPS for r in s['refs'] + s.get('ext_refs', [])]
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
        self.keys = {}

    def key(self, fitted, present, chips=(), quality=None):
        """Cache key of a render, and the board text it needs (memoised)."""
        args = RENDER_ARGS + ['--quality', quality or self.quality]
        k = (frozenset(fitted), frozenset(present), frozenset(chips), tuple(args))
        if k not in self.keys:
            text = self.board.variant(fitted, present, chips)
            h = hashlib.sha1((text + repr(args) + self.board.project_models(text)).encode())
            self.keys[k] = (h.hexdigest(), text, args)
        return self.keys[k]

    def render(self, fitted, present, chips=(), quality=None):
        key, text, args = self.key(fitted, present, chips, quality)
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
    m = m.filter(ImageFilter.MaxFilter(25)).filter(ImageFilter.MinFilter(13))  # grow, close gaps
    ImageDraw.floodfill(m, (0, 0), 128)                  # outside; whatever stays 0 is a hole
    m = Image.fromarray(np.where(np.asarray(m) == 128, 0, 255).astype(np.uint8))
    ring = np.asarray(m.filter(ImageFilter.MaxFilter(7))) > np.asarray(m)
    out = img.copy()
    out[ring] = (*colour, 255)
    return out


def save(arr, crop, path):
    im = Image.fromarray(arr.clip(0, 255).astype(np.uint8), 'RGBA').crop(crop)
    im = im.resize((OUT_WIDTH, round(im.height * OUT_WIDTH / im.width)), Image.LANCZOS)
    im.save(path, quality=88, method=6)

# ----------------------------------------------------------------------------------- output
def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--board', default=ROOT / 'pcb' / 'footswitch.kicad_pcb')
    ap.add_argument('--quality', default='high', choices=['high', 'basic'])
    ap.add_argument('--no-images', action='store_true', help='only write the text')
    ap.add_argument('--pdf', action='store_true', help='also write OUT/build.pdf (needs Chrome)')
    ap.add_argument('--out', default=ROOT / 'docs', help='writes OUT/build.md and OUT/build/')
    a = ap.parse_args()

    board = Board(a.board)
    check(board)
    docs = Path(a.out)
    docs.mkdir(parents=True, exist_ok=True)
    imgdir = docs / 'build'
    allrefs = set(board.fps)
    main_only = {r for s in STEPS if s.get('main_only') for r in s['refs']}
    ext_only = {r for s in STEPS for r in s.get('ext_refs', [])}

    # name -> (fitted, present, chips, [(outlined refs, colour), ...]). The step pictures show
    # the main board: the extension-only positions stay empty, outlined when they come up.
    images = {}
    fitted, chips = set(), set()
    for i, s in enumerate(STEPS, 1):
        new = set(s['refs']) | set(s.get('highlight', [])) | set(s.get('chips', []))
        fitted |= set(s['refs']); chips |= set(s.get('chips', []))
        s['img'] = f'{i:02d}-{s["slug"]}.webp'
        marks = [(new, NEW_COLOUR)] + ([(set(s['ext_refs']), EMPTY_COLOUR)] if s.get('ext_refs') else [])
        images[s['img']] = (set(fitted), allrefs, set(chips), marks)
    images['main-done.webp'] = (set(fitted), allrefs, set(chips), [(ext_only, EMPTY_COLOUR)])
    images['extension-done.webp'] = ((fitted - main_only) | ext_only, allrefs, set(chips),
                                     [(main_only, EMPTY_COLOUR)])

    if not a.no_images:
        r = Renderer(board, a.quality)
        print('rendering', end='', flush=True)
        full_key = r.key(fitted | ext_only, allrefs, chips)[0]
        crop = None
        # Everything that shapes a finished image besides its renders.
        code = hashlib.sha1((inspect.getsource(outline) + inspect.getsource(save) +
                             repr((OUT_WIDTH, NEW_COLOUR, EMPTY_COLOUR))).encode()).hexdigest()
        imgdir.mkdir(parents=True, exist_ok=True)
        for name, (fit, present, ch, marks) in images.items():
            parts = [code, full_key, r.key(fit, present, ch)[0]]
            for hl, colour in marks:
                if hl:
                    parts += [repr(colour), r.key(fit - hl, present - hl, ch - hl, 'basic')[0],
                              r.key(fit, present, ch, 'basic')[0]]
            cached = CACHE / (hashlib.sha1(' '.join(parts).encode()).hexdigest() + '.webp')
            if cached.exists():
                shutil.copyfile(cached, imgdir / name)
                continue
            if crop is None:
                full = r.render(fitted | ext_only, allrefs, chips)
                ys, xs = np.nonzero(full[:, :, 3])
                pad = 20
                crop = (max(xs.min() - pad, 0), max(ys.min() - pad, 0),
                        min(xs.max() + pad, full.shape[1]), min(ys.max() + pad, full.shape[0]))
            after = r.render(fit, present, ch)
            for hl, colour in marks:
                if not hl: continue
                # "before": the outlined footprints gone entirely (pads, silk and models).
                # For empty positions: the footprints gone, vs. present but empty.
                # The diff uses basic renders: they have no shadows, which would also change.
                before = r.render(fit - hl, present - hl, ch - hl, quality='basic')
                after = outline(after, before, r.render(fit, present, ch, quality='basic'), colour)
            save(after, crop, cached)
            shutil.copyfile(cached, imgdir / name)
        for f in [*imgdir.glob('*.webp'), *imgdir.glob('*.png')]:
            if f.name not in images: f.unlink()
        shutil.rmtree(r.tmp)
        print(' done')

    write_md(board, docs / 'build.md', main_only, ext_only)
    print(f'wrote {docs / "build.md"}' + ('' if a.no_images else f' and {len(images)} images'))
    if a.pdf:
        write_pdf(docs / 'build.md', docs / 'build.pdf')
        print(f'wrote {docs / "build.pdf"}')


PDF_CSS = """
@page { size: A4; margin: 15mm 15mm 18mm; }
body { font: 10.5pt/1.45 "DejaVu Sans", sans-serif; color: #222; }
h1 { font-size: 20pt; margin: 0 0 8pt; }
h2 { font-size: 15pt; break-before: page; border-bottom: 1px solid #ccc; padding-bottom: 3pt; }
h2:first-of-type { break-before: auto; }
h3 { font-size: 12.5pt; break-before: page; margin-top: 0; }
h2 + h3 { break-before: auto; }
table { border-collapse: collapse; margin: 6pt 0 10pt; font-size: 9.5pt; }
th, td { border: 1px solid #ccc; padding: 3pt 6pt; text-align: left; }
th { background: #f2f2f2; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 9pt; }
pre { background: #f6f6f6; padding: 6pt; font-size: 8.5pt; white-space: pre-wrap; }
img { display: block; max-width: 100%; max-height: 135mm; margin: 8pt auto; }
hr { display: none; }
"""


def write_pdf(md_path, pdf_path):
    """Markdown -> HTML (python-markdown) -> PDF (headless Chrome's print)."""
    import markdown
    text = re.sub(r'~~(.+?)~~', r'<del>\1</del>', md_path.read_text())   # not in python-markdown
    body = markdown.markdown(text, extensions=['tables', 'fenced_code'])
    html = md_path.with_name('.build-pdf.html')         # next to build.md, so image paths work
    html.write_text(f'<!doctype html><meta charset="utf-8"><title>Build instructions</title>'
                    f'<style>{PDF_CSS}</style>{body}')
    chrome = next((c for c in ('google-chrome', 'chromium', 'chromium-browser')
                   if shutil.which(c)), None)
    if not chrome: sys.exit('no Chrome or Chromium found for --pdf')
    try:
        subprocess.run([chrome, '--headless', '--disable-gpu', '--no-pdf-header-footer',
                        f'--print-to-pdf={pdf_path}', html.as_uri()],
                       check=True, capture_output=True)
    finally:
        html.unlink()


def write_md(board, path, main_only, ext_only):
    md = ['<!-- Generated by pcb/scripts/build_docs.py. Edit that script, not this file. -->',
          '# Build instructions', '', """\
Every board is the same PCB. The **main board** gets a Pico and four extra resistors, and
only one of the two chain connectors. **Extension boards** get both connectors, but no Pico.

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
    md += ['**Main board done.**', '', f'{ref_list(ext_only)} stays empty (outlined).', '',
           '![Finished main board](build/main-done.webp)', '',
           '---', '', '## Extension board', '']
    skip = [i for i, s in enumerate(STEPS, 1) if s.get('main_only')]
    md += [f'Same PCB, same steps, but **skip steps {", ".join(map(str, skip[:-1]))} and '
           f'{skip[-1]}**. Leave {ref_list(main_only)} empty (outlined below), but do fit '
           f'{ref_list(ext_only)}.', '',
           '| Step | Do | Parts |', '|------|----|-------|']
    for i, s in enumerate(STEPS, 1):
        parts = ', '.join(
            [f'{len(rs)} × {d.split(":")[0]}'
             for d, rs in group(board, s['refs'] + s.get('ext_refs', [])).items()] +
            [f'{q} × {board.fps[c]["value"]}' for q, c in ((1, c) for c in s.get('chips', []))] +
            [f'{q} × {d}' for q, d in s.get('extra', [])]) or 'none'
        if s.get('main_only'):
            md.append(f'| ~~{i}~~ | ~~{s["title"]}~~ | skip |')
        else:
            md.append(f'| {i} | {s["title"]} | {parts} |')
    md += ['', '![Finished extension board](build/extension-done.webp)', '',
           '**Repeat for every extension board.**', '', '---', '', CABLES, '---', '']
    md += mechanical()
    path.write_text('\n'.join(md))


def mechanical():
    """The enclosure steps. Texts from mech/assembly_steps.py, which also renders their
    pictures into docs/build/mech/ (run it separately: it needs cadquery)."""
    sys.path.insert(0, str(ROOT / 'mech'))
    import assembly_steps as m
    md = [f'## Mechanical assembly ({m.N} buttons)', '', MECH_INTRO.format(n=m.N, n_ext=m.N - 1)]
    for i, s in enumerate(m.STEPS, 1):
        md += [f'### Step M{i}: {s["title"]}', '']
        if s['parts']:
            md += ['| Part | Qty |', '|------|-----|'] + [f'| {d} | {q} |' for q, d in s['parts']] + ['']
        md += [s['text'].strip(), '']
        for j in range(len(s['views'])):
            md += [f'![Step M{i}](build/mech/{m.image_name(i, s, j)})', '']
    md += ['---', '', '## Side walls (optional)', '', WALLS_INTRO, '']
    for i, s in enumerate(m.WALL_STEPS, 1):
        md += [f'### Step W{i}: {s["title"]}', '']
        if s['parts']:
            md += ['| Part | Qty |', '|------|-----|'] + [f'| {d} | {q} |' for q, d in s['parts']] + ['']
        md += [s['text'].strip(), '']
        for j in range(len(s['views'])):
            md += [f'![Step W{i}](build/mech/{m.image_name(i, s, j, "w")})', '']
    return md


WALLS_INTRO = """\
Printed walls close the open sides. They go on a finished unit, or during the build after
step M5. The plates don't change: the walls hook over the plate edges, and the plates hold
them in place once the front plate is screwed down.

**Printing:** run `uv run --group dev mech/walls.py N` for N buttons and print the STLs from
`mech/out/` upright, as they come, without supports. PETG or PLA, 3 perimeters. The same pieces
fit any number of buttons: two end caps and 2N − 4 straight pieces. Print one end cap first and
try it on the back plate's edge: the plate should drop into the step with a little play.

**Tools:** as above, plus a 2 mm drill bit and side cutters for the pins."""


MECH_INTRO = """\
The unit is a sandwich: the boards sit on the back plate, and the front plate sits on the
standoff columns. The sides stay open, or get the printed walls in the last section. The steps below are for {n} buttons: one main board
and {n_ext} extension boards. For more buttons, use the longer plates and more of the same
hardware per board.

**Orientation:** footswitches towards you, the main board (with the Pico) at the right-hand
end. In each picture, the parts of that step are outlined.

**Tools:** 2 mm hex key (or the driver for your screws), 14 mm spanner.
"""


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
| 8-way ribbon, about 10 cm (OUT to the next IN is 88 mm, centre to centre) | 1 |

1. Cut the ribbon square.
2. Lay it in the IDC socket, with the **red wire on the pin 1 side** (marked ▼ on the socket).
3. Squeeze it closed in a vise until flat. Fit the strain-relief clip.
4. Do the same at the other end, **the same way round** (red wire on pin 1 at both ends).

**Repeat:** one cable per extension board.

### Connect

```
[Extension 2] IN ◄──cable── OUT [Extension 1] IN ◄──cable── OUT [Main board]
```

1. Main board **OUT** (J2, top-left corner) → **IN** (J1, the header right of OUT) of the
   first extension board, to its left. The cable runs straight along the top edge.
2. That board's **OUT** → the next board's **IN**. Repeat.
3. The last board's OUT stays empty. (The main board has no IN.)
4. Plug USB into the Pico. Check J2 (OUT, empty) on the **last** board: pin 1 to pin 2 ≈ 5 V,
   pin 3 to pin 2 ≈ 3.3 V.
"""

if __name__ == '__main__':
    main()
