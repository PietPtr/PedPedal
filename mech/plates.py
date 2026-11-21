"""Parametric front and back plates for N footswitch modules, as DXFs for laser cutting.

The enclosure is a sandwich: the front plate (top) and the back plate (bottom), with the sides
open. There are no separate case spacers: each board's four mounting holes carry a column that
runs from plate to plate. A female-female standoff goes from the front plate down to the PCB.
Under the PCB sits a short male-female standoff, stud up: the stud goes through the PCB into
the long standoff and clamps the board. A short screw from underneath holds the back plate to
its female end. Side view, front of
the unit (towards the player) on the left:

                       cap
                       ┌┴┐
    front plate  ═[s]══[nut]═══════(LED)══════[s]═   <- screw heads on top
                   ║   [nut]         │ │       ║
                   ║  ┌─────┐   LED spacer     ║      F-F standoff, PCB to front plate
                   ║  │ sw  │        │ │       ║
    PCB          ══╬══└─────┘══════════════════╬══   <- the short standoff's stud goes through
                   ▓   (leads cut short)       ▓      M-F standoff, stud up, PCB to back plate
    back plate   ═[s]═════════════════════════[s]═   <- screw heads underneath, feet

The switch, LED, mounting-hole and chain-connector positions are read from the board file, so
the plates follow the PCB if parts move. All dimensions are in mm.

    uv run mech/plates.py 4 8    # writes mech/out/{front,back}plate_{4,8}.dxf plus check renders:
                                 #   *_preview.png  plate seen from above, boards and parts in grey
                                 #   *_dxf.png      the DXF file as written
                                 #   side_section.png  one module seen from the side, to scale
"""
import argparse
import math
import sys
from dataclasses import dataclass, fields
from pathlib import Path

import ezdxf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'pcb' / 'scripts'))
import sx  # noqa: E402

HEX_R = 5.5 / math.sqrt(3)       # M3 hex standoff, 5.5 mm across flats: corner radius


@dataclass
class Params:
    # Layout
    pitch: float = 100.0          # switch-to-switch distance
    margin_left: float = 5.0      # plate edge to the outermost board edge
    margin_right: float = 5.0     # module 1 (Pico, USB) is at the right-hand end
    margin_top: float = 5.0       # board top edge is the Pico/USB side (back of the unit)
    margin_bottom: float = 5.0    # board bottom edge is the footswitch side (towards the player)
    corner_radius: float = 4.0

    # Holes (finished sizes, before kerf compensation)
    switch_hole: float = 12.3     # M12x0.75 thread
    led_hole: float = 5.2         # 5 mm LED dome
    screw_hole: float = 3.4       # M3 clearance, both plates, at the board's mounting holes
    foot_inset: float = 8.0       # foot centre to the back plate's front/back edge
    foot_diameter: float = 12.0

    # Laser
    kerf: float = 0.0             # beam width. Many services compensate themselves; then leave 0.

    # Stack-up
    panel_thickness: float = 3.0  # both plates
    standoff: float = 25.0        # F-F standoff, PCB top to front plate underside
    pcb_spacer: float = 5.0       # M-F standoff body, back plate top to PCB underside
    stud: float = 6.0             # its male thread, up through the PCB into the long standoff
    bottom_screw: float = 6.0     # through the back plate into the short standoff's female end
    pcb_thickness: float = 1.6
    switch_body: float = 20.6     # PCB to the switch's shoulder (where the thread starts)
    switch_thread: float = 12.0
    switch_nut: float = 2.2
    switch_washer: float = 0.8
    lead_stub: float = 3.0        # solder joint plus lead under the PCB, with all leads cut short
                                  # (the switch and Pico header pins too)
    under_clearance: float = 1.0  # wanted gap between the lead stubs and the (acrylic) back plate
    led_height: float = 8.6       # 5 mm LED, from the bottom of the flange to the dome tip
    led_proud: float = 0.0        # how far the LED tip sits above the panel top (negative: below)
    # Chain connector with the cable plugged in, worst case: the socket (7.0 mm) resting on top of
    # the 9.1 mm box header shroud, plus the strain-relief clip (3.5 mm). Really the socket sits
    # inside the shroud, a few mm lower.
    connector_height: float = 9.1 + 7.0 + 3.5
    cable_exit: float = 13.0      # where the ribbon leaves the socket, above the PCB (estimate)
    cable_length: float = 94.0    # chain cable, socket centre to socket centre: a 10 cm cable
                                  # measured end to end, minus one 6 mm socket width
    min_clearance: float = 2.0    # wanted gap between any part and a plate


