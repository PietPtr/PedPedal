"""3D-printable side walls for the plate sandwich, as STLs. Optional: the plates are the same
with or without them.

The walls form a closed frame around the plates. Their profile is stepped (a rebate top and
bottom): the core sits between the plates, and the outer skin runs up past both plate edges,
flush with the front plate's top and the back plate's underside. The plate edges sit in the
rebates, which holds the frame in and out. The frame closes around the plates, so it can't slide
along them either. The plates need no slots or extra holes. Cross-section through the front wall,
outside of the unit on the left:

      skin  core
      ┌──┐
      │  │═══════════  front plate (its edge sits in the top rebate)
      │  ├───┐
      │  │   │        <- inner face, `inset` mm inside the plate edge
      │  │   │           core height = gap between the plates - `height_slack`
      │  ├───┘
      │  │═══════════  back plate
      └──┘

The frame is cut into short pieces at the middle of each gap between two boards, so every piece
fits a small printer: two U-shaped end caps (the right one has the USB cutout for the Pico) and
straight pieces, all the same, for the front and back walls. A 1.75 mm filament pin in each joint
lines up the pieces. Glue is not needed: the plates hold everything.

    uv run --group dev mech/walls.py 4 8   # writes mech/out/walls_N_*.stl, a check render
                                           # walls_N.png and walls_section.png

Print upright, as installed, without supports: the core overhangs the skin by
`inset + edge_clearance` mm at the bottom.
"""
import argparse
import math
import sys
from dataclasses import dataclass, fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plates  # noqa: E402
from plates import Params  # noqa: E402

ROOT = plates.ROOT
PCB = ROOT / 'pcb' / 'footswitch.kicad_pcb'


@dataclass
class WallParams:
    thickness: float = 3.0        # how far the wall sticks out past the plate edge
    inset: float = 3.0            # how far the core reaches in from the plate edge
    edge_clearance: float = 0.2   # gap between the plate edge and the skin, for fit
    height_slack: float = 0.2     # core this much shorter than the gap, so the columns set the
                                  # gap and the plates clamp on them, not on the walls
    pin_diameter: float = 1.9     # hole for a piece of 1.75 mm filament
    pin_depth: float = 6.0        # per side of each joint
    usb_width: float = 14.0       # USB cutout in the right-hand wall, along the wall
    usb_bottom: float = 1.0       # cutout from this height above the PCB top...
    usb_top: float = 20.0         # ...to this one. Covers the Pico soldered straight onto its
                                  # headers (plug at about 1-9 mm) and in sockets (about 9-18 mm)
    bed: float = 200.0            # largest piece the printer takes, either way


# ---------------------------------------------------------------- geometry

def heights(p):
    """z = 0 at the back plate's underside, as in assembly.py."""
    T = p.panel_thickness
    gap = p.pcb_spacer + p.pcb_thickness + p.standoff
    return T, gap, T + p.pcb_spacer + p.pcb_thickness        # plate, gap, PCB top


def cuts(n, p, board):
    """x positions of the joints: the middle of each gap between two boards. One module has no
    gap, so its frame is cut in the middle of the board."""
    if n == 1:
        return [p.margin_left + board['w'] / 2]
    return [p.margin_left + i * p.pitch + board['w'] + (p.pitch - board['w']) / 2 for i in range(n - 1)]


def pins(n, p, w, board, H):
    """Alignment pins: (x, y, z, side) of each pin's centre, two per joint, in the front and back
    walls, a third and two thirds up the core, in the middle of its thickness."""
    T, gap, _ = heights(p)
    yc = (w.thickness - w.inset) / 2                 # middle of the core, from the plate edge out
    return [(x, y, z, side) for x in cuts(n, p, board)
            for y, side in ((-yc, 'front'), (H + yc, 'back'))
            for z in (T + gap / 3, T + 2 * gap / 3)]


def usb_y(p, board, H):
    """The Pico's USB port: on the centre line of the Pico (U3), at the board's right edge."""
    return H - p.margin_top - board['parts']['U3'][1]


