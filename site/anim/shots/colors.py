"""Shot 4, "Customizable": the 4-button unit hovers above the floor, turning and tilting, while
its look changes: acrylic plates, 3D-printed walls and LED colours together (LOOKS: clear with
white walls, matte white with white walls, shiny black with black walls, red with bordeaux walls,
and back to clear). Each change is a glowing seam that sweeps diagonally across the unit, turning
it over to the new look behind it; each LED switches colour as the seam passes it.

The turn is fastest during each wipe (a whole-cycle sine on top of one steady turn per loop),
so every finish gets a slow, close look and the changes have some energy.

Timeline (30 fps, 12 s): a wipe every 90 frames, centred on 80, 170, 260 and 350.
"""
import math

import bpy
from mathutils import Vector

from studio import ACRYLIC, MM, key, set_interp, thin_refraction

# (plate finish, wall colour, LED colours of modules 2 and 4), in order; the loop ends where it starts
LOOKS = [
    ('clear',       'white',    ('cyan', 'blue')),
    ('white_matte', 'white',    ('green', 'cyan')),
    ('black',       'black',    ('magenta', 'blue')),
    ('red',         'bordeaux', ('yellow', 'white')),
    ('clear',       'white',    ('cyan', 'blue')),
]
WALLS = {                            # 3D-printed PLA
    'white':    (0.26, 0.26, 0.255),
    'black':    (0.018, 0.019, 0.022),
    'bordeaux': (0.03, 0.0012, 0.004),
}
LIT = (2, 4)                         # modules with their LED on
WIPES = [80, 170, 260, 350]          # wipe centre frames; look i+1 takes over at WIPES[i]
WIPE_LEN = 20                        # frames for the seam to cross
SWEEP = (-260.0, 260.0)              # seam position (mm along the diagonal) at start and end
SEAM = (0.55, 0.75, 1.0)             # seam glow colour
GLOW = 12.0


def P(target, az, dist, elev, fstop, lens):
    return dict(target=target, az=az, dist=dist, elev=elev, fstop=fstop, lens=lens)


def seams(nt, root, center):
    """The seam chain in a node tree: one Value node per wipe (the seam's position, mm along
    x + 0.4 y in the unit's own coordinates, so the seam turns with it). Returns the Value nodes,
    a 0..1 factor per seam (1 behind it: the new look) and the glow of all seams together."""
    nodes, link = nt.nodes, nt.links.new

    def math(op, a, b):
        m = nodes.new('ShaderNodeMath')
        m.operation = op
        for i, v in enumerate((a, b)):
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            else:
                link(v, m.inputs[i])
        return m.outputs[0]

    tc = nodes.new('ShaderNodeTexCoord')
    tc.object = root
    sep = nodes.new('ShaderNodeSeparateXYZ')
    link(tc.outputs['Object'], sep.inputs[0])
    # x + 0.4 y, minus the same at the centre (the unit's own coordinates start at a corner)
    diag = math('SUBTRACT', math('ADD', math('MULTIPLY', sep.outputs['Y'], 0.4), sep.outputs['X']),
                center[0] + 0.4 * center[1])
    edges, facs, glow = [], [], None
    for _ in WIPES:
        edge = nodes.new('ShaderNodeValue')
        edges.append(edge)
        d = math('SUBTRACT', edge.outputs[0], diag)
        fac = nodes.new('ShaderNodeMapRange')                # clamp((d + 3 mm) / 6 mm)
        fac.inputs['From Min'].default_value, fac.inputs['From Max'].default_value = -3.0, 3.0
        link(d, fac.inputs['Value'])
        facs.append(fac.outputs['Result'])
        band = nodes.new('ShaderNodeMapRange')               # a narrow bump around d = 0
        band.interpolation_type = 'SMOOTHSTEP'
        band.inputs['From Min'].default_value, band.inputs['From Max'].default_value = 9.0, 0.0
        link(math('ABSOLUTE', d, 0.0), band.inputs['Value'])
        glow = band.outputs['Result'] if glow is None else math('MAXIMUM', glow, band.outputs['Result'])
    return edges, facs, glow


def add_glow(nt, shader, glow, strength=GLOW):
    """shader + the seam glow, into the material output."""
    nodes, link = nt.nodes, nt.links.new
    em = nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = (*SEAM, 1)
    st = nodes.new('ShaderNodeMath')
    st.operation = 'MULTIPLY'
    st.inputs[1].default_value = strength
    link(glow, st.inputs[0])
    link(st.outputs[0], em.inputs['Strength'])
    add = nodes.new('ShaderNodeAddShader')
    link(shader, add.inputs[0])
    link(em.outputs[0], add.inputs[1])
    link(add.outputs[0], nodes['Material Output'].inputs['Surface'])