# ---------------------------------------------------------------- read the board

def _find(node, key):
    return [e for e in node if isinstance(e, list) and e and e[0] == key]


def read_board(path):
    """Board outline and part positions in board-local mm (origin top-left, y down)."""
    pcb = sx.parse(Path(path).read_text())
    edge = None
    for r in _find(pcb, 'gr_rect'):
        if _find(r, 'layer')[0][1] == 'Edge.Cuts':
            x0, y0 = map(float, _find(r, 'start')[0][1:3])
            x1, y1 = map(float, _find(r, 'end')[0][1:3])
            edge = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    if edge is None:
        raise SystemExit('no gr_rect on Edge.Cuts in the board')
    ox, oy = edge[0], edge[1]

    parts = {}
    holes = []
    for fp in _find(pcb, 'footprint'):
        name = fp[1]
        at = _find(fp, 'at')[0]
        fx, fy = float(at[1]), float(at[2])
        rot = math.radians(float(at[3])) if len(at) > 3 else 0.0
        ref = next(p[2] for p in _find(fp, 'property') if p[1] == 'Reference')
        if 'MountingHole' in name:
            holes.append((fx - ox, fy - oy))
            continue
        # Body centre: the largest circle on the fab layer (the thread for the switch, the
        # 5 mm body for the LED), else the centre of the pads (the box headers).
        best, cx, cy = -1.0, None, None
        for c in _find(fp, 'fp_circle'):
            if _find(c, 'layer')[0][1] != 'F.Fab':
                continue
            (px, py), (ex, ey) = _find(c, 'center')[0][1:3], _find(c, 'end')[0][1:3]
            r = math.hypot(float(ex) - float(px), float(ey) - float(py))
            if r > best:
                best, cx, cy = r, float(px), float(py)
        if cx is None:
            pads = [tuple(map(float, _find(pd, 'at')[0][1:3])) for pd in _find(fp, 'pad')]
            cx, cy = (sum(c) / len(pads) for c in zip(*pads)) if pads else (0.0, 0.0)
        # KiCad rotates CCW with y pointing down.
        x = fx + cx * math.cos(rot) + cy * math.sin(rot)
        y = fy - cx * math.sin(rot) + cy * math.cos(rot)
        parts[ref] = (x - ox, y - oy)
    return dict(w=edge[2] - edge[0], h=edge[3] - edge[1], parts=parts, holes=sorted(holes))


# ---------------------------------------------------------------- geometry

def layout(n, p, board):
    """Plate size, holes, board rectangles and feet, in plate coordinates (origin bottom-left,
    y up, as in DXF, seen from above). Holes are (x, y, diameter, kind). The back plate gets
    only the mounting-hole columns."""
    W = p.margin_left + (n - 1) * p.pitch + board['w'] + p.margin_right
    H = p.margin_top + board['h'] + p.margin_bottom
    front, back, boards, feet = [], [], [], []
    for i in range(n):
        bx = p.margin_left + i * p.pitch
        by_top = H - p.margin_top                   # board's top edge in plate coordinates
        to_plate = lambda x, y: (bx + x, by_top - y)
        boards.append((bx, by_top - board['h'], board['w'], board['h']))
        sx_, sy_ = to_plate(*board['parts']['SW1'])
        front.append((sx_, sy_, p.switch_hole, 'switch'))
        front.append((*to_plate(*board['parts']['D1']), p.led_hole, 'led'))
        for hx, hy in board['holes']:
            front.append((*to_plate(hx, hy), p.screw_hole, 'screw'))
            back.append((*to_plate(hx, hy), p.screw_hole, 'screw'))
        # Feet: one under each switch at the front edge (straight under the stomp), and one
        # behind it at the back edge, so the unit can't tip when the back edge is stepped on.
        feet += [(sx_, p.foot_inset), (sx_, H - p.foot_inset)]
    return W, H, front, back, boards, feet


