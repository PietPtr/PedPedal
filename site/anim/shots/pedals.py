"""Shot 1, "Your MIDI pedals": the assembled 4-button unit (black acrylic) seen from several
angles in one loop.

Module 3 is set to momentary: its LED is red only while the switch is held. Module 2 is set to
latching: each press toggles its green LED. Green is on at the start of the loop (so the wide
shots show it lit), goes off at the first press in its close-up and comes back on at the second.

Timeline (30 fps, 12 s). The camera holds (drifting slowly) and swoops between holds:
    1- 70   hold: low hero view from the front left, 35 mm; one momentary press
   70- 95   swoop in to the momentary switch
   95-160   hold: close on module 3 (momentary), 60 mm: a press and a double tap, red
  160-180   quick sideways move
  180-245   hold: close on module 2 (latching), from the right: off, then on again
  245-275   pull up and out
  275-335   hold: high wide view, turning; one more momentary press
  335-361   drop back down to the start
"""
from mathutils import Vector

from studio import MM

M, L = 3, 2          # momentary (red) and latching (green) modules; module 1 is the right end


def P(target, az, dist, elev, fstop, lens):
    return dict(target=target, az=az, dist=dist, elev=elev, fstop=fstop, lens=lens)


def build(s):
    s.set_frames(360)
    u = s.unit('assembly_4')
    u.center()
    u.apply_default_look('black')
    s.stage(floor=True)
    s.camera_rig()

    def aim(k):
        """Between the switch and its LED, a little below the plunger top: frames both."""
        sw, led = u.switch_pos(k), u.top_of(u.one('LED_D5', u.modules[k]))
        return (sw + led) / 2 - Vector((0, 0, 6 * MM))

    mid = Vector((0, 0, 0.03))
    s.camera_path([
        (1, 70,    P(mid + Vector((-0.03, 0, 0)), -42, 0.44, 11, 4.0, 35),
                   P(mid, -33, 0.40, 13, 4.0, 35)),
        (95, 160,  P(aim(M), -20, 0.27, 40, 8.0, 60),
                   P(aim(M), -9, 0.25, 45, 8.0, 60)),
        (180, 245, P(aim(L), 18, 0.25, 44, 8.0, 60),
                   P(aim(L), 30, 0.27, 38, 8.0, 60)),
        (275, 335, P(mid, 34, 0.78, 52, 4.5, 40),
                   P(mid, 18, 0.74, 47, 4.5, 40)),
    ])

    # momentary: lit only while held
    for down, up in ((30, 42), (108, 122), (134, 139), (144, 149), (300, 310)):
        u.press(M, down, up)
        u.led(M, down, 'red')
        u.led(M, up, None)

    # latching: on at the start, a press turns it off, the next on again
    u.led(L, 1, 'green')
    u.press(L, 200, 205)
    u.led(L, 200, None)
    u.press(L, 225, 230)
    u.led(L, 225, 'green')
