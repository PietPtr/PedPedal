"""Look-development shot for the pipeline: the 4-button unit (black plates) on a slow full turn.
Module 3 is a momentary switch (red while held), module 2 a latching one (green, toggles)."""


def build(s):
    s.set_frames(240)                       # 8 s at 30 fps
    u = s.unit('assembly_4')
    u.center()
    u.apply_default_look('black')
    s.stage(floor=True)
    s.camera_rig(target=(0, 0, 0.03), dist=0.62, height=0.30, lens=50, fstop=4.0)
    s.orbit(-30, 330)

    # momentary: lit only while held
    for down, up in ((30, 48), (140, 152), (170, 182)):
        u.press(3, down, up)
        u.led(3, down, 'red')
        u.led(3, up, None)
    # latching: each press toggles
    u.led(2, 1, None)
    u.press(2, 80, 86)
    u.led(2, 80, 'green')
    u.press(2, 205, 211)
    u.led(2, 205, None)
