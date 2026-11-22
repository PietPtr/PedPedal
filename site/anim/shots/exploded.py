"""Shot 2, "Open Hardware": the 4-button unit comes apart into its layers (feet, back plate,
spacers, boards, cables, standoffs, nuts, front plate, screws; the side walls slide outwards),
the camera tours the boards, then it all goes back together.

No two parts may pass through each other, so:
- the walls come apart first, along their pins (filament pins along x, 6 mm into each side of
  every joint): the U-shaped end pieces slide out left and right; once the pins are clear the
  straight front and back pieces split at their middle joint (in x), then move out in y, off the
  plates' edges. They go back together the same way in reverse, last;
- every layer moves along the same eased curve, scaled by its lift, and lifts grow from bottom
  to top. The explode starts at the top layer and the reassembly at the bottom one, so a layer
  is never caught up by the one below it: the gaps between the layers only open while
  exploding, and only close while reassembling.

Timeline (30 fps, 12 s):
    1- 35   hold: assembled, from the front left
   26- 50   wall ends slide out left and right
   38- 66   straight walls: split in x, then out in y
   54-138   explode, layer after layer (top first)
   50-110   hold: wide, watching it open up
  130-185   hold: close on module 1 (the Pico board)
  205-265   hold: low along the boards, between the plates
  256-340   reassemble (bottom layer first)
  285-345   hold: high wide view while it closes
  330-354   straight walls: in in y, then together in x
  344-360   wall ends slide back in
"""
from mathutils import Vector

from studio import MM, base_name, move

SCALE = 1.0           # overall size of the explosion

# (name prefix, lift in mm). The lift must grow with the part's height in the stack (as listed,
# bottom to top: rest heights in the comments); parts with the same lift move together.
LAYERS = [
    ('foot_', 0),                   # 0-4
    ('screw_bottom', 12),           # head 2.4-4 under the back plate, shank up into the spacer
    ('back_plate', 25),             # 4-7
    ('pcb_spacer', 45),             # 7-18
    ('module_', 62),                # PCB 12-13.5, switch up to 56
    ('led_spacer', 62),             # rides with its board, so the LED stays on it
    ('socket_', 84),                # 16.6-25.1, on the board's headers
    ('ribbon_', 84),
    ('standoff', 100),              # 13.6-38.6, board to front plate
    ('switch_nut_low', 114),        # 35.6-37.8
    ('switch_washer_low', 120),     # 37.8-38.6
    ('front_plate', 130),           # 38.6-41.6
    ('switch_washer_top', 146),     # 41.6-42.4
    ('switch_nut_top', 154),        # 42.4-44.6
    ('screw_top', 168),             # head on the front plate, shank down into the standoff
]
END_PUSH = 95                       # mm: the U-shaped wall ends, out along x
SIDE_SPLIT, SIDE_PUSH = 14, 80      # mm: the straight walls, off their middle pins (x), then out (y)

EXPLODE, REASSEMBLE, STEP, DUR = 54, 256, 4, 40     # first start, frames between layers, length

M, L = 3, 2


def P(target, az, dist, elev, fstop, lens):
    return dict(target=target, az=az, dist=dist, elev=elev, fstop=fstop, lens=lens)


def build(s):
    s.set_frames(360)
    u = s.unit('assembly_4')
    u.center()
    u.apply_default_look('black')
    s.stage(floor=True)
    s.camera_rig()

    top = u.root.children[0].children           # the parts directly under footswitch_4
    lifts = sorted({lift for _, lift in LAYERS if lift})
    for o in top:
        n = base_name(o)
        if n.startswith('wall_'):
            c = sum((o.matrix_world @ Vector(b) for b in o.bound_box), Vector()) / 8
            sx, sy = (1 if c.x > 0 else -1), (1 if c.y > 0 else -1)
            move(o, 1)
            if n.startswith('wall_end'):
                off = Vector((sx * END_PUSH * MM * SCALE, 0, 0))
                for f, v in ((26, None), (50, off), (344, off), (360, None)):
                    move(o, f, v or (0, 0, 0))
            else:
                split = Vector((sx * SIDE_SPLIT * MM * SCALE, 0, 0))
                out = split + Vector((0, sy * SIDE_PUSH * MM * SCALE, 0))
                for f, v in ((38, None), (48, split), (66, out), (330, out), (344, split), (354, None)):
                    move(o, f, v or (0, 0, 0))
            continue
        lift = next((lift for prefix, lift in LAYERS if n.startswith(prefix)), None)
        if lift is None:
            print('exploded.py: no layer for', n)
            continue
        if not lift:
            continue
        r = lifts.index(lift)                    # 0 = lowest moving layer
        go = EXPLODE + STEP * (len(lifts) - 1 - r)
        back = REASSEMBLE + STEP * r
        off = Vector((0, 0, lift * MM * SCALE))
        move(o, 1)
        move(o, go)
        move(o, go + DUR, off)
        move(o, back, off)
        move(o, back + DUR)

    mod1 = u.modules[1]
    lo, hi = u.bounds(mod1)
    pico = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, 0.0)) + Vector((0, 0, (12 + 62 + 10) * MM * SCALE))
    mid_open = Vector((0, 0, 0.10 * SCALE))
    boards = Vector((0, 0, (12 + 62 + 6) * MM * SCALE))
    mid = Vector((0, 0, 0.03))
    s.camera_path([
        (1, 35,    P(mid, -40, 0.60, 16, 4.0, 40), P(mid, -36, 0.58, 18, 4.0, 40)),
        (50, 110,  P(mid_open, -34, 0.78, 16, 4.0, 35), P(mid_open, -22, 0.74, 19, 4.0, 35)),
        (130, 185, P(pico, 28, 0.30, 34, 5.6, 55), P(pico, 44, 0.28, 30, 5.6, 55)),
        (205, 265, P(boards + Vector((0.06, 0, 0)), -6, 0.34, 9, 5.6, 45),
                   P(boards + Vector((-0.10, 0, 0)), -14, 0.34, 11, 5.6, 45)),
        (285, 345, P(mid_open, 30, 0.85, 34, 4.0, 38), P(mid + Vector((0, 0, 0.02)), 14, 0.75, 28, 4.0, 38)),
    ])

    u.led(L, 1, 'green')                         # as in shot 1: module 2 latched on
