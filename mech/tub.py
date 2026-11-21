"""Injection-moulded tub: the bottom half of the enclosure, replacing the back plate (and the
printed side walls). The front plate and everything screwed to it (columns, boards, switches)
drop into the tub as one unit, and screws from underneath into the columns hold it in. The
front plate is the same laser-cut plate as before (plates.py); it sits in a rebate round the
top of the tub, flush with the rim.

Cross-section through the front wall at a column, front of the unit on the left (not to scale;
`tub_N_section.png` is):

         lip  rebate
          ┌┐ ┌──────────────────── front plate, top flush with the rim
          ││ │ ══════════════════
          │└─┤ ledge               (plate sits `plate_slack` above it: the columns set the height)
          │  │
          │  │      ║ F-F standoff
          │  │  ════╬═══════════   PCB
          │  │      ▓ M-F standoff
          │  │    ┌─┴─┐            boss
          │  └────┘   └──┬──rib──
          └──────────[screw]─────  floor; the screw head sits in a pocket, below the bottom face
                        ▲

All walls are `wall` mm thick (floor included), with `draft` on every face along the pull
direction, so the tub comes straight out of a two-part tool. The one exception is the USB
opening in the right-hand wall, which needs a side action (slide) in the tool.

    uv run --group dev mech/tub.py 4 8   # writes mech/out/tub_N.step and tub_N.stl, plus check
                                         # renders tub_N_{top,bottom,usb}.png, tub_section.png

z = 0 is the tub's underside. Plate coordinates as in plates.py: origin at the front plate's
bottom-left corner seen from above, y towards the back of the unit.
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
ABS_DENSITY = 1.05       # g/cm³


@dataclass
class TubParams:
    # Walls
    lip: float = 1.5              # wall round the front plate's edge, above the ledge
    plate_clearance: float = 0.2  # plate edge to the lip, per side
    ledge: float = 0.8            # how far the plate edge overlaps the ledge. The wall below the
                                  # ledge is lip + plate_clearance + ledge thick
    floor: float = 2.5
    draft: float = 1.5            # degrees, every face along the pull. 1.5 is enough for a light
                                  # texture (e.g. MT-11010) on the outside; polished could go to 1
    plate_slack: float = 0.3     # ledge this far under the plate, so the columns set the height
    outer_fillet: float = 3.5     # round bottom edge outside (= inner fillet + wall: even wall)
    inner_fillet: float = 1.0     # floor-to-wall corner inside
    rim_fillet: float = 0.5       # outer edge of the rim

    # Columns: boss, screw from underneath into the M-F standoff
    boss_top: float = 6.0         # top of the boss = bottom of the M-F standoff, above z = 0
    boss_diameter: float = 7.5    # M3 hex standoff is 6.35 mm across corners
    boss_hole: float = 3.4
    screw: float = 8.0            # M3 button head (ISO 7380), length under the head
    head_diameter: float = 5.7
    head_height: float = 1.65
    head_inset: float = 0.3       # head this far under the bottom face
    pocket_diameter: float = 6.6

    # Ribs: a grid along the column rows and across at every column and switch
    rib: float = 1.5              # thickness at the root (60 % of the wall, against sink marks)
    rib_top: float = 6.0          # same as the boss top

    # USB opening in the right-hand wall, for the Pico's port: a stadium with a chamfer outside
    usb_hole_width: float = 13.0       # takes the overmould of a USB-C (or micro-USB) cable plug
    usb_hole_height: float = 7.0
    usb_chamfer: float = 0.75
    usb_z: float = 5.1            # port centre above the main PCB's top. Pico soldered on its
                                  # headers: 2.54 header + 1.0 Pico PCB + half the receptacle.
                                  # Pico in female sockets: about 13.5
    usb_face: float = 0.5         # receptacle's mating face, inside the board's right edge
                                  # (KiCad's Pico model)
    plug_reach: float = 6.6       # USB-C plug, metal shell length in front of the overmould

    # Feet: stick-on rubber feet in shallow recesses
    feet_inset: float = 10.0      # foot centre to the front plate's front/back edge
    foot_recess: float = 0.5


# ---------------------------------------------------------------- geometry

def wall(t):
    return t.lip + t.plate_clearance + t.ledge


def heights(p, t):
    """z of the main levels, z = 0 at the tub's underside."""
    z_pcb_bot = t.boss_top + p.pcb_spacer
    z_pcb_top = z_pcb_bot + p.pcb_thickness
    z_plate = z_pcb_top + p.standoff               # front plate underside
    z_top = z_plate + p.panel_thickness            # rim top = front plate top
    z_ledge = z_plate - t.plate_slack
    return dict(pcb_bot=z_pcb_bot, pcb_top=z_pcb_top, plate=z_plate, top=z_top, ledge=z_ledge,
                pocket=t.head_height + t.head_inset)


