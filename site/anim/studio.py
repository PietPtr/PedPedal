"""Blender-side toolkit for the product animations: the dark, glowy studio, the unit imported from
the CAD export, its materials, the LEDs, the switch plungers and the camera rig.

Runs inside Blender (imported by main.py). Shots in shots/*.py get a Studio and build their
animation with it. Scene units are metres. The GLBs from mech/assembly.py are in millimetres and
are scaled down on import.
"""
import math
import os
import re
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
MECH_OUT = ROOT / 'mech' / 'out'
MM = 0.001

# Render presets. 'draft' is meant for a weak laptop GPU: a few seconds a frame.
# vol_samples is for the optional haze (stage(haze=...)); 0 leaves the haze out altogether.
# step renders only every step-th frame of a loop, so draft runs at 15 fps with the shots'
# 30 fps timing unchanged.
QUALITY = {
    'draft':   dict(res=(640, 360),   samples=16,  raytrace=False, glare='Low',    motion_blur=False,
                    vol_samples=0, step=2),
    'preview': dict(res=(960, 540),   samples=32,  raytrace=False, glare='Medium', motion_blur=False,
                    vol_samples=8, step=1),
    'final':   dict(res=(2560, 1440), samples=128, raytrace=True,  glare='High',   motion_blur=True,
                    vol_samples=64, step=1),
}

# The front/back plate finishes. Each is a set of Principled BSDF inputs.
ACRYLIC = {
    # clear needs raytracing (Studio.raytrace = True), even in draft: without it EEVEE's
    # transmission shows the world probe, not the parts behind, with blocky artefacts. (Alpha
    # instead of transmission hangs the Intel iGPU.)
    'clear':       {'Base Color': (0.95, 0.97, 1.0, 1), 'Roughness': 0.02, 'IOR': 1.49,
                    'Transmission Weight': 1.0, 'Coat Weight': 0.0},
    'black':       {'Base Color': (0.004, 0.004, 0.005, 1), 'Roughness': 0.04, 'IOR': 1.49,
                    'Coat Weight': 1.0, 'Coat Roughness': 0.02},
    'white_matte': {'Base Color': (0.36, 0.36, 0.355, 1), 'Roughness': 0.55, 'IOR': 1.49,
                    'Subsurface Weight': 0.25, 'Subsurface Radius': (2.0, 2.0, 2.0),
                    'Subsurface Scale': 0.002},
    'pink':        {'Base Color': (0.55, 0.018, 0.17, 1), 'Roughness': 0.06, 'IOR': 1.49,
                    'Subsurface Weight': 0.35, 'Subsurface Radius': (1.0, 0.2, 0.5),
                    'Subsurface Scale': 0.003, 'Coat Weight': 0.6, 'Coat Roughness': 0.03},
    'red':         {'Base Color': (0.22, 0.0, 0.002, 1), 'Roughness': 0.04, 'IOR': 1.49,
                    'Coat Weight': 1.0, 'Coat Roughness': 0.02},
}

LED_COLORS = {
    'red':   (1.0, 0.02, 0.01),
    'green': (0.05, 1.0, 0.08),
    'blue':  (0.05, 0.15, 1.0),
    'white': (1.0, 0.85, 0.7),
    'yellow':  (1.0, 0.55, 0.02),
    'cyan':    (0.05, 0.85, 1.0),
    'magenta': (1.0, 0.05, 0.6),
}   # the LED's channels are on/off: these 7 are all it can show

_SUFFIX = re.compile(r'\.\d{3}$')


def aspect():
    """Frame aspect ratio from $ANIM_ASPECT ('16x9', '21x9', '32x9'; set by render.py
    --aspect). The vertical framing is the same for all of them."""
    w, h = os.environ.get('ANIM_ASPECT', '16x9').split('x')
    return float(w) / float(h)


def base_name(obj):
    """Object name without Blender's '.001' duplicate suffix."""
    return _SUFFIX.sub('', obj.name)


def descendants(obj):
    out = []
    stack = list(obj.children)
    while stack:
        o = stack.pop()
        out.append(o)
        stack.extend(o.children)
    return out


def principled(name, **inputs):
    mat = bpy.data.materials.new(name)
    bsdf = mat.node_tree.nodes['Principled BSDF']
    for k, v in inputs.items():
        bsdf.inputs[k].default_value = v
    return mat


def bsdf(mat):
    return mat.node_tree.nodes['Principled BSDF']


