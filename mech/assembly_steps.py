"""Mechanical assembly steps for a 4-button unit: the step texts, and their pictures.

    uv run --group dev mech/assembly_steps.py    # writes docs/build/mech/*.webp

The texts are plain data (STEPS, and WALL_STEPS for the optional printed walls) and are read by
pcb/scripts/build_docs.py, which puts them at the end of docs/build.md. This script only makes the pictures: it builds the unit
with assembly.py, tessellates every part once, and renders each step off screen with VTK
(plain flat shading). Each step shows the parts fitted so far; the parts of that step are
outlined, as in the board steps. Some steps lift parts apart ("explode") to show how they go
together.

Parts are picked by the name prefixes assembly.py gives them (back_plate, module_, standoff_,
screw_bottom_, ...). Run it again after changing the enclosure or the board.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'mech'))
from plates import Params  # noqa: E402
from walls import WallParams  # noqa: E402

P = Params()
W = WallParams()
TOP_SCREW = f'M3 × {P.top_screw:g}'
BOTTOM_SCREW = f'M3 × {P.bottom_screw:g}'
N = 4                       # modules in the pictured unit
OUT = ROOT / 'docs' / 'build' / 'mech'
OUT_WIDTH = 1000            # px, final image width

# What every board already carries when the board build is done (board step 12: LED spacer).
BOARDS = ['module_', 'led_spacer_']
COLUMNS = ['standoff_', 'pcb_spacer_']      # the two standoffs at each mounting hole
FRONT = (-25, 30)           # camera (azimuth, elevation) in degrees: from the front right, above
BACK = (155, 30)            # from the back left: the chain cables and the Pico's USB side
BELOW = (155, -55, 'flipped')   # from underneath, as seen after turning the unit over
LOW = (-25, 12)             # from the front, nearly level: the standoffs under the boards
UNDER = (-25, -25)          # from the front, below: the screws going up into the back plate

RIGHT_END = (65, 22)        # from the front right, low: the USB end

# adds:     part-name prefixes fitted in this step (shown from now on, outlined in its picture).
# removes:  part-name prefixes taken off in this step (outlined in its picture, gone after it).
# explode:  prefix -> mm to move those parts up (+) or down (-), or (dx, dy, dz) in mm, in this
#           step's picture only. The first matching prefix wins, so put longer ones first.
# views:    camera per picture; one picture per view.
# outline:  False for no outline (the first step, where everything is new).
# parts:    (qty, description) for the parts table.
STEPS = [
    dict(slug='boards', title='Get the boards ready', adds=BOARDS, views=[FRONT], outline=False, parts=[
        (1, 'main board (with the Pico), built'),
        (N - 1, 'extension board, built'),
    ], text=f"""
Every board must be fully built, with its chips in and the LED on its spacer.

1. Lay the boards out in a row, **footswitches towards you**: the **main board at the right
   end** (its USB connector points off the right edge), the {N - 1} extension boards to its left.
2. Check that every lead under the boards is cut to **{P.lead_stub:g} mm or less**, including
   the footswitch and Pico pins. The back plate sits {P.pcb_spacer:g} mm under the boards.
3. Peel the protective film off both plates, if they have one.
"""),
    dict(slug='standoffs', title='Standoffs', adds=COLUMNS,
         explode={'standoff_': 12, 'pcb_spacer_': -12}, views=[LOW], parts=[
             (4 * N, f'M3 hex standoff, male-female, {P.pcb_spacer:g} mm + {P.stud:g} mm stud'),
             (4 * N, f'M3 hex standoff, female-female, {P.standoff:g} mm'),
         ], text=f"""
Each of the four mounting holes in the board corners gets a column of two standoffs: a short
one under the board, and a long one on top, screwed onto the short one's stud.

1. From the **underside**, push a **short standoff**'s stud up through a mounting hole. The
   body stays under the board.
2. On top, screw a **{P.standoff:g} mm standoff** onto the stud, finger tight.
3. Do the other three holes, then tighten each pair: hold the short one with a 5.5 mm
   spanner or pliers and turn the long one. Not too hard: the thread is brass.

Do this on every board. Check that no column has a gap at the board: the standoffs clamp it.
"""),
    dict(slug='switch-nuts', title='Lower switch nuts',
         adds=['switch_nut_low_', 'switch_washer_low_'], views=[FRONT], parts=[
             (N, 'M12 nut and washer, from the switch'),
         ], text=f"""
Each footswitch comes with two nuts and two washers. The first nut and washer go on now,
under the front plate. They set the switch height.

1. Take the nuts and washers off the switch thread.
2. Run one nut down the thread, then one washer on top of it.
3. Turn the nut until the **top of the washer is level with the tops of the {P.standoff:g} mm
   standoffs** (lay a ruler across the standoffs). That is about {P.standoff - P.switch_body:.1f} mm
   above the switch body.

