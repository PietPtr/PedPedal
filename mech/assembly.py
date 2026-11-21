"""3D model of the whole unit: front and back plate, the standoff/spacer columns through each
board, screws, switch nuts, LED spacers, feet, chain cables, and the boards with their components (exported from
KiCad). Uses the same layout and dimensions as plates.py.

    uv run mech/assembly.py 4     # writes mech/out/assembly_4.step and assembly_4.glb
                                  # plus check renders assembly_4_*.png

Module 1 (rightmost) gets the Pico and R5-R8 but no IN header (J1); the others the other way round.
The LED is lifted onto its spacer, and chips are put in the DIP sockets, in a temporary copy of
the board before the STEP export.
"""
import argparse
import math
import re
import subprocess
import sys
import tempfile
from dataclasses import fields
from pathlib import Path

import cadquery as cq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plates  # noqa: E402
from plates import HEX_R, Params  # noqa: E402

ROOT = plates.ROOT
PCB = ROOT / 'pcb' / 'footswitch.kicad_pcb'
MODULE1_ONLY = {'U3', 'R5', 'R6', 'R7', 'R8'}
EXT_ONLY = {'J1'}                # the IN header: nothing plugs into it on module 1
NOT_FITTED = set()
# A chip in each DIP socket, 3 mm up so it sits on the socket.
CHIP_MODEL = ('(model "${KICAD10_3DMODEL_DIR}/Package_DIP.3dshapes/DIP-16_W7.62mm.step" '
              '(offset (xyz 0 0 3)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))')

C_PLATE = cq.Color(0.16, 0.16, 0.17)        # black anodised / dark acrylic
C_BRASS = cq.Color(0.80, 0.65, 0.30)
C_STEEL = cq.Color(0.62, 0.63, 0.65)
C_BLACK = cq.Color(0.08, 0.08, 0.08)
C_RUBBER = cq.Color(0.12, 0.12, 0.12)
C_SPACER = cq.Color(0.92, 0.92, 0.90)       # white nylon LED spacer
C_RIBBON = cq.Color(0.70, 0.70, 0.72)


class Assy(cq.Assembly):
    """Assembly that makes repeated names unique instead of refusing them. KiCad's STEP export
    names every instance of a part after its model (all the resistors are 'R_Axial_...'), which
    cadquery's importer otherwise rejects."""

    def add(self, arg, **kw):
        if isinstance(arg, cq.Assembly):
            base = name = kw.get('name') or arg.name
            k = 1
            while name in self.objects:
                k += 1
                name = f'{base}_{k}'
            kw['name'] = name
        return super().add(arg, **kw)


# ---------------------------------------------------------------- parts

def plate(W, H, holes, p):
    wp = cq.Workplane('XY').sketch().rect(W, H).vertices().fillet(p.corner_radius).finalize()
    wp = wp.extrude(p.panel_thickness).translate((W / 2, H / 2, 0))
    pts = [(x, y) for x, y, _, _ in holes]
    for d in sorted({h[2] for h in holes}):
        wp = wp.faces('>Z').workplane(origin=(0, 0, p.panel_thickness)).pushPoints(
            [(x, y) for x, y, dd, _ in holes if dd == d]).hole(d)
    return wp


def hex_spacer(length, thread=2.5):
    return (cq.Workplane('XY').polygon(6, 2 * HEX_R).extrude(length)
            .faces('>Z').workplane().hole(thread))


def button_screw(length):
    """ISO 7380 M3: head 5.7 x 1.65 above z=0, shank going down."""
    head = (cq.Workplane('XY').circle(5.7 / 2).extrude(1.65).faces('>Z').edges().fillet(0.8)
            .faces('>Z').workplane().polygon(6, 2 / math.cos(math.pi / 6)).cutBlind(-1.0))
    shank = cq.Workplane('XY').circle(1.5).extrude(-length)
    return head.union(shank)