def check(n, p, w, board, W, H):
    T, gap, z_pcb = heights(p)
    errors = []
    margin = min(p.margin_left, p.margin_right, p.margin_top, p.margin_bottom)
    if w.inset > margin - 1:
        errors.append(f'the core reaches {w.inset} mm in, but the boards are {margin} mm from the plate '
                      'edge: keep at least 1 mm between them (smaller --inset)')
    if w.inset < 1.5:
        errors.append(f'only {w.inset} mm of plate edge rests on the core: use --inset 1.5 or more')
    if w.thickness - w.edge_clearance < 1.2:
        errors.append(f'skin only {w.thickness - w.edge_clearance:.1f} mm thick: use a larger --thickness')
    core = w.inset + w.thickness
    if w.pin_diameter + 2 * 1.2 > core:
        errors.append(f'pin hole {w.pin_diameter} mm leaves less than 1.2 mm in the {core:.1f} mm wall')
    yu = usb_y(p, board, H)
    if w.usb_top > gap - p.pcb_spacer - p.pcb_thickness - 1:
        errors.append(f'USB cutout reaches {w.usb_top} mm above the PCB, into the front plate')
    if yu - w.usb_width / 2 < 3 or yu + w.usb_width / 2 > H - 3:
        errors.append('USB cutout runs into a corner of the frame')
    xs = [0] + cuts(n, p, board) + [W]
    longest = max(b - a for a, b in zip(xs, xs[1:])) + w.thickness
    depth = H + 2 * w.thickness
    if longest > w.bed or (n > 1 and depth > w.bed):
        errors.append(f'a piece is {max(longest, depth):.0f} mm long, more than the {w.bed:g} mm bed')
    if errors:
        raise SystemExit('\n'.join(['walls: design check failed:'] + errors))
    return [
        f'frame {W + 2 * w.thickness:.1f} x {H + 2 * w.thickness:.1f} x {gap + 2 * T:.1f} mm, '
        f'{w.thickness:g} mm past the plate edges; core {gap - w.height_slack:.1f} mm tall, '
        f'{w.inset:g} mm in from the plate edges ({margin - w.inset:.1f} mm from the boards)',
        f'USB cutout {w.usb_width:g} wide, {w.usb_bottom:g} to {w.usb_top:g} mm above the PCB, '
        f'centred {yu:.1f} mm from the front edge',
    ]


def frame(W, H, p, w):
    """The whole frame in plate coordinates (origin at the plates' bottom-left corner seen from
    above), z = 0 at the back plate's underside."""
    import cadquery as cq

    T, gap, z_pcb = heights(p)
    r = p.corner_radius
    t, c, i = w.thickness, w.edge_clearance, w.inset

    def rrect(off, h, z0):
        """Plate outline grown by `off` (negative: shrunk), extruded from z0 by h."""
        return (cq.Workplane('XY').workplane(offset=z0).sketch()
                .rect(W + 2 * off, H + 2 * off).vertices().fillet(max(r + off, 0.5)).finalize()
                .extrude(h).translate((W / 2, H / 2, 0)))

    skin = rrect(t, gap + 2 * T, 0).cut(rrect(c, gap + 2 * T, 0))
    s = w.height_slack / 2
    core = rrect(t, gap - 2 * s, T + s).cut(rrect(-i, gap - 2 * s, T + s))
    return skin.union(core)


def build(n, p, w, board):
    """Frame pieces in place: list of (name, solid). Names are end_left, end_right, and
    front_k / back_k for the straight pieces (k from the left)."""
    import cadquery as cq

    W, H, *_ = plates.layout(n, p, board)
    T, gap, z_pcb = heights(p)
    t, i = w.thickness, w.inset
    f = frame(W, H, p, w)

    # USB cutout: a box through the right-hand wall
    yu = usb_y(p, board, H)
    zb, zt = z_pcb + w.usb_bottom, z_pcb + w.usb_top
    usb = cq.Workplane('XY').box(i + t + 4, w.usb_width, zt - zb).translate((W + (t - i) / 2, yu, (zb + zt) / 2))
    usb = usb.edges('|X').fillet(min(2.0, w.usb_width / 2 - 0.1, (zt - zb) / 2 - 0.1))
    f = f.cut(usb)

    # Pin holes across each joint
    for x, y, z, _ in pins(n, p, w, board, H):
        f = f.cut(cq.Workplane('YZ').circle(w.pin_diameter / 2).extrude(2 * w.pin_depth)
                  .translate((x - w.pin_depth, y, z)))
    xs = cuts(n, p, board)

    # Cut into pieces with boxes between the joints
    big = H + 4 * t + 20
    bounds = [-t - 5] + xs + [W + t + 5]
    pieces = []
    for k, (a, b) in enumerate(zip(bounds, bounds[1:])):
        box = cq.Workplane('XY').box(b - a, big, gap + 2 * T + 10).translate(((a + b) / 2, H / 2, (gap + 2 * T) / 2))
        part = f.intersect(box)
        solids = part.solids().vals()
        if k == 0:
            pieces.append(('end_left', cq.Workplane().add(solids)))
        elif k == len(bounds) - 2:
            pieces.append(('end_right', cq.Workplane().add(solids)))
        else:
            for s in solids:
                side = 'front' if s.Center().y < H / 2 else 'back'
                pieces.append((f'{side}_{k}', cq.Workplane().add(s)))
    return pieces


# ---------------------------------------------------------------- output

