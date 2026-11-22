"""Shot 3, "Expandable": the bare main board (module 1, with the Pico), then a second board
glides in out of the dark, its ribbon cable drops onto both headers and its LED lights up. Then
six more boards follow in quick succession, eight in all, each lighting up as it is connected.
At the end they slide back out into the dark, last one first, and the camera returns to the main
board.

Only the boards are shown (with their switch and its lower nut, the LED spacer and the
spacers underneath), no plates, walls or enclosure screws. Boards 3-8 are copies of module 2.

Timeline (30 fps, 12 s):
    1- 45   hold: close on the main board, its LED on
   40- 95   board 2 glides in; 100-112 its cable drops in; 116 its LED lights
   70-140   hold: boards 1 and 2 and the cable
  160-245   boards 3-8, 12 frames apart, each with its cable and LED
  165-290   hold: wide on the whole chain
  290-340   LEDs off and boards 8..2 slide back out
  295-361   camera back to the main board
"""
import colorsys

import bpy
from mathutils import Matrix, Vector

from studio import MM, base_name, descendants, move

N_BOARDS = 8
PITCH = 0.100                       # board spacing along x, m
AWAY = Vector((-0.55, 0.50, 0.0))   # where a board comes from (and goes back to), off its spot
KEEP = ('pcb_spacer', 'switch_nut_low', 'switch_washer_low', 'led_spacer')


def P(target, az, dist, elev, fstop, lens):
    return dict(target=target, az=az, dist=dist, elev=elev, fstop=fstop, lens=lens)


def center_of(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs if o.type == 'MESH' for c in o.bound_box]
    return sum(pts, Vector()) / len(pts)


def reparent(child, parent):
    mw = child.matrix_world.copy()
    child.parent = parent
    child.matrix_parent_inverse.identity()
    child.matrix_world = mw


def duplicate(obj, parent=None):
    """Linked copy of obj and everything under it (LED lenses get their own mesh, so their
    material can differ)."""
    c = obj.copy()
    bpy.context.scene.collection.objects.link(c)
    if parent is not None:
        c.parent = parent
    for ch in obj.children:
        cc = duplicate(ch, c)
        if cc.type == 'MESH' and any(base_name(a).startswith('LED_D5') for a in _up(cc)):
            cc.data = ch.data.copy()
    return c


def _up(o):
    while o.parent:
        o = o.parent
        yield o


def shift(obj, d):
    obj.matrix_world = Matrix.Translation(d) @ obj.matrix_world


BELOW = Vector((0, 0, -1.0))   # out of sight: a metre under the (opaque) floor


def build(s):
    s.set_frames(360)
    u = s.unit('assembly_4')
    asm = u.root.children[0]
    bpy.context.view_layer.update()

    # --- strip down to boards 1 and 2 plus the cable between them
    mods = {k: u.modules[k] for k in (1, 2)}
    span = {}
    for k, m in mods.items():
        lo, hi = u.bounds(m)
        span[k] = (lo.x, hi.x)
    cable_parts = [o for o in asm.children if base_name(o) in ('ribbon_2', 'socket_in_2', 'socket_out_3')]
    for o in list(asm.children):
        n = base_name(o)
        if o in mods.values() or o in cable_parts:
            continue
        if n.startswith(KEEP):
            cx = center_of([o]).x
            k = next((k for k, (a, b) in span.items() if a <= cx <= b), None)
            if k:
                reparent(o, mods[k])
                continue
        for d in [o] + descendants(o):
            bpy.data.objects.remove(d)
    u.objects = [o for o in bpy.data.objects if o.name in bpy.context.scene.objects]
    u.modules = dict(mods)

    cable = bpy.data.objects.new('cable_2', None)
    bpy.context.scene.collection.objects.link(cable)
    cable.location = center_of(cable_parts)
    bpy.context.view_layer.update()              # reparent() needs the empty's new matrix
    for o in cable_parts:
        reparent(o, cable)

    # --- copies: boards 3..8 and their cables, each one pitch further along -x
    cables = {2: cable}
    for k in range(3, N_BOARDS + 1):
        b = duplicate(mods[2], mods[2].parent)
        shift(b, Vector((-(k - 2) * PITCH, 0, 0)))
        u.modules[k] = b
        c = duplicate(cable)
        shift(c, Vector((-(k - 2) * PITCH, 0, 0)))
        cables[k] = c
    bpy.context.view_layer.update()
    u.objects = [o for o in bpy.data.objects if o.name in bpy.context.scene.objects]

    # --- place the whole chain: centred along x, resting on the floor (z = -4 mm)
    lo, hi = u.bounds()
    d = Vector((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -4 * MM - lo.z + 0.1 * MM))
    u.root.location += d
    for c in cables.values():
        c.location += d
    bpy.context.view_layer.update()

    u.restyle()
    u.set_plates('black')
    u.setup_leds()
    s.stage(floor=True)
    s.camera_rig()

    # --- the boards arrive
    def arrive(k, start, dur, drop_at, led_at, color):
        b, c = u.modules[k], cables[k]
        move(b, 1, AWAY + BELOW)                 # parked out of sight until it comes in
        move(b, start - 1, AWAY + BELOW)
        move(b, start, AWAY)
        move(b, start + dur)
        move(c, 1, BELOW)
        move(c, drop_at - 1, BELOW)
        move(c, drop_at, (0, 0, 0.05))
        move(c, drop_at + 10)
        u.led(k, led_at, color)

    def leave(k, start, dur):
        b, c = u.modules[k], cables[k]
        move(c, start - 8)
        move(c, start, (0, 0, 0.05))
        move(c, start + 1, BELOW)
        move(b, start)
        move(b, start + dur, AWAY)
        move(b, start + dur + 1, AWAY + BELOW)
        u.led(k, start - 8, None)

    def hue(k):
        h = 0.5 + 0.35 * (k - 1) / (N_BOARDS - 1)          # cyan -> blue -> magenta
        return colorsys.hsv_to_rgb(h, 0.9, 1.0)

    u.led(1, 1, hue(1))
    timing = {2: (40, 55, 100, 116)}
    for i, k in enumerate(range(3, N_BOARDS + 1)):
        st = 160 + 12 * i
        timing[k] = (st, 22, st + 20, st + 30)
    for k, (st, dur, drop, lit) in timing.items():
        arrive(k, st, dur, drop, lit, hue(k))
        leave(k, 290 + 5 * (N_BOARDS - k), 20 if k > 2 else 26)

    # --- camera
    bpy.context.view_layer.update()

    def board_pos(k):
        lo, hi = u.bounds(u.modules[k])
        return Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, 0.018))

    b1, b2 = board_pos(1), board_pos(2)                 # rest positions (frame 0 = arrived)
    s.scene.frame_set(250)
    b1, b2 = board_pos(1), board_pos(2)
    chain = (b1 + board_pos(N_BOARDS)) / 2
    pair = (b1 + b2) / 2
    s.camera_path([
        (1, 45,    P(b1, -30, 0.30, 30, 5.6, 50), P(b1, -22, 0.28, 33, 5.6, 50)),
        (70, 140,  P(pair, -12, 0.42, 34, 5.6, 45), P(pair + Vector((-0.02, 0, 0)), -2, 0.40, 38, 5.6, 45)),
        (165, 290, P(chain + Vector((0.10, 0, 0)), -24, 0.88, 30, 5.6, 35),
                   P(chain + Vector((-0.04, 0, 0)), -8, 0.82, 36, 5.6, 35)),
    ])
    s.scene.frame_set(1)