def mf_up(length, stud):
    """Male-female hex standoff with the stud pointing up: body from z=0, stud above it."""
    return hex_spacer(length).union(cq.Workplane('XY').workplane(offset=length).circle(1.5).extrude(stud))


def nut(af, thick, hole):
    return cq.Workplane('XY').polygon(6, af / math.cos(math.pi / 6)).extrude(thick).faces('>Z').workplane().hole(hole)


def washer(od, idia, thick):
    return cq.Workplane('XY').circle(od / 2).circle(idia / 2).extrude(thick)


def led_spacer(length):
    return cq.Workplane('XY').circle(3.0).extrude(length).faces('>Z').workplane().rect(2.4, 2.4, forConstruction=True).vertices().hole(0.9)


def foot():
    return cq.Workplane('XY').circle(6).extrude(-4).faces('<Z').edges().fillet(1.5)


def idc_socket():
    """FC-8P socket with the ribbon clamped on top. Origin at the bottom centre."""
    body = cq.Workplane('XY').rect(6.0, 15.3).extrude(7.0)
    cover = cq.Workplane('XY').workplane(offset=7.0).rect(6.0, 15.3).extrude(1.5)
    return body.union(cover)


def ribbon(points, width=10.2, thick=1.0):
    """Flat ribbon along a polyline in the XZ plane (width along Y), as boxes per segment."""
    r = None
    for (x0, z0), (x1, z1) in zip(points, points[1:]):
        lx, lz = abs(x1 - x0) or thick, abs(z1 - z0) or thick
        seg = cq.Workplane('XY').box(lx + (thick if x1 != x0 else 0), width, lz + (thick if z1 != z0 else 0)).translate(
            ((x0 + x1) / 2, 0, (z0 + z1) / 2))
        r = seg if r is None else r.union(seg)
    return r


# ---------------------------------------------------------------- boards from KiCad

def export_board(out, refs, led_lift):
    """STEP of one board with only `refs` fitted, origin at the board's top-left corner
    (KiCad's STEP: x right, y up so the board spans y 0..-86, board bottom at z=0)."""
    text = PCB.read_text()
    # Lift the LED onto its spacer: the first offset after the LED model line.
    m = re.search(r'(\(model "[^"]*LED_D5\.0mm[^"]*"\s*\(offset\s*\(xyz [-\d.]+ [-\d.]+ )([-\d.]+)\)', text)
    if not m:
        raise SystemExit('LED model offset not found in the board')
    text = text[:m.start(2)] + f'{led_lift:.3f}' + text[m.end(2):]
    # The chips in their sockets: the socket footprints only carry the socket's model.
    sock = '(model "${KICAD10_3DMODEL_DIR}/Package_DIP.3dshapes/DIP-16_W7.62mm_Socket.step"'
    if sock not in text:
        raise SystemExit('DIP socket model not found in the board')
    text = text.replace(sock, CHIP_MODEL + '\n\t\t' + sock)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_pcb = Path(tmp) / 'footswitch.kicad_pcb'
        tmp_pcb.write_text(text)
        cmd = ['kicad-cli', 'pcb', 'export', 'step', str(tmp_pcb), '-o', str(out), '-f',
               '--user-origin', f'{_origin()[0]}x{_origin()[1]}mm',
               '--component-filter', ','.join(sorted(refs)),
               '-D', f'KIPRJMOD={ROOT / "pcb"}']
        subprocess.run(cmd, check=True, capture_output=True)


def _origin():
    pcb = plates.sx.parse(PCB.read_text())
    for r in plates._find(pcb, 'gr_rect'):
        if plates._find(r, 'layer')[0][1] == 'Edge.Cuts':
            x0, y0 = map(float, plates._find(r, 'start')[0][1:3])
            x1, y1 = map(float, plates._find(r, 'end')[0][1:3])
            return min(x0, x1), min(y0, y1)


# ---------------------------------------------------------------- assembly