def key(obj, path, frame, value, interp='BEZIER', index=-1):
    """Set `obj.path` to `value` and keyframe it. `obj` is any ID or struct (object, node
    socket, light data)."""
    target, attr = obj, path
    if '.' in path:
        head, attr = path.rsplit('.', 1)
        for part in head.split('.'):
            target = getattr(target, part)
    setattr(target, attr, value)
    target.keyframe_insert(attr, frame=frame, index=index)
    set_interp(obj, interp)


def set_interp(obj, interp, data_path=None):
    """Interpolation for the keyframes on `obj` (all, or one data path)."""
    owner = obj.id_data if hasattr(obj, 'id_data') else obj
    ad = owner.animation_data
    if not ad or not ad.action:
        return
    for fc in _fcurves(ad):
        if data_path is None or fc.data_path.endswith(data_path):
            for kp in fc.keyframe_points:
                kp.interpolation = interp


def _fcurves(ad):
    """F-curves of an action, for both the layered (4.4+) and the old action layout."""
    act = ad.action
    if hasattr(act, 'layers') and act.layers:
        slot = ad.action_slot
        for layer in act.layers:
            for strip in layer.strips:
                bag = strip.channelbag(slot) if slot else None
                if bag:
                    yield from bag.fcurves
    elif hasattr(act, 'fcurves'):
        yield from act.fcurves


def move(obj, frame, offset=(0, 0, 0), interp='BEZIER'):
    """Keyframe `obj` at its rest location plus a world-space `offset` (metres). The rest
    location is the one it had at the first call."""
    if 'rest' not in obj:
        obj['rest'] = list(obj.location)
    m = obj.parent.matrix_world @ obj.matrix_parent_inverse if obj.parent else obj.matrix_parent_inverse
    key(obj, 'location', frame, Vector(obj['rest']) + m.to_3x3().inverted() @ Vector(offset), interp)


def make_cyclic(obj):
    """Repeat the keyframes of `obj` forever (Cycles modifier), for loops."""
    owner = obj.id_data if hasattr(obj, 'id_data') else obj
    for fc in _fcurves(owner.animation_data):
        if not any(m.type == 'CYCLES' for m in fc.modifiers):
            fc.modifiers.new('CYCLES')


# ---------------------------------------------------------------- the unit