Do this on every board. Keep the other nut and washer for later.
"""),
    dict(slug='back-plate', title='Boards on the back plate', adds=['back_plate', 'screw_bottom_'],
         explode={**{b: 30 for b in BOARDS + COLUMNS}, 'switch_nut_low_': 30,
                  'switch_washer_low_': 30, 'screw_bottom_': -18},
         views=[UNDER], parts=[
             (1, 'back plate (only the small holes)'),
             (4 * N, f'{BOTTOM_SCREW} mm button head screw'),
         ], text=f"""
1. Lay the back plate across two blocks or books, or let it stick out over the edge of the
   bench, so you can get at the holes from underneath.
2. Put each board on the plate, in the same order as in step M1. The short standoffs' bodies
   stand on the plate, over its holes.
3. From underneath, screw an **{BOTTOM_SCREW}** screw up through the plate into every short standoff
   ({4 * N} in all). Leave them a little loose until all are in, then tighten them.
"""),
    dict(slug='cables', title='Chain cables', adds=['socket_', 'ribbon_'], views=[BACK],
         parts=[(N - 1, 'chain cable (see *Make a ribbon cable* above)')], text="""
The connectors are on the back edge of each board (the edge away from you).

1. Plug a cable into the main board's **OUT** (J2, its only chain header) and the other end
   into the **IN** (J1, the right one of the two headers) of the extension board to its left.
2. Do the same from each extension board's **OUT** to the next board's **IN**.
3. The leftmost board's OUT stays empty.

The cable lies flat along the back edge, a little slack between the sockets.

**Flash and test now**, before the front plate goes on. The first flash needs the Pico's
BOOTSEL button, which the front plate covers (see `docs/firmware.md`). Then press each switch:
its LED should light.
"""),
    dict(slug='front-plate', title='Front plate', adds=['front_plate'],
         explode={'front_plate': 35}, views=[FRONT], parts=[
             (1, 'front plate (big switch holes, LED holes)'),
         ], text="""
1. Lower the front plate onto the standoffs: the switch threads go through the big holes,
   the LEDs into the small ones.
2. It rests on the standoffs and the lower switch washers. If it rocks, a lower nut is set
   too high: take the plate off and turn that nut down a little.
"""),
    dict(slug='top-screws', title='Top screws and switch nuts',
         adds=['screw_top_', 'switch_washer_top_', 'switch_nut_top_'], views=[FRONT], parts=[
             (4 * N, f'{TOP_SCREW} mm button head screw'),
             (N, 'M12 nut and washer, from the switch'),
         ], text=f"""
1. Screw an **{TOP_SCREW}** screw through the plate into every standoff ({4 * N} in all). Snug,
   not tight: the plate is acrylic.
2. On each switch: the second washer, then the second nut, on top of the plate. Tighten the
   nut by hand, then a quarter turn with a 14 mm spanner, holding the switch straight.
"""),
    dict(slug='feet', title='Feet', adds=['foot_'], views=[BELOW], parts=[
        (2 * N, 'rubber foot, stick-on, 12 mm'),
    ], text="""
1. Turn the unit over onto a towel.
2. Stick a foot under each switch, near the front edge, and one behind it, near the back
   edge. They sit between the screw heads: the stomp goes straight down into them.
"""),
    dict(slug='done', title='Done', adds=[], views=[FRONT, BACK], parts=[], text="""
Turn it back over and plug USB into the Pico, at the right-hand end.
"""),
]


# The optional printed walls, as their own section after the steps above: on a finished unit.
TOP = ['front_plate', 'screw_top_', 'switch_washer_top_', 'switch_nut_top_']
OUTWARD = 30                # mm the wall pieces are pulled out in the fitting picture
N_STRAIGHT = 2 * N - 4
WALL_STEPS = [
    dict(slug='walls-open', title='Take the front plate off', adds=[], removes=TOP,
         explode={'switch_nut_top_': 55, 'switch_washer_top_': 50, 'screw_top_': 55, 'front_plate': 35},
         views=[FRONT], parts=[], text=f"""
The walls hook over the edges of both plates, so the front plate has to come off. If you are
building a new unit, fit the walls after step M5 instead, and skip this step.