def build(n, p, board, workdir):
    W, H, front, back, boards, feet = plates.layout(n, p, board)
    T = p.panel_thickness
    # z = 0 at the back plate's underside
    z_back_top = T
    z_pcb_bot = T + p.pcb_spacer
    z_pcb_top = z_pcb_bot + p.pcb_thickness
    z_front = z_pcb_top + p.standoff               # front plate underside
    led_lift = p.standoff + T + p.led_proud - p.led_height

    all_refs = set(board['parts']) - NOT_FITTED
    main_step = workdir / 'board_main.step'
    ext_step = workdir / 'board_ext.step'
    export_board(main_step, all_refs - EXT_ONLY, led_lift)
    export_board(ext_step, all_refs - MODULE1_ONLY, led_lift)
    main = Assy.importStep(str(main_step))
    ext = Assy.importStep(str(ext_step))

    a = Assy(name=f'footswitch_{n}')
    a.add(plate(W, H, back, p), name='back_plate', color=C_PLATE)
    a.add(plate(W, H, front, p), name='front_plate', color=C_PLATE, loc=cq.Location((0, 0, z_front)))

    for i, (bx, by, bw, bh) in enumerate(boards):
        is_main = i == n - 1                        # module 1 is at the right-hand end
        a.add(main if is_main else ext, name=f'module_{n - i}',
              loc=cq.Location((bx, by + bh, z_pcb_bot)))

    standoff = hex_spacer(p.standoff)
    spacer = mf_up(p.pcb_spacer, p.stud)
    screw_top = button_screw(T + 5)
    screw_bot = button_screw(p.bottom_screw)
    nut_, washer_ = nut(14, p.switch_nut, 12), washer(18, 12.2, p.switch_washer)
    lsp = led_spacer(led_lift)
    for k, (x, y, d, kind) in enumerate(front):
        if kind == 'screw':
            a.add(standoff, name=f'standoff_{k}', color=C_BRASS, loc=cq.Location((x, y, z_pcb_top)))
            a.add(spacer, name=f'pcb_spacer_{k}', color=C_BRASS, loc=cq.Location((x, y, z_back_top)))
            a.add(screw_top, name=f'screw_top_{k}', color=C_STEEL, loc=cq.Location((x, y, z_front + T)))
            a.add(screw_bot, name=f'screw_bottom_{k}', color=C_STEEL,
                  loc=cq.Location((x, y, 0), (1, 0, 0), 180))
        elif kind == 'switch':
            a.add(washer_, name=f'switch_washer_low_{k}', color=C_STEEL,
                  loc=cq.Location((x, y, z_front - p.switch_washer)))
            a.add(nut_, name=f'switch_nut_low_{k}', color=C_STEEL,
                  loc=cq.Location((x, y, z_front - p.switch_washer - p.switch_nut)))
            a.add(washer_, name=f'switch_washer_top_{k}', color=C_STEEL, loc=cq.Location((x, y, z_front + T)))
            a.add(nut_, name=f'switch_nut_top_{k}', color=C_STEEL,
                  loc=cq.Location((x, y, z_front + T + p.switch_washer)))
        elif kind == 'led':
            a.add(lsp, name=f'led_spacer_{k}', color=C_SPACER, loc=cq.Location((x, y, z_pcb_top)))

    for k, (x, y) in enumerate(feet):
        a.add(foot(), name=f'foot_{k}', color=C_RUBBER, loc=cq.Location((x, y, 0)))

    # Chain cables: OUT (J2) of module i+1 to IN (J1) of module i. Both headers sit side by side
    # at the top left, so the ribbon runs straight along the top edge to the next module.
    # read_board gives the headers' pad centre, which is the shroud centre.
    sock = idc_socket()
    seat = z_pcb_top + 3.0                          # socket bottom, inside the shroud (estimate)
    top = seat + 8.5 + 0.5
    for i, (bx, by, bw, bh) in enumerate(boards):
        top_y = by + bh
        jx = {r: bx + board['parts'][r][0] for r in ('J1', 'J2')}
        jy = top_y - board['parts']['J1'][1]
        if i > 0:
            a.add(sock, name=f'socket_out_{i}', color=C_BLACK, loc=cq.Location((jx['J2'], jy, seat)))
        if i < n - 1:
            a.add(sock, name=f'socket_in_{i}', color=C_BLACK, loc=cq.Location((jx['J1'], jy, seat)))
            nxt = boards[i + 1][0] + board['parts']['J2'][0]
            pts = [(jx['J1'], top), (nxt, top)]
            a.add(ribbon(pts).translate((0, jy, 0)), name=f'ribbon_{i}', color=C_RIBBON)
    return a, (W, H, z_front + T)