class Unit:
    """One imported assembly GLB, under an empty that scales it to metres."""

    def __init__(self, glb, name):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(glb))
        new = [o for o in bpy.data.objects if o not in before]
        self.root = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(self.root)
        for o in new:
            if o.parent is None:
                o.parent = self.root
        self.root.scale = (MM, MM, MM)
        bpy.context.view_layer.update()
        self.objects = new
        self.modules = {}
        for o in new:
            m = re.fullmatch(r'module_(\d+)', base_name(o))
            if m:
                self.modules[int(m.group(1))] = o
        self.leds = {}

    def find(self, name, under=None):
        """All objects (below `under`, default the whole unit) whose base name starts with `name`."""
        pool = descendants(under) if under else self.objects
        return [o for o in pool if base_name(o).startswith(name)]

    def one(self, name, under=None):
        hits = self.find(name, under)
        if len(hits) != 1:
            raise KeyError(f'{name!r}: {len(hits)} matches')
        return hits[0]

    def meshes(self, under=None):
        pool = descendants(under) if under else self.objects
        return [o for o in pool if o.type == 'MESH']

    def bounds(self, under=None):
        pts = [o.matrix_world @ Vector(c) for o in self.meshes(under) for c in o.bound_box]
        lo = Vector([min(p[i] for p in pts) for i in range(3)])
        hi = Vector([max(p[i] for p in pts) for i in range(3)])
        return lo, hi

    def center(self):
        """Move the unit so its footprint is centred on the origin, resting on z = 0."""
        bpy.context.view_layer.update()
        lo, hi = self.bounds()
        self.root.location -= Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
        bpy.context.view_layer.update()

    # -- switches and LEDs ------------------------------------------------------------

    def plunger(self, k):
        return self.one('plunger', self.modules[k])

    def top_of(self, obj):
        """World position of the centre of the top of `obj`'s bounding box."""
        bpy.context.view_layer.update()
        pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        return Vector((sum(p.x for p in pts) / 8, sum(p.y for p in pts) / 8, max(p.z for p in pts)))

    def switch_pos(self, k):
        """World position of the top of module k's footswitch plunger (at rest)."""
        return self.top_of(self.plunger(k))

    def press(self, k, down, up, travel=2.5 * MM, ramp=3):
        """Plunger of module `k` goes down at frame `down` and back up at `up`. `ramp` frames
        for the movement."""
        p = self.plunger(k)
        if 'rest' not in p:
            p['rest'] = list(p.location)
        rest = Vector(p['rest'])
        # world-space "down" in the plunger's parent space (which is in mm and maybe rotated)
        delta = p.parent.matrix_world.to_3x3().inverted() @ Vector((0, 0, -travel))
        for f, pos in ((down - ramp, rest), (down, rest + delta), (up, rest + delta),
                       (up + ramp, rest)):
            key(p, 'location', f, pos)

    def setup_leds(self, lights=True):
        """Give every module's LED lens its own emissive material (off), plus a small point
        light just above it so the glow spills onto the plate."""
        for k, mod in self.modules.items():
            holder = self.one('LED_D5', mod)
            lens = [o for o in descendants(holder) if o.type == 'MESH'][0]
            mat = principled(f'led_{self.root.name}_{k}', **{
                'Base Color': (0.5, 0.5, 0.5, 1), 'Roughness': 0.2,
                'Transmission Weight': 0.8, 'Emission Color': (1, 1, 1, 1),
                'Emission Strength': 0.0})
            lens.material_slots[0].material = mat
            light = None
            if lights:
                lo, hi = (Vector([f(c[i] for c in [lens.matrix_world @ Vector(b) for b in lens.bound_box])
                                  for i in range(3)]) for f in (min, max))
                ld = bpy.data.lights.new(f'ledlight_{self.root.name}_{k}', 'POINT')
                ld.energy = 0.0
                ld.shadow_soft_size = 2.5 * MM
                ld.use_shadow = False   # spill only; tiny moving shadowed lights hang the iGPU
                light = bpy.data.objects.new(ld.name, ld)
                bpy.context.scene.collection.objects.link(light)
                light.location = (lo + hi) / 2 + Vector((0, 0, (hi.z - lo.z) / 2 + 0.5 * MM))   # at the dome tip
                light.parent = mod                  # follows the board when a shot moves it
                light.matrix_parent_inverse = mod.matrix_world.inverted()
                light.visible_camera = False
                light.visible_glossy = False   # spill only: no second 'LED' mirrored in the plate
            self.leds[k] = (mat, light)
            self.led(k, 1, None)               # all off until a shot says otherwise

    def led(self, k, frame, color=None, strength=8.0, interp='CONSTANT'):
        """Keyframe LED `k` at `frame`: a color name / RGB tuple, or None for off."""
        mat, light = self.leds[k]
        b = bsdf(mat)
        on = color is not None
        rgb = LED_COLORS.get(color, color) if on else None
        if on:
            key(b.inputs['Emission Color'], 'default_value', frame, (*rgb, 1), interp)
            if light:
                key(light.data, 'color', frame, rgb, interp)
        key(b.inputs['Emission Strength'], 'default_value', frame, strength if on else 0.0, interp)
        if light:
            key(light.data, 'energy', frame, 0.4 * strength / 8 if on else 0.0, interp)

    # -- materials --------------------------------------------------------------------

    def set_plates(self, finish):
        """Front and back plate finish, one of ACRYLIC."""
        mat = bpy.data.materials.get(f'acrylic_{finish}') or principled(f'acrylic_{finish}', **ACRYLIC[finish])
        thin_refraction(mat)
        for o in self.find('front_plate') + self.find('back_plate'):
            o.data.materials.clear()
            o.data.materials.append(mat)

    def restyle(self):
        """Turn the flat CAD colours into studio materials, by part name and colour."""
        by_part = {
            'standoff': 'brass', 'pcb_spacer': 'brass', 'screw_': 'black_oxide', 'switch_nut': 'steel',
            'switch_washer': 'steel', 'bushing': 'steel', 'frame': 'steel', 'plunger': 'steel',
            'pins': 'steel', 'foot_': 'rubber', 'wall_': 'wall', 'led_spacer': 'nylon',
            'ribbon': 'ribbon', 'socket_': 'plastic_black', 'body': 'plastic_black',
        }
        lib = {
            'brass': principled('brass', **{'Base Color': (0.85, 0.62, 0.28, 1), 'Metallic': 1.0, 'Roughness': 0.28}),
            'steel': principled('steel', **{'Base Color': (0.6, 0.61, 0.63, 1), 'Metallic': 1.0, 'Roughness': 0.38}),
            'black_oxide': principled('black_oxide', **{'Base Color': (0.06, 0.06, 0.065, 1), 'Metallic': 1.0,
                                                        'Roughness': 0.35}),
            'rubber': principled('rubber', **{'Base Color': (0.02, 0.02, 0.02, 1), 'Roughness': 0.8}),
            'wall': print_lines(principled('wall', **{'Base Color': (0.018, 0.019, 0.022, 1), 'Roughness': 0.35})),
            # no subsurface: on a small part seen close up, EEVEE's SSS hangs the Intel iGPU
            'nylon': principled('nylon', **{'Base Color': (0.7, 0.7, 0.68, 1), 'Roughness': 0.5}),
            'ribbon': principled('ribbon', **{'Base Color': (0.07, 0.07, 0.075, 1), 'Roughness': 0.75,
                                              'Specular IOR Level': 0.2}),
            'plastic_black': principled('plastic_black', **{'Base Color': (0.015, 0.015, 0.015, 1), 'Roughness': 0.35}),
        }
        done = set()
        for o in self.meshes():
            names = [base_name(a) for a in [o] + _ancestors(o)]
            part = next((v for k, v in by_part.items() for n in names if n.startswith(k)), None)
            if part:
                for s in o.material_slots:
                    s.material = lib[part]
                continue
            for s in o.material_slots:     # KiCad components: keep the colour, fix the finish
                m = s.material
                if m and m.name not in done and m.name.startswith('mat_'):
                    done.add(m.name)
                    _kicad_finish(m)

    def apply_default_look(self, finish='black'):
        self.restyle()
        self.set_plates(finish)
        self.setup_leds()