def tan(t):
    return math.tan(math.radians(t.draft))


def usb_center(n, p, t, board, W, H):
    """(y, z) of the USB opening's centre, and x of the receptacle's mating face."""
    z = heights(p, t)
    bx = p.margin_left + (n - 1) * p.pitch          # module 1, the right-hand board
    x_face = bx + board['w'] - t.usb_face
    y = H - p.margin_top - board['parts']['U3'][1]
    return y, z['pcb_top'] + t.usb_z, x_face


def feet(n, p, t, board, H):
    """Under each switch, near the front and back edges (as on the back plate, a little further
    in, clear of the rounded bottom edge)."""
    xs = [p.margin_left + i * p.pitch + board['parts']['SW1'][0] for i in range(n)]
    return [(x, y) for x in xs for y in (t.feet_inset, H - t.feet_inset)]


def ribs(n, p, board, W, H, columns):
    """Rib centre lines (x0, y0, x1, y1), running wall to wall (clipped to the inside later)."""
    out = []
    for y in sorted({round(y, 3) for _, y, _, _ in columns}):
        out.append((-10, y, W + 10, y))
    xs = {round(x, 3) for x, _, _, _ in columns}
    xs |= {round(p.margin_left + i * p.pitch + board['parts']['SW1'][0], 3) for i in range(n)}
    for x in sorted(xs):
        out.append((x, -10, x, H + 10))
    return out