def plate_material(root, center):
    """A Principled BSDF per finish, mixed by the seams, plus the seam glow."""
    mat = bpy.data.materials.new('acrylic_wipe')
    nt = mat.node_tree
    nt.nodes.remove(nt.nodes['Principled BSDF'])
    edges, facs, glow = seams(nt, root, center)

    def shader(finish):
        b = nt.nodes.new('ShaderNodeBsdfPrincipled')
        for k, v in ACRYLIC[finish].items():
            if not k.startswith('Subsurface'):
                b.inputs[k].default_value = v
        if finish == 'white_matte':
            b.inputs['Base Color'].default_value = (0.24, 0.24, 0.235, 1)
        return b.outputs[0]

    cur = shader(LOOKS[0][0])
    # (no subsurface in here: SSS on the plates during a wipe hangs the Intel iGPU)
    for fac, (finish, _, _) in zip(facs, LOOKS[1:]):
        mix = nt.nodes.new('ShaderNodeMixShader')
        nt.links.new(fac, mix.inputs['Fac'])
        nt.links.new(cur, mix.inputs[1])
        nt.links.new(shader(finish), mix.inputs[2])
        cur = mix.outputs[0]
    add_glow(nt, cur, glow)
    thin_refraction(mat)
    return mat, edges


def wall_material(root, center):
    """The walls' own material (print lines and all), with its base colour switched by the
    seams and the seam glow added."""
    mat = bpy.data.materials['wall']
    nt = mat.node_tree
    b = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    edges, facs, glow = seams(nt, root, center)
    cur = None
    for i, (_, wall, _) in enumerate(LOOKS):
        rgb = nt.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = (*WALLS[wall], 1)
        if cur is None:
            cur = rgb.outputs[0]
            continue
        mix = nt.nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        nt.links.new(facs[i - 1], mix.inputs['Factor'])
        nt.links.new(cur, mix.inputs['A'])
        nt.links.new(rgb.outputs[0], mix.inputs['B'])
        cur = mix.outputs['Result']
    nt.links.new(cur, b.inputs['Base Color'])
    b.inputs['Roughness'].default_value = 0.6
    add_glow(nt, b.outputs[0], glow, GLOW * 0.6)
    return mat, edges


def build(s):
    N = 360
    s.set_frames(N)
    u = s.unit('assembly_4')
    u.center()
    u.apply_default_look('black')
    s.raytrace = True                                # for the clear acrylic, even in draft
    inv = u.root.matrix_world.inverted()
    lo, hi = u.bounds()
    mid_local = inv @ ((lo + hi) / 2)
    mat, edges = plate_material(u.root, mid_local)
    for o in u.find('front_plate') + u.find('back_plate'):
        o.data.materials.clear()
        o.data.materials.append(mat)
    wmat, wedges = wall_material(u.root, mid_local)
    s.stage(floor=True)
    s.camera_rig()

    # seams: each sweeps once, from beyond one end of the unit to beyond the other
    for e, c in zip(edges + wedges, WIPES + WIPES):
        sock = e.outputs[0]
        for f, v in ((1, SWEEP[0]), (c - WIPE_LEN // 2, SWEEP[0]), (c + WIPE_LEN // 2, SWEEP[1])):
            key(sock, 'default_value', f, v, 'LINEAR')
    set_interp(mat.node_tree, 'LINEAR')
    set_interp(wmat.node_tree, 'LINEAR')

    # the unit: hovering, a steady turn plus a surge at every wipe, a gentle tilt and bob
    r = bpy.data.objects.new('pivot', None)          # turn about the unit's centre, not its corner
    s.scene.collection.objects.link(r)
    r.location = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, 0)
    bpy.context.view_layer.update()
    mw = u.root.matrix_world.copy()
    u.root.parent = r
    u.root.matrix_world = mw
    base = r.location.copy()
    phase = 2 * math.pi * (WIPES[0] - 1) / (N / 4)
    for f in range(1, N + 2):
        t = 2 * math.pi * (f - 1) / N
        turn = -30 + 360 * (f - 1) / N + 12.5 * math.sin(4 * t - phase)
        tilt_x = 7 * math.sin(2 * t + 0.6) + 2 * math.sin(5 * t)
        tilt_y = 4 * math.sin(3 * t + 1.9)
        z = 38 * MM + 6 * MM * math.sin(2 * t + 1.1)
        key(r, 'rotation_euler', f, (math.radians(tilt_x), math.radians(tilt_y), math.radians(turn)), 'LINEAR')
        key(r, 'location', f, base + Vector((0, 0, z)), 'LINEAR')

    # LEDs: each changes colour as the seam passes over it
    bpy.context.view_layer.update()
    for k in LIT:
        lo_m, hi_m = u.bounds(u.modules[k])
        p = u.root.matrix_world.inverted() @ ((lo_m + hi_m) / 2) - mid_local   # unit's mm
        at = p.x + 0.4 * p.y                             # its position along the seam's diagonal
        u.led(k, 1, LOOKS[0][2][LIT.index(k)])
        for c, (_, _, leds) in zip(WIPES, LOOKS[1:]):
            f = c - WIPE_LEN / 2 + WIPE_LEN * (at - SWEEP[0]) / (SWEEP[1] - SWEEP[0])
            u.led(k, round(f), leds[LIT.index(k)])

    mid = Vector((0, 0, 0.06))
    s.camera_path([
        (1, 150,   P(mid, -18, 0.50, 24, 4.0, 40), P(mid, -8, 0.47, 28, 4.0, 40)),
        (190, 330, P(mid + Vector((0, 0, -0.01)), 10, 0.44, 22, 4.0, 45),
                   P(mid + Vector((0, 0, -0.01)), 22, 0.46, 25, 4.0, 45)),
    ])