def print_lines(mat, layer=0.2, depth=1.0):
    """FDM layer lines on `mat`: a ridge every `layer` mm along the mesh's local Y, which is
    the assembly's up axis for the walls (they're printed standing). The lines use object
    coordinates (mm, before the unit's scale), so they move with the part. `depth` scales the
    bump. Each layer gets a slightly different height, like a real print."""
    nt = mat.node_tree
    n, link = nt.nodes.new, nt.links.new
    b = bsdf(mat)

    def math(op, *args):
        m = n('ShaderNodeMath')
        m.operation = op
        for i, v in enumerate(args):
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            else:
                link(v, m.inputs[i])
        return m.outputs[0]

    tc = n('ShaderNodeTexCoord')
    xyz = n('ShaderNodeSeparateXYZ')
    link(tc.outputs['Object'], xyz.inputs[0])
    t = math('DIVIDE', xyz.outputs['Y'], layer)
    # rounded bead per layer: sqrt(1 - (2f - 1)^2), with a sharp groove between beads
    u = math('SUBTRACT', math('MULTIPLY', math('FRACT', t), 2.0), 1.0)
    bead = math('SQRT', math('MAXIMUM', math('SUBTRACT', 1.0, math('POWER', u, 2.0)), 0.0))
    # per layer: a random value (extrusion varies a little from layer to layer)
    wn = n('ShaderNodeTexWhiteNoise')
    wn.noise_dimensions = '1D'
    link(math('FLOOR', t), wn.inputs['W'])
    jitter = wn.outputs['Value']
    # and a slow banding over a few mm of height (z wobble, flow drift)
    band = n('ShaderNodeTexNoise')
    band.noise_dimensions = '1D'
    band.inputs['Scale'].default_value = 1.0
    link(math('DIVIDE', t, 12.0), band.inputs['W'])
    amp = math('ADD', math('MULTIPLY_ADD', jitter, 0.3, 0.5), math('MULTIPLY', band.outputs['Fac'], 0.4))
    height = math('MULTIPLY', bead, amp)
    bump = n('ShaderNodeBump')
    bump.inputs['Strength'].default_value = 1.0
    bump.inputs['Distance'].default_value = 0.00004 * depth
    link(height, bump.inputs['Height'])
    link(bump.outputs['Normal'], b.inputs['Normal'])
    # Roughness stays unlinked, so shots can still set it (colors.py does).
    return mat


def _ancestors(o):
    out = []
    while o.parent:
        o = o.parent
        out.append(o)
    return out