# ---------------------------------------------------------------- check renders (VTK, off screen)

def render(a, png, view, size=(1600, 900), hide=(), zoom=1.3):
    import vtk
    from cadquery.occ_impl.assembly import toVTKAssy

    sub = Assy(name='view')
    for child in a.children:
        if not any(child.name.startswith(h) for h in hide):
            sub.add(child, name=child.name, loc=child.loc)
    ren = vtk.vtkRenderer()
    ren.SetBackground(1, 1, 1)
    for actor in toVTKAssy(sub, edges=False, tolerance=0.2, angularTolerance=0.3):
        ren.AddActor(actor)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.AddRenderer(ren)
    win.SetSize(*size)
    cam = ren.GetActiveCamera()
    ren.ResetCamera()
    fx, fy, fz = cam.GetFocalPoint()
    dist = cam.GetDistance()
    az, el = view
    cam.SetPosition(fx + dist * math.cos(math.radians(el)) * math.sin(math.radians(az)),
                    fy - dist * math.cos(math.radians(el)) * math.cos(math.radians(az)),
                    fz + dist * math.sin(math.radians(el)))
    cam.SetViewUp(0, 0, 1)
    ren.ResetCamera()
    cam.Zoom(zoom)
    win.Render()
    img = vtk.vtkWindowToImageFilter()
    img.SetInput(win)
    img.Update()
    w = vtk.vtkPNGWriter()
    w.SetFileName(str(png))
    w.SetInputConnection(img.GetOutputPort())
    w.Write()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modules', type=int, nargs='?', default=4)
    ap.add_argument('--out', default=ROOT / 'mech' / 'out', type=Path)
    ap.add_argument('--no-renders', dest='renders', action='store_false')
    for f in fields(Params):
        ap.add_argument(f'--{f.name.replace("_", "-")}', type=float, default=f.default)
    args = ap.parse_args()
    p = Params(**{f.name: getattr(args, f.name) for f in fields(Params)})
    board = plates.read_board(PCB)
    n = args.modules
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        a, (W, H, Z) = build(n, p, board, Path(tmp))
        step = args.out / f'assembly_{n}.step'
        glb = args.out / f'assembly_{n}.glb'
        a.export(str(step))
        # Coarser tessellation than the default: a fraction of the size, same look at this scale.
        a.export(str(glb), tolerance=0.05, angularTolerance=0.2)
    print(f'{n} modules: {W:.0f} x {H:.0f} x {Z:.0f} mm (without feet and switches)')
    print(f'  wrote {step}\n  wrote {glb}')
    if args.renders:
        render(a, args.out / f'assembly_{n}_front.png', (-25, 30), zoom=2.0)
        render(a, args.out / f'assembly_{n}_inside.png', (-25, 30), hide=('front_plate', 'screw_top', 'switch_nut_top',
                                                                         'switch_washer_top'), zoom=2.0)
        render(a, args.out / f'assembly_{n}_side.png', (-90, 0), zoom=3.2)
        print(f'  renders: {args.out}/assembly_{n}_{{front,inside,side}}.png')


if __name__ == '__main__':
    main()