def check(n, p, t, board, W, H, columns):
    z = heights(p, t)
    errors, notes = [], []
    wl = wall(t)
    if abs(wl - t.floor) > 0.5:
        errors.append(f'wall {wl:.1f} mm and floor {t.floor:.1f} mm differ by more than 0.5 mm: '
                      'uneven sections sink and warp')
    if t.lip < 1.2:
        errors.append(f'lip only {t.lip} mm thick')
    if t.rib > 0.7 * wl:
        errors.append(f'ribs {t.rib} mm thick, more than 70 % of the {wl:.1f} mm wall: they will show as sink marks')
    # Under the PCB: cut leads against the ribs and bosses
    gap = z['pcb_bot'] - p.lead_stub - max(t.rib_top, t.boss_top)
    if gap < p.under_clearance:
        errors.append(f'only {gap:.1f} mm between the cut leads and the ribs/bosses')
    if t.boss_top - t.floor < 1.0:
        errors.append('boss less than 1 mm above the floor')
    # Screw: through the boss into the M-F standoff's female end
    grip = t.boss_top - z['pocket']                  # plastic under the head
    screw_in = t.screw - grip
    if screw_in > p.pcb_spacer - 0.5:
        errors.append(f'screw goes {screw_in:.1f} mm into the {p.pcb_spacer} mm standoff: may bottom out')
    if screw_in < 3.0:
        errors.append(f'screw goes only {screw_in:.1f} mm into the standoff: use a longer one')
    if z['pocket'] > t.floor - 0.4 and t.boss_diameter < t.pocket_diameter + 1:
        errors.append('screw pocket leaves no wall round it')
    if t.pocket_diameter < t.head_diameter + 0.4:
        errors.append('screw pocket too tight for the head')
    # Boards against the drafted inner wall, at the PCB's underside (the wall leans in lower down)
    inner = -t.ledge - (z['ledge'] - z['pcb_bot']) * tan(t)      # inner face, from the plate edge
    margin = min(p.margin_left, p.margin_right, p.margin_top, p.margin_bottom)
    if margin + inner < 1.5:
        errors.append(f'boards only {margin + inner:.1f} mm from the inner wall')
    # Feet: inside the flat part of the bottom, clear of the screw heads
    bottom_out = t.plate_clearance + t.lip - z['top'] * tan(t)      # outer face at z = 0, from the plate edge
    for fx, fy in feet(n, p, t, board, H):
        edge = min(fy, H - fy) + bottom_out - p.foot_diameter / 2
        if edge < t.outer_fillet + 0.5:
            errors.append(f'foot at ({fx:.0f}, {fy:.0f}) runs onto the rounded bottom edge')
        for x, y, _, _ in columns:
            if math.hypot(fx - x, fy - y) < p.foot_diameter / 2 + t.pocket_diameter / 2 + 1:
                errors.append(f'foot at ({fx:.0f}, {fy:.0f}) covers the screw at ({x:.0f}, {y:.0f})')
    # USB opening
    yu, zu, x_face = usb_center(n, p, t, board, W, H)
    if zu + t.usb_hole_height / 2 + t.usb_chamfer > z['ledge'] - 1.5:
        errors.append('USB opening runs into the ledge')
    if zu - t.usb_hole_height / 2 - t.usb_chamfer < t.floor + t.inner_fillet + 1:
        errors.append('USB opening runs into the floor')
    out_face = W + t.plate_clearance + t.lip - (z['top'] - zu) * tan(t)
    reach = out_face - x_face                         # receptacle face to the outside of the wall
    if reach > t.plug_reach + 4:
        errors.append(f'the port is {reach:.1f} mm inside the outer face: the plug overmould would '
                      'have to go more than 4 mm into the case')
    if errors:
        raise SystemExit('\n'.join(['tub: design check failed:'] + errors))

    out_top = t.plate_clearance + t.lip
    notes += [
        f'tub {W + 2 * out_top:.1f} x {H + 2 * out_top:.1f} x {z["top"]:.1f} mm (top of rim), '
        f'wall {wl:.1f} mm, floor {t.floor:.1f} mm, draft {t.draft:g}°',
        f'front plate {W:.0f} x {H:.0f} mm in the rebate, {t.plate_clearance:g} mm clearance; ledge '
        f'{t.ledge:g} mm wide, {t.plate_slack:g} mm under the plate',
        f'columns: boss top {t.boss_top:g} mm, PCB underside {z["pcb_bot"]:.1f} mm, leads clear the '
        f'ribs by {gap:.1f} mm; boards {margin + inner:.1f} mm from the inner wall at the PCB',
        f'screws: {len(columns)} x M3 x {t.screw:g} button head from underneath, head {t.head_inset:g} mm '
        f'under the bottom face, {grip:.2f} mm of plastic clamped, {screw_in:.2f} mm into the M-F standoff',
        f'USB opening {t.usb_hole_width:g} x {t.usb_hole_height:g} mm (stadium, {t.usb_chamfer:g} mm chamfer), '
        f'centre {zu:.1f} mm above the bottom, {yu:.1f} mm from the front plate\'s front edge; '
        f'port face {reach:.1f} mm inside the outer face, so the plug overmould goes '
        f'{max(reach - t.plug_reach, 0):.1f} mm into the opening',
    ]
    return notes