1. Take the top nut and washer off each switch (14 mm spanner).
2. Unscrew the {4 * N} {TOP_SCREW} screws from the front plate.
3. Lift the front plate off. The boards stay screwed to the back plate.
"""),
    dict(slug='walls-fit', title='Walls around the back plate',
         adds=['wall_end_', 'wall_front_', 'wall_back_', 'wall_pin_'],
         explode={'wall_end_left': (-OUTWARD, 0, 0), 'wall_end_right': (OUTWARD, 0, 0),
                  'wall_front_': (0, -OUTWARD, 0), 'wall_pin_front_': (0, -OUTWARD, 0),
                  'wall_back_': (0, OUTWARD, 0), 'wall_pin_back_': (0, OUTWARD, 0)},
         views=[FRONT], parts=[
             (1, 'wall end cap, left (`walls_N_end_left.stl`)'),
             (1, 'wall end cap, right, with the USB cutout (`walls_N_end_right.stl`)'),
             (N_STRAIGHT, 'wall, straight (`walls_N_straight.stl`)'),
             (4 * N - 4, f'alignment pin: 1.75 mm filament, {2 * W.pin_depth - 1:g} mm long'),
         ], text=f"""
Each wall has a step along its top and bottom inside edge. The edge of the back plate sits in
the bottom step, the front plate's edge in the top one.

1. Clean the stringing out of the pin holes at the ends of the pieces. A 2 mm drill, turned by
   hand, does it.
2. Cut {4 * N - 4} pins of {2 * W.pin_depth - 1:g} mm from 1.75 mm filament. Push two into the
   holes at **both ends of the end caps' arms**, halfway in.
3. Hook the **right end cap** (the one with the USB cutout) over the right-hand end of the
   back plate. The plate's edge goes into its bottom step, and the USB port lines up with
   the cutout. Then the **left end cap** at the left-hand end.
4. Fit the {N_STRAIGHT} straight pieces along the front and back edges, from one end to the
   other. Push each one onto the pins of the piece before it, then put two pins in its free
   end for the next one.
5. Check that the frame sits flat on the bench all round, with the back plate's edge in the
   step everywhere. If a piece won't close up, trim the pin a little.

Until the front plate is on, the straight pieces can fall outwards. A strip of tape across
each joint holds them.
"""),
    dict(slug='walls-close', title='Front plate back on', adds=TOP,
         explode={'switch_nut_top_': 55, 'switch_washer_top_': 50, 'screw_top_': 55, 'front_plate': 35},
         views=[FRONT], parts=[], text=f"""
1. Lower the front plate onto the standoffs, as in step M6. Its edge drops into the top step
   of the walls all round. If it catches, find the piece that has moved out of line and push
   it back in.
2. Screw it down with the {4 * N} {TOP_SCREW} screws, and put the top washers and nuts back
   on the switches, as in step M7. Take any tape off.

The plates now hold the walls: there is no need for glue. The walls are slightly shorter than
the standoffs, so the screws still clamp on the standoffs, not on the walls.
"""),
    dict(slug='walls-done', title='Done', adds=[], views=[FRONT, RIGHT_END], parts=[], text="""