def check(n, p, board, W, H, front, back, boards, feet):
    """Fail on geometry that can't be built; return notes on the stack-up."""
    errors = []
    for i, a in enumerate(front):
        if a[0] - a[2] / 2 < 2 or a[0] + a[2] / 2 > W - 2 or a[1] - a[2] / 2 < 2 or a[1] + a[2] / 2 > H - 2:
            errors.append(f'{a[3]} hole at ({a[0]:.1f}, {a[1]:.1f}) is within 2 mm of the plate edge')
        for b in front[i + 1:]:
            web = math.hypot(a[0] - b[0], a[1] - b[1]) - (a[2] + b[2]) / 2
            if web < 2:
                errors.append(f'{a[3]} and {b[3]} holes at ({a[0]:.1f}, {a[1]:.1f}) and '
                              f'({b[0]:.1f}, {b[1]:.1f}) leave only {web:.1f} mm between them')
    for fx, fy in feet:                              # feet must not sit on a screw head
        for x, y, _, _ in back:
            if math.hypot(fx - x, fy - y) < p.foot_diameter / 2 + 5.7 / 2 + 1:
                errors.append(f'foot at ({fx:.1f}, {fy:.1f}) overlaps the screw head at ({x:.1f}, {y:.1f})')

    gap = p.standoff - p.switch_body              # switch shoulder to panel underside
    thread_used = gap + p.panel_thickness + p.switch_washer + p.switch_nut
    if gap < p.switch_nut + p.switch_washer:
        errors.append(f'only {gap:.1f} mm under the panel for the lower switch nut and washer '
                      f'({p.switch_nut + p.switch_washer:.1f} mm): use longer standoffs')
    if thread_used > p.switch_thread:
        errors.append(f'switch thread too short: needs {thread_used:.1f} mm, has {p.switch_thread} mm. '
                      'Use shorter standoffs or a thinner panel')
    if p.connector_height + p.min_clearance > p.standoff:
        errors.append(f'chain connector with cable ({p.connector_height:.1f} mm) leaves less than '
                      f'{p.min_clearance} mm under the front plate ({p.standoff} mm)')
    if p.pcb_spacer - p.lead_stub < p.under_clearance:
        errors.append(f'only {p.pcb_spacer - p.lead_stub:.1f} mm between the cut leads and the back plate: '
                      'use a longer PCB spacer or cut the leads shorter')
    # The stud from below and the top screw from above must not meet inside the long standoff.
    stud_in = p.stud - p.pcb_thickness
    top_in = 5.0
    if stud_in + top_in > p.standoff - 1:
        errors.append(f'stud ({stud_in:.1f} mm) and top screw ({top_in:.1f} mm) meet inside the '
                      f'{p.standoff} mm standoff')
    # The short standoff's female hole is at most as deep as its body.
    screw_in = p.bottom_screw - p.panel_thickness
    if screw_in > p.pcb_spacer - 0.5:
        errors.append(f'bottom screw ({screw_in:.1f} mm in) may bottom out in the {p.pcb_spacer} mm '
                      'standoff before it clamps: use a shorter screw')
    if screw_in < 1.5:
        errors.append(f'bottom screw goes only {screw_in:.1f} mm into the short standoff: use a longer one')
    if errors:
        raise SystemExit('\n'.join(['plates: design check failed:'] + errors))

    # Chain cable: from OUT (J2) of one module to IN (J1) of the next module, one pitch to the
    # left. Both headers sit side by side at the top left, OUT left of IN, so the ribbon runs
    # along the top edge, over the next module's (empty) Pico area, nearly straight.
    j1, j2 = board['parts']['J1'], board['parts']['J2']
    span = p.pitch + j2[0] - j1[0]
    slack = p.cable_length - span
    if slack < 0:
        raise SystemExit(f'plates: design check failed:\nchain cable too short: the sockets are {span:.0f} mm '
                         f'apart, the cable spans {p.cable_length:.0f} mm')
    cable = (f'{slack:.0f} mm of slack, which sags a little between the sockets. '
             f'Cables from {span:.0f} to about {span + 15:.0f} mm (centre to centre) fit')

    led_spacer = p.standoff + p.panel_thickness + p.led_proud - p.led_height
    height = 2 * p.panel_thickness + p.pcb_spacer + p.pcb_thickness + p.standoff
    return [
        f'plates {W:.1f} x {H:.1f} mm, {p.panel_thickness} mm thick, {n} modules at {p.pitch} mm pitch; '
        f'overall height {height:.1f} mm plus feet',
        f'columns (4 per module, {4 * n} in all): M3 female-female standoff {p.standoff:g} mm above the PCB, '
        f'M3 male-female standoff {p.pcb_spacer:g}+{p.stud:g} mm (stud up) below it',
        f'switch: lower nut sits {gap:.1f} mm under the front plate; thread used {thread_used:.1f} of {p.switch_thread} mm',
        f'under the PCB: {p.pcb_spacer:.1f} mm to the back plate; cut all leads to {p.lead_stub:g} mm '
        f'(switch and Pico pins too), leaving {p.pcb_spacer - p.lead_stub:.1f} mm',
        f'stud {stud_in:.1f} mm into the long standoff, top screw {top_in:g} mm; '
        f'bottom screw {screw_in:.1f} mm into the short one',
        f'chain connector + cable: at most {p.connector_height:.1f} mm, '
        f'{p.standoff - p.connector_height:.1f} mm under the front plate',
        f'chain cable: {span:.0f} mm between sockets, {p.cable_length:.0f} mm cable; {cable}',
        f'LED spacer: {led_spacer:.1f} mm puts the LED tip {p.led_proud:+.1f} mm from the front plate top',
        f'screws: M3 x {p.panel_thickness + 5:.0f} mm through the front plate into each standoff, '
        f'M3 x {p.bottom_screw:g} mm up through the back plate into each short standoff',
        f'feet: {len(feet)} stick-on rubber feet, {p.foot_diameter:g} mm, under the back plate',
    ]