def section(path, p, w):
    """The wall profile with the plate edges, to scale."""
    plt = plates._plt()
    from matplotlib.patches import Polygon, Rectangle

    T, gap, z_pcb = heights(p)
    t, c, i, s = w.thickness, w.edge_clearance, w.inset, w.height_slack / 2
    fig, ax = plt.subplots(figsize=(5, 6), dpi=150)
    # y: distance outward from the plate edge (left of the plot is outside)
    prof = [(t, 0), (c, 0), (c, T + s), (-i, T + s), (-i, T + gap - s), (c, T + gap - s),
            (c, gap + 2 * T), (t, gap + 2 * T)]
    ax.add_patch(Polygon([(-y, z) for y, z in prof], closed=True, fc='#8fb3d9', ec='k', lw=0.8))
    plate = dict(fc='#d9c7a0', ec='k', lw=0.6)
    ax.add_patch(Rectangle((0, 0), 20, T, **plate))
    ax.add_patch(Rectangle((0, T + gap), 20, T, **plate))
    board_y = min(p.margin_left, p.margin_right, p.margin_top, p.margin_bottom)
    ax.add_patch(Rectangle((board_y, z_pcb - p.pcb_thickness), 20 - board_y, p.pcb_thickness,
                           fc='#2e6b3a', ec='k', lw=0.5))
    ax.annotate('front plate', (8, T + gap + T + 1), fontsize=7)
    ax.annotate('back plate', (8, -3), fontsize=7)
    ax.annotate('PCB', (board_y + 6, z_pcb + 1), fontsize=7)
    ax.annotate('outside', (-t - 0.5, gap / 2 + T), fontsize=7, ha='right', va='center', rotation=90)
    ax.annotate(f'core {gap - 2 * s:.1f} mm\n{i:g} mm in', (i + 0.8, T + gap / 2 + 3), fontsize=6)
    ax.set_xlim(-t - 6, 20)
    ax.set_ylim(-6, gap + 2 * T + 6)
    ax.set_aspect('equal')
    ax.set_xlabel('mm from the plate edge (inwards)', fontsize=7)
    ax.set_ylabel('mm from the back plate underside', fontsize=7)
    ax.tick_params(labelsize=6)
    ax.set_title('Wall profile, to scale', fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def render_pieces(path, n, p, board, pieces):
    """The pieces around the back plate, pulled apart a little so the joints show."""
    import cadquery as cq
    import assembly

    W, H, front, back, boards, feet = plates.layout(n, p, board)
    a = assembly.Assy(name='walls')
    a.add(assembly.plate(W, H, back, p), name='back_plate', color=assembly.C_PLATE)
    colours = [cq.Color(0.35, 0.55, 0.80), cq.Color(0.85, 0.55, 0.25)]
    xs = [0] + cuts(n, p, board) + [W]
    for name, part in pieces:
        c = part.val().Center()
        k = next(j for j in range(len(xs) - 1) if xs[j] <= c.x <= xs[j + 1]) if 0 < c.x < W else (0 if c.x <= 0 else len(xs) - 2)
        dx = (k - (len(xs) - 2) / 2) * 8
        dy = 0 if name.startswith('end') else (-8 if name.startswith('front') else 8)
        a.add(part, name=name, color=colours[k % 2], loc=cq.Location((dx, dy, 0)))
    assembly.render(a, path, (-25, 35), zoom=1.6)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', type=int, nargs='+', help='number of modules, one frame per value')
    ap.add_argument('--board', default=PCB)
    ap.add_argument('--out', default=ROOT / 'mech' / 'out', type=Path)
    ap.add_argument('--no-renders', dest='renders', action='store_false', help="don't write the check renders")
    for cls in (Params, WallParams):
        for f in fields(cls):
            ap.add_argument(f'--{f.name.replace("_", "-")}', type=float, default=f.default)
    a = ap.parse_args()
    p = Params(**{f.name: getattr(a, f.name) for f in fields(Params)})
    w = WallParams(**{f.name: getattr(a, f.name) for f in fields(WallParams)})

    import cadquery as cq

    board = plates.read_board(a.board)
    a.out.mkdir(parents=True, exist_ok=True)
    for n in a.modules:
        W, H, *_ = plates.layout(n, p, board)
        notes = check(n, p, w, board, W, H)
        pieces = build(n, p, w, board)
        print(f'{n} modules:')
        for line in notes:
            print('  ' + line)
        # The straight pieces are all the same (a back piece is a front piece turned round), so
        # write one of them and count the rest.
        straight = [pc for name, pc in pieces if not name.startswith('end')]
        kinds = [('end_left', next(pc for nm, pc in pieces if nm == 'end_left'), 1),
                 ('end_right', next(pc for nm, pc in pieces if nm == 'end_right'), 1)]
        if straight:
            kinds.append(('straight', straight[0], len(straight)))
        for name, part, count in kinds:
            bb = part.val().BoundingBox()
            # Upright as installed, moved to the origin
            solid = part.translate((-bb.xmin, -bb.ymin, -bb.zmin))
            stl = a.out / f'walls_{n}_{name}.stl'
            cq.exporters.export(solid, str(stl), tolerance=0.02, angularTolerance=0.1)
            print(f'  wrote {stl}: print {count}, {bb.xlen:.0f} x {bb.ylen:.0f} x {bb.zlen:.1f} mm')
        if straight:
            print(f'  joints: {2 * len(cuts(n, p, board))}, each with 2 pins of 1.75 mm filament, '
                  f'{2 * w.pin_depth - 1:.0f} mm long')
        if a.renders:
            render_pieces(a.out / f'walls_{n}.png', n, p, board, pieces)
    if a.renders:
        section(a.out / 'walls_section.png', p, w)


if __name__ == '__main__':
    main()
