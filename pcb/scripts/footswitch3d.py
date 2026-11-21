"""3D model of the PBS24-202P footswitch (momentary DPDT, M12x0.75 bushing).

Writes pcb/footswitches.3dshapes/PBS24-202P.step. Dimensions are from the seller's drawing:
body 17.4 x 14.3 x 20.6, bushing M12 x 12 long, plunger d8 x 5, cap d10 x 5,
6 blade pins 1.2 x 0.8 sticking out 6 mm, pitch 7.1 along the long side, rows 4.65 apart.

Coordinates match the footprint: origin at the body centre, X along the 17.4 side,
Z = 0 at the board surface (the body sits flat on the board). Pad 1 is at (-7.1, -2.325)
in footprint coordinates; KiCad's footprint Y points down, the model's Y points up, so
the pin rows are mirrored, which doesn't matter for a symmetric part.

Run: uv run pcb/scripts/footswitch3d.py
"""
from pathlib import Path

import cadquery as cq

BODY_X, BODY_Y, BODY_H = 17.4, 14.3, 20.6
BUSH_D, BUSH_H, PITCH = 12.0, 12.0, 0.75
PLUNGER_D, PLUNGER_H = 8.0, 5.0
CAP_D, CAP_H = 10.0, 5.0
PIN_W, PIN_T, PIN_L = 1.2, 0.8, 6.0
PIN_DX, PIN_DY = 7.1, 4.65
FRAME_T = 0.4

OUT = Path(__file__).resolve().parent.parent / "footswitches.3dshapes" / "PBS24-202P.step"


def body():
    b = cq.Workplane("XY").box(BODY_X, BODY_Y, BODY_H - FRAME_T, centered=(True, True, False))
    b = b.edges("|Z").chamfer(0.5)
    # shallow recess on the long faces, like the moulding in the photo
    for s in (1, -1):
        cut = (cq.Workplane("XY").box(BODY_X - 4, 1.0, 8, centered=(True, True, False))
               .translate((0, s * (BODY_Y / 2), 3)))
        b = b.cut(cut)
    return b


def frame():
    """Sheet-metal clip: top plate with a hole for the bushing, straps down the long faces."""
    top = (cq.Workplane("XY").workplane(offset=BODY_H - FRAME_T)
           .rect(BODY_X, BODY_Y).extrude(FRAME_T)
           .faces(">Z").workplane().hole(BUSH_D - 1))
    strap_w, strap_h = 3.0, 7.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            strap = (cq.Workplane("XY")
                     .box(strap_w, FRAME_T, strap_h, centered=(True, True, False))
                     .translate((sx * (BODY_X / 2 - 2.5), sy * (BODY_Y / 2 + FRAME_T / 2),
                                 BODY_H - strap_h)))
            top = top.union(strap)
    return top


def bushing():
    """M12 bushing: thread drawn as rings (not a helix), with the flat keyway seen in the drawing."""
    r_out, depth = BUSH_D / 2, 0.4
    n = int(BUSH_H / PITCH)
    pts = [(0, 0), (r_out - depth, 0)]
    for i in range(n):
        z = i * PITCH
        pts += [(r_out, z + PITCH / 2), (r_out - depth, z + PITCH)]
    if n * PITCH < BUSH_H:
        pts.append((r_out - depth, BUSH_H))
    pts.append((0, BUSH_H))
    b = cq.Workplane("XZ").polyline(pts).close().revolve(360, (0, 0, 0), (0, 1, 0))
    key = cq.Workplane("XY").box(2.0, 1.0, BUSH_H, centered=(True, False, False)).translate((0, r_out - 0.5, 0))
    b = b.cut(key)
    return b.translate((0, 0, BODY_H))


def plunger():
    z0 = BODY_H + BUSH_H
    p = cq.Workplane("XY").workplane(offset=z0).circle(PLUNGER_D / 2).extrude(PLUNGER_H)
    cap = (cq.Workplane("XY").workplane(offset=z0 + PLUNGER_H).circle(CAP_D / 2).extrude(CAP_H)
           .faces(">Z").edges().fillet(1.0))
    return p.union(cap)


def pins():
    w = None
    for ix in (-1, 0, 1):
        for iy in (-1, 1):
            p = (cq.Workplane("XY").box(PIN_W, PIN_T, PIN_L, centered=(True, True, False))
                 .edges("<Z").chamfer(0.25)
                 .translate((ix * PIN_DX, iy * PIN_DY / 2, -PIN_L)))
            w = p if w is None else w.union(p)
    return w


def main():
    metal = cq.Color(0.55, 0.56, 0.58)
    a = cq.Assembly(name="PBS24-202P")
    a.add(body(), name="body", color=cq.Color(0.08, 0.08, 0.08))
    a.add(frame(), name="frame", color=metal)
    a.add(bushing(), name="bushing", color=metal)
    a.add(plunger(), name="plunger", color=metal)
    a.add(pins(), name="pins", color=cq.Color(0.7, 0.7, 0.68))
    OUT.parent.mkdir(exist_ok=True)
    a.export(str(OUT))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