def build(n, p, t, board):
    """The tub as one solid, in plate coordinates."""
    import cadquery as cq

    W, H, front, back, boards, _ = plates.layout(n, p, board)
    z = heights(p, t)
    tn, r = tan(t), p.corner_radius
    columns = back

    def prism(off_top, z0, z1, fillet_bottom=0.0):
        """Plate outline grown by `off_top` at z1, drafted: smaller lower down. z0 to z1."""
        off0 = off_top - (z1 - z0) * tn
        s = (cq.Workplane('XY').workplane(offset=z0).sketch()
             .rect(W + 2 * off0, H + 2 * off0).vertices().fillet(max(r + off0, 0.5)).finalize()
             .extrude(z1 - z0, taper=-t.draft).translate((W / 2, H / 2, 0)))
        if fillet_bottom:
            s = s.edges('<Z').fillet(fillet_bottom)
        return s

    out_top = t.plate_clearance + t.lip
    outer = prism(out_top, 0, z['top'], t.outer_fillet)
    outer = outer.edges('>Z').fillet(t.rim_fillet)
    cavity = prism(-t.ledge, t.floor, z['ledge'] + 0.01, t.inner_fillet)
    rebate = prism(t.plate_clearance + 2 * tn, z['ledge'], z['top'] + 2)
    tub = outer.cut(cavity).cut(rebate)

    # Ribs and bosses inside the cavity, drafted. Ribs are clipped to the inside of the walls.
    h_rib = t.rib_top - t.floor + 0.5
    top_w = max(t.rib - 2 * h_rib * tn, 0.6)
    inside = prism(-t.ledge, t.floor - 0.5, t.rib_top + 1)
    grid = None
    for x0, y0, x1, y1 in ribs(n, p, board, W, H, columns):
        L = math.hypot(x1 - x0, y1 - y0)
        prof = (cq.Workplane('YZ').polyline([(-t.rib / 2, 0), (t.rib / 2, 0), (top_w / 2, h_rib),
                                             (-top_w / 2, h_rib)]).close().extrude(L))
        if y0 != y1:                                 # across: turn to run along y
            prof = prof.rotate((0, 0, 0), (0, 0, 1), 90)
        rib = prof.translate((x0, y0, t.floor - 0.5))
        grid = rib if grid is None else grid.union(rib)
    grid = grid.intersect(inside)
    tub = tub.union(grid)
    rb = t.boss_diameter / 2
    for x, y, _, _ in columns:
        boss = (cq.Workplane('XY').workplane(offset=t.floor - 0.5).circle(rb + (t.boss_top - t.floor + 0.5) * tn)
                .extrude(t.boss_top - t.floor + 0.5, taper=t.draft).translate((x, y, 0)))
        tub = tub.union(boss)
    for x, y, _, _ in columns:
        hole = cq.Workplane('XY').circle(t.boss_hole / 2).extrude(t.boss_top + 1).translate((x, y, -0.5))
        pocket = cq.Workplane('XY').circle(t.pocket_diameter / 2).extrude(z['pocket'] + 0.5).translate((x, y, -0.5))
        lead = (cq.Workplane('XY').workplane(offset=t.boss_top - 0.4).circle(t.boss_hole / 2)
                .workplane(offset=0.41).circle(t.boss_hole / 2 + 0.4).loft().translate((x, y, 0)))
        tub = tub.cut(hole).cut(pocket).cut(lead)

    # Foot recesses
    for fx, fy in feet(n, p, t, board, H):
        tub = tub.cut(cq.Workplane('XY').circle(p.foot_diameter / 2 + 0.3).extrude(t.foot_recess + 0.5)
                      .translate((fx, fy, -0.5)))

    # USB opening: a stadium through the right-hand wall, with a 45° chamfer on the outside
    yu, zu, _ = usb_center(n, p, t, board, W, H)
    x_out = W + out_top - (z['top'] - zu) * tn       # outer face at the opening's centre
    c, extra = t.usb_chamfer, 0.6
    slot = (cq.Workplane('YZ', origin=(x_out - 8, yu, zu)).slot2D(t.usb_hole_width, t.usb_hole_height)
            .extrude(10))
    cham = (cq.Workplane('YZ', origin=(x_out + extra, yu, zu))
            .slot2D(t.usb_hole_width + 2 * (c + extra), t.usb_hole_height + 2 * (c + extra))
            .workplane(offset=-(c + extra) - 0.01).slot2D(t.usb_hole_width, t.usb_hole_height).loft())
    tub = tub.cut(slot).cut(cham)
    return tub


# ---------------------------------------------------------------- output