def _kicad_finish(m):
    """Metal leads and pads metallic and shiny, soldermask glossy, plastic bodies satin."""
    b = bsdf(m)
    r, g, bl, _ = b.inputs['Base Color'].default_value
    hi, lo = max(r, g, bl), min(r, g, bl)
    sat = 0 if hi == 0 else (hi - lo) / hi
    if (sat < 0.15 and hi > 0.35) or (0.3 < sat < 0.75 and hi > 0.55 and r >= g > bl):
        b.inputs['Metallic'].default_value = 1.0          # tin, silver, gold, copper
        b.inputs['Roughness'].default_value = 0.25
    elif g > r and g > bl and hi < 0.3:
        b.inputs['Roughness'].default_value = 0.18        # soldermask
        b.inputs['Coat Weight'].default_value = 0.5
    else:
        b.inputs['Roughness'].default_value = 0.4


# ---------------------------------------------------------------- the studio

class Studio:
    def __init__(self, quality='draft', frames=120, fps=30):
        self.quality = quality
        self.q = QUALITY[quality]
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        self.scene.unit_settings.system = 'METRIC'
        self.set_frames(frames, fps)
        self.units = []
        self.target = None
        self.camera = None
        self.rig = None
        self.raytrace = None              # True/False overrides the preset (clear acrylic needs it)

    def set_frames(self, frames, fps=30):
        """A loop of `frames` frames, 1..frames. Frame frames+1 would equal frame 1."""
        self.frames = frames
        self.scene.frame_start, self.scene.frame_end = 1, frames
        self.scene.render.fps = fps

    def unit(self, stem='assembly_4', name=None):
        glb = MECH_OUT / f'{stem}.glb'
        if not glb.exists():
            raise SystemExit(f'{glb} is missing: run `uv run --group dev mech/assembly.py N` first')
        u = Unit(glb, name or stem)
        self.units.append(u)
        return u

    # -- environment ------------------------------------------------------------------

    def stage(self, floor=True, haze=0.0):
        """Near-black world, a soft key from above, coloured rim strips behind, and optionally
        a dark glossy floor that fades out, and a thin volumetric haze."""
        world = bpy.data.worlds.new('world')
        self.scene.world = world
        bg = world.node_tree.nodes['Background']
        bg.inputs['Color'].default_value = (0.004, 0.005, 0.009, 1)
        bg.inputs['Strength'].default_value = 1.0
        if haze and self.q['vol_samples']:
            vol = world.node_tree.nodes.new('ShaderNodeVolumePrincipled')
            vol.inputs['Density'].default_value = haze
            vol.inputs['Anisotropy'].default_value = 0.4
            world.node_tree.links.new(vol.outputs[0], world.node_tree.nodes['World Output'].inputs['Volume'])

        self.lights = {
            'key':  self.area('key', (0.0, -0.25, 0.75), 0.7, 0.5, 22, (1.0, 0.92, 0.85)),
            'fill': self.area('fill', (0.0, -0.9, 0.15), 1.2, 0.3, 4, (0.7, 0.8, 1.0)),
            'rim_l': self.area('rim_l', (-0.4, 0.3, 0.35), 0.06, 0.6, 35, (0.25, 0.5, 1.0)),
            'rim_r': self.area('rim_r', (0.4, 0.3, 0.35), 0.06, 0.6, 30, (0.85, 0.25, 1.0)),
        }
        if floor:
            self.floor()

    def area(self, name, loc, sx, sy, watts, color, target=(0, 0, 0.02)):
        d = bpy.data.lights.new(name, 'AREA')
        d.shape = 'RECTANGLE'
        d.size, d.size_y = sx, sy
        d.energy = watts
        d.color = color
        o = bpy.data.objects.new(name, d)
        self.scene.collection.objects.link(o)
        o.location = loc
        o.visible_camera = False           # a light source, not a prop: never seen directly
        look_at(o, Vector(target))
        return o

    def floor(self, size=8.0):
        """Dark glossy floor whose reflection fades out away from the centre."""
        bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, -4 * MM))
        fl = bpy.context.object
        fl.name = 'floor'
        mat = principled('floor', **{'Base Color': (0.005, 0.005, 0.007, 1), 'Roughness': 0.28})
        nt = mat.node_tree
        tex = nt.nodes.new('ShaderNodeTexCoord')
        grad = nt.nodes.new('ShaderNodeTexGradient')
        grad.gradient_type = 'SPHERICAL'
        mapping = nt.nodes.new('ShaderNodeMapping')
        mapping.inputs['Scale'].default_value = (2.4, 4.5, 1.0)      # fades out ~0.4 m along x, ~0.2 m along y
        ramp = nt.nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position = 0.0
        # Never exactly 0: EEVEE renders colour garbage where Specular IOR Level is 0.
        ramp.color_ramp.elements[0].color = (0.03, 0.03, 0.03, 1)
        ramp.color_ramp.elements[1].position = 0.8
        ramp.color_ramp.elements[1].color = (0.45, 0.45, 0.45, 1)
        nt.links.new(tex.outputs['Object'], mapping.inputs['Vector'])
        nt.links.new(mapping.outputs['Vector'], grad.inputs['Vector'])
        nt.links.new(grad.outputs['Fac'], ramp.inputs['Fac'])
        nt.links.new(ramp.outputs['Color'], bsdf(mat).inputs['Specular IOR Level'])
        # Micro texture, like sand-blasted stone: blotchy roughness from a coarse noise and a
        # fine grain in the bump, so the reflections break up into a speckled sheen.
        coarse = nt.nodes.new('ShaderNodeTexNoise')
        coarse.inputs['Scale'].default_value = 25.0           # ~4 cm blotches
        coarse.inputs['Detail'].default_value = 4.0
        rough = nt.nodes.new('ShaderNodeMapRange')
        rough.inputs['From Min'].default_value, rough.inputs['From Max'].default_value = 0.3, 0.7
        rough.inputs['To Min'].default_value, rough.inputs['To Max'].default_value = 0.18, 0.42
        fine = nt.nodes.new('ShaderNodeTexNoise')
        fine.inputs['Scale'].default_value = 2500.0           # ~0.4 mm grain
        fine.inputs['Detail'].default_value = 2.0
        bump = nt.nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.25
        bump.inputs['Distance'].default_value = 0.0002
        nt.links.new(tex.outputs['Object'], coarse.inputs['Vector'])
        nt.links.new(tex.outputs['Object'], fine.inputs['Vector'])
        nt.links.new(coarse.outputs['Fac'], rough.inputs['Value'])
        nt.links.new(rough.outputs['Result'], bsdf(mat).inputs['Roughness'])
        nt.links.new(fine.outputs['Fac'], bump.inputs['Height'])
        nt.links.new(bump.outputs['Normal'], bsdf(mat).inputs['Normal'])
        fl.data.materials.append(mat)
        return fl

    # -- camera -----------------------------------------------------------------------

    def camera_rig(self, target=(0, 0, 0.02), dist=0.75, height=0.35, lens=50, fstop=4.0, azimuth=0,
                   lights_follow=True):
        """Camera on an orbit rig: the rig sits at the target and turns (rig.rotation_euler.z);
        the camera looks at the target, which is also the focus point. With `lights_follow`, the
        studio lights turn with the rig, so the lighting stays the same as seen from the camera
        (the rims stay behind the product and their reflections never face the lens)."""
        self.rig = bpy.data.objects.new('rig', None)
        self.scene.collection.objects.link(self.rig)
        self.rig.location = target
        self.rig.rotation_euler.z = math.radians(azimuth)
        self.target = bpy.data.objects.new('target', None)      # rides on the rig, at its centre
        self.scene.collection.objects.link(self.target)
        self.target.parent = self.rig
        cd = bpy.data.cameras.new('camera')
        cd.lens = lens
        # Fixed vertical field of view (that of a 36 mm wide sensor at 16:9): wider aspects
        # (aspect(), ANIM_ASPECT) only add picture at the sides, the framing stays the same.
        cd.sensor_fit = 'VERTICAL'
        cd.sensor_height = 36 * 9 / 16
        cd.clip_start, cd.clip_end = 0.01, 50
        cd.dof.use_dof = True
        cd.dof.focus_object = self.target
        cd.dof.aperture_fstop = fstop
        cd.dof.aperture_blades = 7
        self.camera = bpy.data.objects.new('camera', cd)
        self.scene.collection.objects.link(self.camera)
        self.camera.parent = self.rig
        self.camera.location = (0, -dist, height)
        c = self.camera.constraints.new('TRACK_TO')
        c.target = self.target
        c.track_axis, c.up_axis = 'TRACK_NEGATIVE_Z', 'UP_Y'
        self.scene.camera = self.camera
        if lights_follow:
            # lights are laid out for azimuth 0 (camera at -y), relative to the world origin
            for o in getattr(self, 'lights', {}).values():
                o.parent = self.rig
                o.location -= Vector(target)
        return self.camera

    def pose(self, frame, target, az, dist, elev, fstop=None, interp='BEZIER'):
        """Keyframe a camera pose: looking at `target` (world x, y, z), from azimuth `az`
        (degrees, 0 = from the front, i.e. from -y; positive turns towards +x), `dist` metres
        away, `elev` degrees above the horizontal. Poses are joined by smooth curves; call
        loop_camera() after the last one."""
        e = math.radians(elev)
        key(self.rig, 'location', frame, Vector(target), interp)
        key(self.rig, 'rotation_euler', frame, (0, 0, math.radians(az)), interp)
        key(self.camera, 'location', frame, (0, -dist * math.cos(e), dist * math.sin(e)), interp)
        if fstop is not None:
            key(self.camera.data, 'dof.aperture_fstop', frame, fstop, interp)

    def loop_camera(self):
        """Make the camera path repeat, with smooth (cyclic auto) handles across the loop
        point. The pose at frame N+1 must equal the one at frame 1."""
        for obj in (self.rig, self.camera, self.camera.data):
            ad = obj.animation_data
            if not ad or not ad.action:
                continue
            for fc in _fcurves(ad):
                for kp in fc.keyframe_points:
                    kp.handle_left_type = kp.handle_right_type = 'AUTO_CLAMPED'
                if not any(m.type == 'CYCLES' for m in fc.modifiers):
                    fc.modifiers.new('CYCLES')
                fc.update()

    def camera_path(self, holds, float_=1.0):
        """A looping camera path of holds joined by quick moves.

        `holds` is a list of (f0, f1, pose0, pose1): from frame f0 to f1 the camera drifts
        steadily from pose0 to pose1. Between one hold's end and the next one's start it moves
        with a sharp ease (quintic), starting and ending at the drift speeds, so nothing ever
        jolts or stops dead. After the last hold it moves back to the first, at frame N + f0.

        A pose is a dict: target (x, y, z), az, dist, elev (as in pose()), and optionally
        fstop (4) and lens (50 mm). `float_` scales a faint, seamless handheld drift.
        The path is baked into one key per frame.
        """
        N = self.frames
        names = ('tx', 'ty', 'tz', 'az', 'dist', 'elev', 'fstop', 'lens')

        def vec(p):
            t = p['target']
            return [t[0], t[1], t[2], p['az'], p['dist'], p['elev'], p.get('fstop', 4.0), p.get('lens', 50.0)]

        segs = []                       # (fa, fb, a, b, va, vb, kind)
        hs = [(f0, f1, vec(p0), vec(p1)) for f0, f1, p0, p1 in holds]
        for i, (f0, f1, a, b) in enumerate(hs):
            v = [(y - x) / (f1 - f0) for x, y in zip(a, b)]
            segs.append((f0, f1, a, b, v, v, 'hold'))
            n0, _, na, nb = hs[(i + 1) % len(hs)]
            nv = [(y - x) / (hs[(i + 1) % len(hs)][1] - n0) for x, y in zip(na, nb)]
            if i == len(hs) - 1:
                n0 += N
            segs.append((f1, n0, b, na, v, nv, 'move'))

        def at(f):
            start = hs[0][0]
            f = start + (f - start) % N
            for fa, fb, a, b, va, vb, kind in segs:
                if fa <= f <= fb:
                    T = fb - fa
                    t = (f - fa) / T
                    if kind == 'hold':
                        return [x + (y - x) * t for x, y in zip(a, b)]
                    e = t * t * t * (t * (6 * t - 15) + 10)          # quintic: flat ends
                    # cubic Hermite terms that add the end velocities without moving the ends
                    h10, h11 = t * (1 - t) ** 2, t * t * (t - 1)
                    return [x + (y - x) * e + T * (h10 * p + h11 * q)
                            for x, y, p, q in zip(a, b, va, vb)]
            raise ValueError(f)

        def wobble(f, k, phase, amp):
            """Sum of sines with whole cycles per loop: seamless."""
            u = 2 * math.pi * f / N
            return amp * (math.sin(k * u + phase) + 0.5 * math.sin((2 * k + 1) * u + 2 * phase))

        for f in range(1, N + 2):
            v = dict(zip(names, at(f)))
            v['az'] += float_ * wobble(f, 2, 0.3, 0.5)
            v['elev'] += float_ * wobble(f, 3, 1.7, 0.35)
            v['tz'] += float_ * wobble(f, 4, 2.9, 0.6 * MM)
            e = math.radians(v['elev'])
            key(self.rig, 'location', f, (v['tx'], v['ty'], v['tz']), 'LINEAR')
            key(self.rig, 'rotation_euler', f, (0, 0, math.radians(v['az'])), 'LINEAR')
            key(self.camera, 'location', f, (0, -v['dist'] * math.cos(e), v['dist'] * math.sin(e)), 'LINEAR')
            key(self.camera.data, 'dof.aperture_fstop', f, v['fstop'], 'LINEAR')
            key(self.camera.data, 'lens', f, v['lens'], 'LINEAR')

    def orbit(self, start_deg, end_deg, frames=None, interp='LINEAR'):
        """Turn the rig from start to end over the shot. With end = start + 360 and linear
        interpolation it loops seamlessly."""
        n = frames or self.frames
        key(self.rig, 'rotation_euler', 1, (0, 0, math.radians(start_deg)), interp, index=2)
        key(self.rig, 'rotation_euler', n + 1, (0, 0, math.radians(end_deg)), interp, index=2)

    # -- render settings and compositing ----------------------------------------------

    def finish(self):
        """Engine, colour management and the glow/vignette compositor, from the preset."""
        q, sc, r = self.q, self.scene, self.scene.render
        r.engine = 'BLENDER_EEVEE'
        h = q['res'][1]
        r.resolution_x, r.resolution_y = 2 * round(h * aspect() / 2), h
        r.resolution_percentage = 100
        r.use_motion_blur = q['motion_blur']
        r.motion_blur_shutter = 0.4
        ee = sc.eevee
        ee.taa_render_samples = q['samples']
        ee.use_raytracing = q['raytrace'] if self.raytrace is None else self.raytrace
        if ee.use_raytracing:
            ee.ray_tracing_method = 'SCREEN'
        ee.use_shadows = True
        ee.shadow_ray_count = 1 if self.quality == 'draft' else 2
        ee.volumetric_samples = max(self.q['vol_samples'], 1)
        ee.volumetric_end = 4
        try:
            sc.view_settings.view_transform = 'AgX'
            sc.view_settings.look = 'AgX - Medium High Contrast'
        except TypeError:
            pass
        sc.view_settings.exposure = 0.0
        self.compositor()

    def compositor(self, bloom=0.6, fog=0.25, vignette=0.0):
        """Render layer -> bloom (tight highlights) -> fog glow (wide soft halo) -> vignette.
        The vignette is off by default: render.py adds it per export with ffmpeg, because the
        exports are crops of one wide render and each needs its own."""
        t = bpy.data.node_groups.new('post', 'CompositorNodeTree')
        self.scene.compositing_node_group = t
        n, link = t.nodes, t.links.new
        rl = n.new('CompositorNodeRLayers')
        b = n.new('CompositorNodeGlare')
        b.inputs['Type'].default_value = 'Bloom'
        b.inputs['Quality'].default_value = self.q['glare']
        b.inputs['Threshold'].default_value = 1.2
        b.inputs['Strength'].default_value = bloom
        b.inputs['Size'].default_value = 0.6
        f = n.new('CompositorNodeGlare')
        f.inputs['Type'].default_value = 'Fog Glow'
        f.inputs['Quality'].default_value = self.q['glare']
        f.inputs['Threshold'].default_value = 1.5
        f.inputs['Strength'].default_value = fog
        f.inputs['Size'].default_value = 0.8
        link(rl.outputs['Image'], b.inputs['Image'])
        link(b.outputs['Image'], f.inputs['Image'])
        out_img = f.outputs['Image']
        if vignette:
            mask = n.new('CompositorNodeEllipseMask')
            mask.inputs['Size'].default_value = (0.95, 0.9)
            blur = n.new('CompositorNodeBlur')
            px = round(self.q['res'][1] / 5.4)            # 200 px at 1080 lines
            blur.inputs['Size'].default_value = (px, px)
            blur.inputs['Type'].default_value = 'Gaussian'
            mix = n.new('ShaderNodeMix')
            mix.data_type = 'RGBA'
            mix.blend_type = 'MULTIPLY'
            mix.inputs['Factor'].default_value = vignette
            link(mask.outputs['Mask'], blur.inputs['Image'])
            link(out_img, mix.inputs[6])
            link(blur.outputs['Image'], mix.inputs[7])
            out_img = mix.outputs[2]
        go = n.new('NodeGroupOutput')
        t.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        link(out_img, go.inputs[0])


def thin_refraction(mat):
    """Screen-space refraction through a thin sheet (used when raytracing is on)."""
    mat.use_raytrace_refraction = True
    mat.thickness_mode = 'SLAB'


def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