USB goes in through the cutout in the right-hand end cap.
"""),
]


# The cover picture (README and the top of docs/build.md): the whole unit, walls included,
# pulled apart. Layers go up and down; the walls move outwards, so nothing hides the boards.
# Seen from the right, where the Pico's USB port is.
COVER_NAME = 'cover.webp'
COVER_VIEW = (60, 24)
COVER_EXPLODE = {
    'switch_nut_top_': 120, 'switch_washer_top_': 108, 'screw_top_': 120, 'front_plate': 85,
    'foot_': -70, 'screw_bottom_': -45,
    'wall_end_left': (-60, 0, 25), 'wall_end_right': (60, 0, 25),
    'wall_front_': (0, -60, 25), 'wall_pin_front_': (0, -60, 25),
    'wall_back_': (0, 60, 25), 'wall_pin_back_': (0, 60, 25),
    'back_plate': 0,
    **{q: 30 for q in BOARDS + COLUMNS + ['switch_nut_low_', 'switch_washer_low_', 'socket_', 'ribbon_']},
}


# ------------------------------------------------------------------------------- rendering

def main():
    import numpy as np
    import vtk
    import tempfile
    from dataclasses import fields
    from PIL import Image
    from cadquery.occ_impl.assembly import toVTKAssy

    sys.path.insert(0, str(ROOT / 'mech'))
    sys.path.insert(0, str(ROOT / 'pcb' / 'scripts'))
    import assembly, plates, walls
    from build_docs import outline, NEW_COLOUR

    p = plates.Params()
    board = plates.read_board(assembly.PCB)
    with tempfile.TemporaryDirectory() as tmp:
        a, _ = assembly.build(N, p, board, Path(tmp), walls.WallParams())

    # One set of actors per top-level part, tessellated once.
    ren = vtk.vtkRenderer()
    ren.SetBackground(1, 1, 1)
    parts = {}
    for child in a.children:
        sub = assembly.Assy(name='view')
        sub.add(child, name=child.name, loc=child.loc)
        actors = [x for x in toVTKAssy(sub, edges=False, tolerance=0.2, angularTolerance=0.3)
                  if x.GetVisibility()]
        for x in actors:
            ren.AddActor(x)
        parts[child.name] = [(x, x.GetPosition()) for x in actors]
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.AddRenderer(ren)
    win.SetSize(2000, 1400)

    def match(name, prefixes):
        return any(name.startswith(q) for q in prefixes)

    colours = {id(x): x.GetProperty().GetColor() for v in parts.values() for x, _ in v}

    def shot(visible, explode, view, marked=()):
        """Show the `visible` parts; `marked` ones in a flat marker colour."""
        for name, actors in parts.items():
            d = next((d for q, d in explode.items() if name.startswith(q)), 0)
            dx, dy, dz = d if isinstance(d, tuple) else (0, 0, d)
            for x, (px, py, pz) in actors:
                x.SetVisibility(match(name, visible))
                x.SetPosition(px + dx, py + dy, pz + dz)
                x.GetProperty().SetColor(*((1, 0, 1) if match(name, marked) else colours[id(x)]))

    def camera(visible, explode, view):
        """Frame the step's full picture; the 'before' render reuses the same camera."""
        import math
        shot(visible, explode, view)
        cam = ren.GetActiveCamera()
        ren.ResetCamera()
        fx, fy, fz = cam.GetFocalPoint()
        dist = cam.GetDistance()
        az, el = view[:2]
        cam.SetPosition(fx + dist * math.cos(math.radians(el)) * math.sin(math.radians(az)),
                        fy - dist * math.cos(math.radians(el)) * math.cos(math.radians(az)),
                        fz + dist * math.sin(math.radians(el)))
        cam.SetViewUp(0, 0, -1 if 'flipped' in view else 1)
        ren.ResetCamera()
        ren.ResetCameraClippingRange()

    def grab():
        win.Render()
        f = vtk.vtkWindowToImageFilter()
        f.SetInput(win)
        f.ReadFrontBufferOff()
        f.Update()
        img = f.GetOutput()
        w, h, _ = img.GetDimensions()
        from vtk.util.numpy_support import vtk_to_numpy
        arr = vtk_to_numpy(img.GetPointData().GetScalars()).reshape(h, w, -1)[::-1]
        rgb = arr[:, :, :3].astype(np.int16)
        return np.dstack([rgb, np.full(rgb.shape[:2], 255, np.int16)])   # outline() wants RGBA

    OUT.mkdir(parents=True, exist_ok=True)
    written = set()

    def save(img, name):
        """Crop to the drawing, with a margin, then scale to the page width."""
        ys, xs = np.nonzero((img[:, :, :3] < 250).any(axis=2))
        pad = 30
        box = (max(xs.min() - pad, 0), max(ys.min() - pad, 0),
               min(xs.max() + pad, img.shape[1]), min(ys.max() + pad, img.shape[0]))
        im = Image.fromarray(img[:, :, :3].clip(0, 255).astype(np.uint8)).crop(box)
        im = im.resize((OUT_WIDTH, round(im.height * OUT_WIDTH / im.width)), Image.LANCZOS)
        im.save(OUT / name, quality=88, method=6)
        written.add(name)
        print(f'  {name}')
    visible = []
    steps = [('', i, s) for i, s in enumerate(STEPS, 1)] + [('w', i, s) for i, s in enumerate(WALL_STEPS, 1)]
    for prefix, i, s in steps:
        new = s['adds'] + s.get('removes', [])
        visible += s['adds']
        before = [v for v in visible if v not in new]
        ex = s.get('explode', {})
        for j, view in enumerate(s['views']):
            camera(visible, ex, view)
            after = grab()
            if new and s.get('outline', True):
                # Outline where the new parts show: compare a render without them to one with
                # them in a marker colour (black feet on a black plate barely change a pixel).
                shot(visible, ex, view, marked=new)
                marked = grab()
                shot(before, ex, view)
                after = outline(after, grab(), marked, NEW_COLOUR)
            save(after, image_name(i, s, j, prefix))
        visible = [v for v in visible if v not in s.get('removes', [])]
    camera([''], COVER_EXPLODE, COVER_VIEW)         # '' matches every part
    save(grab(), COVER_NAME)
    for f in OUT.glob('*.webp'):
        if f.name not in written:
            f.unlink()


def image_name(i, step, j, prefix=''):
    """prefix: '' for STEPS, 'w' for WALL_STEPS."""
    return f'{prefix}{i:02d}-{step["slug"]}' + (f'-{j + 1}' if len(step['views']) > 1 else '') + '.webp'


if __name__ == '__main__':
    main()