# ---------------------------------------------------------------- output

def rounded_rect(msp, x0, y0, w, h, r, layer):
    """Closed polyline with arc corners (bulge 0.4142 = tan(90°/4))."""
    b = math.tan(math.radians(90) / 4)
    pts = [(r, 0, 0), (w - r, 0, b), (w, r, 0), (w, h - r, b), (w - r, h, 0), (r, h, b), (0, h - r, 0), (0, r, b)]
    msp.add_lwpolyline([(x0 + x, y0 + y, bb) for x, y, bb in pts], format='xyb', close=True,
                       dxfattribs={'layer': layer})


def write_dxf(path, p, W, H, holes):
    doc = ezdxf.new('R2000', setup=False)
    doc.units = ezdxf.units.MM
    doc.header['$MEASUREMENT'] = 1
    doc.layers.add('CUT', color=1)                # red: cut through
    msp = doc.modelspace()
    k = p.kerf / 2
    # The beam removes k on each side of the line: move the outline out and the holes in.
    rounded_rect(msp, -k, -k, W + 2 * k, H + 2 * k, p.corner_radius + k, 'CUT')
    for x, y, d, _ in holes:
        msp.add_circle((x, y), d / 2 - k, dxfattribs={'layer': 'CUT'})
    doc.saveas(path)


def _plt():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    return plt