def section(path, n, p, t, board, tub):
    """The tub cut across at the rightmost board's front-right column, with the columns, the PCB
    and the front plate drawn in, to scale."""
    import cadquery as cq
    plt = plates._plt()
    from matplotlib.patches import Rectangle

    W, H, front, back, *_ = plates.layout(n, p, board)
    z = heights(p, t)
    xc = max(c[0] for c in back)
    x = xc + t.rib / 2 + 0.3                         # just beside the rib that runs along the column
    face = cq.Face.makePlane(400, 400, basePnt=cq.Vector(x, H / 2, 20), dir=cq.Vector(1, 0, 0))
    cut = tub.val().intersect(face)
    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=150)
    for e in cut.Edges():
        pts = [e.positionAt(k / 40) for k in range(41)]
        ax.plot([q.y for q in pts], [q.z for q in pts], color='k', lw=0.7)
    T = p.panel_thickness
    ax.add_patch(Rectangle((0, z['plate']), H, T, fc='#d9c7a0', ec='k', lw=0.5))
    ax.add_patch(Rectangle((p.margin_bottom, z['pcb_bot']), board['h'], p.pcb_thickness, fc='#2e6b3a', ec='k', lw=0.5))
    for _, y, _, _ in [c for c in back if abs(c[0] - xc) < 0.01]:
        ax.add_patch(Rectangle((y - 2.75, z['pcb_top']), 5.5, p.standoff, fc='#c8a24a', ec='k', lw=0.4))
        ax.add_patch(Rectangle((y - 2.75, t.boss_top), 5.5, p.pcb_spacer, fc='#c8a24a', ec='k', lw=0.4))
        ax.add_patch(Rectangle((y - 1.5, z['pocket']), 3, t.screw, fc='0.6', ec='k', lw=0.4))
        ax.add_patch(Rectangle((y - t.head_diameter / 2, t.head_inset), t.head_diameter, t.head_height,
                               fc='0.6', ec='k', lw=0.4))
    # lead stubs zone
    ax.add_patch(Rectangle((p.margin_bottom, z['pcb_bot'] - p.lead_stub), board['h'], p.lead_stub,
                           fc='none', ec='C3', lw=0.5, ls=':'))
    ax.annotate('cut leads (3 mm)', (H / 2, z['pcb_bot'] - p.lead_stub + 0.6), fontsize=6, color='C3', ha='center')
    ax.annotate('front plate', (H / 2, z['plate'] + T + 1), fontsize=7, ha='center')
    ax.annotate('PCB', (H / 2, z['pcb_top'] + 1), fontsize=7, ha='center')
    ax.annotate('front', (-3, -5), fontsize=7)
    ax.annotate('back', (H - 6, -5), fontsize=7)
    ax.set_xlim(-6, H + 6)
    ax.set_ylim(-8, z['top'] + 6)
    ax.set_aspect('equal')
    ax.set_xlabel('mm from the front plate\'s front edge', fontsize=7)
    ax.set_ylabel('mm above the tub\'s underside', fontsize=7)
    ax.tick_params(labelsize=6)
    ax.set_title(f'Tub cut across through a column, beside the rib along it (x = {x:.1f}), to scale', fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def renders(out, n, p, t, board, tub):
    import cadquery as cq
    import assembly

    W, H, *_ = plates.layout(n, p, board)
    z = heights(p, t)
    a = assembly.Assy(name='tub')
    a.add(tub, name='tub', color=assembly.C_WALL)
    # The fine renders first: the mesh is kept on the shapes, and a coarse one isn't redone.
    yu, zu, _ = usb_center(n, p, t, board, W, H)
    assembly.render(a, out / f'tub_{n}_usb.png', (75, 10), zoom=1.0, focus=(W, yu, zu), dist=110,
                    fine=True)
    assembly.render(a, out / f'tub_{n}_bottom.png', (-25, -40), zoom=1.9, fine=True)
    assembly.render(a, out / f'tub_{n}_top.png', (-25, 40), zoom=1.9)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', type=int, nargs='+', help='number of modules, one tub per value')
    ap.add_argument('--board', default=PCB)
    ap.add_argument('--out', default=ROOT / 'mech' / 'out', type=Path)
    ap.add_argument('--no-renders', dest='renders', action='store_false', help="don't write the check renders")
    for cls in (Params, TubParams):
        for f in fields(cls):
            ap.add_argument(f'--{f.name.replace("_", "-")}', type=float, default=f.default)
    a = ap.parse_args()
    p = Params(**{f.name: getattr(a, f.name) for f in fields(Params)})
    t = TubParams(**{f.name: getattr(a, f.name) for f in fields(TubParams)})

    import cadquery as cq

    board = plates.read_board(a.board)
    a.out.mkdir(parents=True, exist_ok=True)
    for n in a.modules:
        W, H, front, back, *_ = plates.layout(n, p, board)
        notes = check(n, p, t, board, W, H, back)
        tub = build(n, p, t, board)
        solid = tub.val()
        if not solid.isValid():
            raise SystemExit(f'tub: {n} modules: the solid is not valid')
        vol = solid.Volume() / 1000
        bb = solid.BoundingBox()
        print(f'{n} modules:')
        for line in notes:
            print('  ' + line)
        print(f'  {vol:.0f} cm³, about {vol * ABS_DENSITY:.0f} g in ABS; projected area '
              f'{bb.xlen * bb.ylen / 100:.0f} cm² (for the clamp force)')
        step, stl = a.out / f'tub_{n}.step', a.out / f'tub_{n}.stl'
        cq.exporters.export(tub, str(step))
        cq.exporters.export(tub, str(stl), tolerance=0.02, angularTolerance=0.1)
        print(f'  wrote {step}\n  wrote {stl}')
        if a.renders:
            renders(a.out, n, p, t, board, tub)
            section(a.out / f'tub_{n}_section.png', n, p, t, board, tub)
            print(f'  renders: {a.out}/tub_{n}_{{top,bottom,usb,section}}.png')


if __name__ == '__main__':
    main()