def preview(path, title, p, W, H, holes, boards, feet=()):
    """A plate seen from above, with the boards and the parts between the plates in grey."""
    plt = _plt()
    from matplotlib.patches import Circle, FancyBboxPatch, Rectangle, RegularPolygon

    fig, ax = plt.subplots(figsize=(max(6, W / 40), max(3, H / 40)), dpi=150)
    grey = dict(fill=False, ec='0.6', lw=0.6)
    for bx, by, bw, bh in boards:
        ax.add_patch(Rectangle((bx, by), bw, bh, **grey))
    for x, y, d, kind in holes:
        if kind == 'switch':      # body under the panel, and the nut (14 mm across flats)
            ax.add_patch(Rectangle((x - 17.4 / 2, y - 14.3 / 2), 17.4, 14.3, ls='--', **grey))
            ax.add_patch(RegularPolygon((x, y), 6, radius=14 / math.sqrt(3), **grey))
        if kind == 'screw':
            ax.add_patch(RegularPolygon((x, y), 6, radius=HEX_R, orientation=math.pi / 6, **grey))
    for x, y in feet:            # under the plate
        ax.add_patch(Circle((x, y), p.foot_diameter / 2, ls=':', **grey))
    ax.add_patch(FancyBboxPatch((0, 0), W, H, boxstyle=f'round,pad=0,rounding_size={p.corner_radius}',
                                fill=False, ec='C3', lw=1))
    for x, y, d, _ in holes:
        ax.add_patch(Circle((x, y), d / 2, fill=False, ec='C3', lw=1))
    ax.set_xlim(-5, W + 5)
    ax.set_ylim(-5, H + 5)
    ax.set_aspect('equal')
    ax.set_title(f'{title}: {W:.0f} x {H:.0f} mm, seen from above (red: cut, grey: boards and parts)',
                 fontsize=8)
    ax.tick_params(labelsize=6)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def side_section(path, p, board, H):
    """One module seen from the side, to scale. Front of the unit on the left.
    z = 0 is the front plate's underside, z goes up."""
    plt = _plt()
    from matplotlib.patches import Rectangle

    fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
    T = p.panel_thickness
    y_pcb0 = p.margin_bottom                     # board's front edge, from the plate's front edge
    to_y = lambda by: p.margin_bottom + board['h'] - by       # board-local y (down) -> from front
    z_pcb = -p.standoff                          # PCB top
    z_back = z_pcb - p.pcb_thickness - p.pcb_spacer     # back plate top

    def box(y0, z0, w, h, **kw):
        ax.add_patch(Rectangle((y0, z0), w, h, **kw))

    plate = dict(fc='#d9c7a0', ec='k', lw=0.6)
    metal = dict(fc='0.75', ec='k', lw=0.5)
    dark = dict(fc='0.15', ec='k', lw=0.5)
    box(0, 0, H, T, **plate)
    box(0, z_back - T, H, T, **plate)
    box(y_pcb0, z_pcb - p.pcb_thickness, board['h'], p.pcb_thickness, fc='#2e6b3a', ec='k', lw=0.5)
    # columns at the board's front and back hole rows: standoff above the PCB, spacer below
    for by in sorted({hy for _, hy in board['holes']}):
        box(to_y(by) - 2.75, z_pcb, 5.5, p.standoff, **metal)
        box(to_y(by) - 2.75, z_back, 5.5, p.pcb_spacer, **metal)
    # feet
    for yc in (p.foot_inset, H - p.foot_inset):
        box(yc - p.foot_diameter / 2, z_back - T - 4, p.foot_diameter, 4, fc='0.25', ec='k', lw=0.5)
    # switch: body, pins, lower nut, bushing, top nut, plunger and cap
    ys = to_y(board['parts']['SW1'][1])
    box(ys - 14.3 / 2, z_pcb, 14.3, p.switch_body, **dark)
    for dy in (-4.65 / 2, 4.65 / 2):                 # pins, cut short under the PCB
        box(ys + dy - 0.4, z_pcb - p.pcb_thickness - p.lead_stub, 0.8, p.lead_stub + p.pcb_thickness, **metal)
    z_sh = z_pcb + p.switch_body
    box(ys - 6, z_sh, 12, p.switch_thread, **metal)
    box(ys - 8, -p.switch_nut - p.switch_washer, 16, p.switch_nut + p.switch_washer, fc='0.55', ec='k', lw=0.5)
    box(ys - 8, T, 16, p.switch_washer + p.switch_nut, fc='0.55', ec='k', lw=0.5)
    box(ys - 4, z_sh + p.switch_thread, 8, 5, **metal)
    box(ys - 5, z_sh + p.switch_thread + 5, 10, 5, **metal)
    # LED on its spacer
    yl = to_y(board['parts']['D1'][1])
    led_spacer = p.standoff + T + p.led_proud - p.led_height
    box(yl - 3, z_pcb, 6, led_spacer, fc='0.9', ec='k', lw=0.5)
    box(yl - 2.5, z_pcb + led_spacer, 5, p.led_height, fc='#d33', ec='k', lw=0.5)
    # chain connector (worst-case height) and the cable leaving sideways
    yj = to_y(board['parts']['J2'][1])
    box(yj - 9, z_pcb, 18, 9.1, **dark)
    box(yj - 7.5, z_pcb + 9.1 + 0.01, 15, p.connector_height - 9.1, fc='0.4', ec='k', lw=0.5, ls='--')
    ax.annotate('chain connector + cable\n(worst case; ribbon runs\nout of the page)', (yj + 9, z_pcb + 15),
                fontsize=6, ha='left')
    yb = max(to_y(hy) for _, hy in board['holes'])
    ax.annotate(f'F-F standoff {p.standoff:g}', (yb + 3.5, z_pcb + 3), fontsize=6)
    ax.annotate(f'M-F {p.pcb_spacer:g}+{p.stud:g}', (yb + 3.5, z_back), fontsize=6)
    ax.annotate(f'LED spacer {led_spacer:.1f}', (yb + 3.5, z_pcb + 10), fontsize=6)
    ax.annotate('front', (1, z_back - T - 9), fontsize=7)
    ax.annotate('back', (H - 10, z_back - T - 9), fontsize=7)
    ax.set_xlim(-5, H + 5)
    ax.set_ylim(z_back - T - 12, T + p.switch_washer + p.switch_nut + 20)
    ax.set_aspect('equal')
    ax.set_xlabel('mm from the front edge', fontsize=7)
    ax.set_ylabel('mm from the front plate underside', fontsize=7)
    ax.tick_params(labelsize=6)
    ax.set_title('Side view of one module, to scale (parts at different depths overlap)', fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def render_dxf(dxf, png):
    """Draw the DXF as written, read back with ezdxf, to check the file rather than the script."""
    from ezdxf.addons.drawing import matplotlib as dxfplot
    dxfplot.qsave(ezdxf.readfile(dxf).modelspace(), str(png), bg='#FFFFFF', dpi=150)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', type=int, nargs='+', help='number of modules, one pair of plates per value')
    ap.add_argument('--board', default=ROOT / 'pcb' / 'footswitch.kicad_pcb')
    ap.add_argument('--out', default=ROOT / 'mech' / 'out', type=Path)
    ap.add_argument('--no-renders', dest='renders', action='store_false', help="don't write the check renders")
    for f in fields(Params):
        ap.add_argument(f'--{f.name.replace("_", "-")}', type=float, default=f.default)
    a = ap.parse_args()
    p = Params(**{f.name: getattr(a, f.name) for f in fields(Params)})

    board = read_board(a.board)
    a.out.mkdir(parents=True, exist_ok=True)
    for n in a.modules:
        W, H, front, back, boards, feet = layout(n, p, board)
        notes = check(n, p, board, W, H, front, back, boards, feet)
        print(f'{n} modules:')
        for line in notes:
            print('  ' + line)
        for name, holes in (('frontplate', front), ('backplate', back)):
            dxf = a.out / f'{name}_{n}.dxf'
            write_dxf(dxf, p, W, H, holes)
            print(f'  wrote {dxf}')
            if a.renders:
                title = f'{"Front" if name == "frontplate" else "Back"} plate, {n} modules'
                preview(a.out / f'{name}_{n}_preview.png', title, p, W, H, holes, boards,
                        feet if name == 'backplate' else ())
                render_dxf(dxf, a.out / f'{name}_{n}_dxf.png')
    if a.renders:
        side_section(a.out / 'side_section.png', p, board, H)


if __name__ == '__main__':
    main()
