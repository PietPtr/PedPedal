import uuid, copy, math, sys, json
import xml.etree.ElementTree as ET
import sx
from sx import Sym, find, find1, dump
from fpinfo import load as load_fp

S = lambda s: Sym(s)
def u(): return str(uuid.uuid4())
BX, BY = 100.0, 60.0          # board origin on the KiCad canvas
W, H = 80.0, 86.0
DY = 10.0                      # routing channel below the Pico band

# ---------------------------------------------------------------- netlist
net = ET.parse(sys.argv[1]).getroot()
comps = {}
for c in net.find('components'):
    extra = {}
    for pr in c.findall('property'):
        if pr.get('name').startswith(('ki_', 'Sim.')) and pr.get('name') not in ('ki_description',):
            extra[pr.get('name')] = pr.get('value')
    comps[c.get('ref')] = dict(value=c.findtext('value'), fp=c.findtext('footprint'), uuid=c.findtext('tstamps'),
                               keywords=extra)
padnet = {}
netnames = []
for n in net.find('nets'):
    name = n.get('name'); netnames.append(name)
    for nd in n.findall('node'):
        padnet[(nd.get('ref'), nd.get('pin'))] = name
netnames = sorted(set(netnames), key=lambda s: (s.startswith('unconnected'), s))
netcode = {n: i + 1 for i, n in enumerate(netnames)}

# ---------------------------------------------------------------- placement (board-local mm, rotation deg CCW)
P = {}
P['SW1'] = (40, 64, 180)
P['D1'] = (40 - 2.413, 30 - 0.762, 0)
P['U1'] = (18.1, 31, 0)
P['U2'] = (80 - 18.1 - 7.62, 31, 0)
P['J2'] = (5.2, 37, 0)                    # OUT, left edge
P['J1'] = (80 - 5.2 - 2.54, 37, 0)        # IN, right edge
P['C3'] = (14.2, 32, -90); P['C1'] = (14.2, 41, -90)
P['C2'] = (65.8, 32, -90); P['C4'] = (47, 29.5, 0)
for i in range(3):                       # LED drivers, centred under the LED
    P[f'Q{1+i}'] = (32 + 8 * i - 2.54, 37.5, 0)
    P[f'R{16+i}'] = (40 - 5.08, 44 + 3 * i, 0)
for i, r in enumerate(['R4', 'R15', 'R14', 'R13', 'R12', 'R11', 'R10', 'R9']):
    P[r] = (4.5 + 3.3 * i, 54.5, -90)
for i, r in enumerate(['R5', 'R6', 'R7', 'R8', 'R3', 'R2', 'R1']):
    P[r] = (75.5 - 3.3 * i, 54.5, -90)
P['U3'] = (80 - 3.17, 3.2, -90)            # Pico, USB to the right edge
P['J3'] = (4.22, 10.54, 90)        # odd row (IN1-IN6) faces the board
REFPOS = {'C2': (65.8, 29.3), 'C3': (14.2, 29.3), 'C1': (14.2, 48.4)}
for i in range(3):
    REFPOS[f'Q{1+i}'] = (32 + 8 * i, 41.0)
    REFPOS[f'R{16+i}'] = (32.0, 44 + 3 * i)
HOLES = [(4, 27.5 + DY), (76, 27.5 + DY), (4, 72 + DY), (76, 72 + DY)]
for _r in list(P):
    if _r not in ('U3', 'J3'):
        _x, _y, _a = P[_r]; P[_r] = (_x, _y + DY, _a)
REFPOS = {k: (v[0], v[1] + DY) for k, v in REFPOS.items()}

def rot(x, y, a):
    t = math.radians(a); c, s = round(math.cos(t), 9), round(math.sin(t), 9)
    return x * c + y * s, -x * s + y * c
def r4(v): return round(v, 4)

# ---------------------------------------------------------------- footprints
def fix_uuids(node):
    if isinstance(node, list):
        if node and node[0] == 'uuid' and len(node) == 2: node[1] = u()
        for e in node: fix_uuids(e)

footprints = []
pads_abs = {}       # ref -> list of (num, absx, absy, shape, w, h, layers, drill)
keepouts = []       # (x, y, r) for NPTH holes
zone_keepouts = []  # polygons (board-local) where tracks are not allowed

def place(ref, fpid, x, y, a, value, path=None, board_only=False, keywords=None):
    lib = load_fp(fpid)
    fp = [S('footprint'), fpid, [S('layer'), 'F.Cu'], [S('uuid'), u()], [S('at'), r4(BX + x), r4(BY + y), a]]
    pads = []
    for e in lib[2:]:
        if not isinstance(e, list) or e[0] in ('version', 'generator', 'generator_version', 'layer', 'uuid'):
            if isinstance(e, list): continue
            continue
        e = copy.deepcopy(e)
        if e[0] == 'property':
            if e[1] == 'Reference':
                e[2] = ref
                if ref.startswith('H'):
                    e.insert(4, [S('hide'), S('yes')])
                if ref.startswith('R') and a == -90:
                    at = find1(e, 'at'); at[1], at[2] = 12.9, 0
                    eff = find1(e, 'effects'); f = find1(eff, 'font'); find1(f, 'size')[1:] = [0.8, 0.8]
                    find1(f, 'thickness')[1] = 0.12
                    del at[3:]; at.append(-180)
                if ref in REFPOS:
                    at = find1(e, 'at'); ox, oy = REFPOS[ref]
                    lx, ly = rot(ox - x, oy - y, -a); at[1], at[2] = r4(lx), r4(ly); del at[3:]; at.append(-a)
            if e[1] == 'Value': e[2] = value
        if e[0] in ('property', 'fp_text', 'pad'):
            at = find1(e, 'at')
            while len(at) < 4: at.append(0)
            at[3] = r4((float(at[3]) + a) % 360)
        if e[0] == 'group':
            continue
        if e[0] == 'zone':
            pts = find1(find1(e, 'polygon'), 'pts')
            absp = []
            for xy in find(pts, 'xy'):
                dx, dy = rot(float(xy[1]), float(xy[2]), a)
                xy[1], xy[2] = r4(BX + x + dx), r4(BY + y + dy)
                absp.append((x + dx, y + dy))
            ko = find1(e, 'keepout')
            if ko and find1(ko, 'tracks') and str(find1(ko, 'tracks')[1]) == 'not_allowed':
                zone_keepouts.append(absp)
        if e[0] == 'attr' and board_only:
            e.append(S('board_only'))
        if e[0] == 'pad':
            num = e[1]
            at = find1(e, 'at'); sz = find1(e, 'size'); dr = find1(e, 'drill')
            lx, ly = float(at[1]), float(at[2])
            dx, dy = rot(lx, ly, a)
            ax, ay = x + dx, y + dy
            ang = float(at[3]) % 180
            w, h = float(sz[1]), float(sz[2])
            if abs(ang - 90) < 1: w, h = h, w
            layers = [str(l) for l in find1(e, 'layers')[1:]]
            kind = str(e[2])
            if kind == 'np_thru_hole':
                keepouts.append((ax, ay, float(dr[1]) / 2 + 0.3))
            elif num != '':
                pn = padnet.get((ref, num))
                if pn:
                    e.insert(len(e) - 1, [S('net'), netcode[pn], pn])
                pads.append(dict(num=num, x=ax, y=ay, shape=str(e[3]), w=w, h=h,
                                 smd=(kind == 'smd'), net=pn))
        fp.append(e)
    for k, v in (keywords or {}).items():   # schematic-only fields, so DRC parity is clean
        fp.insert(5, [S('property'), k, v, [S('at'), 0, 0, 0], [S('layer'), 'F.Fab'], [S('hide'), S('yes')],
                      [S('uuid'), u()], [S('effects'), [S('font'), [S('size'), 1, 1], [S('thickness'), 0.15]]]])
    if path:
        fp += [[S('path'), '/' + path], [S('sheetname'), '/'], [S('sheetfile'), 'footswitch.kicad_sch']]
    fix_uuids(fp[4:])
    footprints.append(fp)
    pads_abs[ref] = pads

for ref, (x, y, a) in P.items():
    c = comps[ref]
    place(ref, c['fp'], x, y, a, c['value'], c['uuid'], keywords=c['keywords'])
for i, (x, y) in enumerate(HOLES):
    place(f'H{i+1}', 'MountingHole:MountingHole_3.2mm_M3', x, y, 0, 'M3', board_only=True)
    keepouts.append((x, y, 3.2))

# ---------------------------------------------------------------- graphics
graphics = []
def gtext(s, x, y, size=1.0, layer='F.SilkS', a=0, just=None):
    eff = [S('effects'), [S('font'), [S('size'), size, size], [S('thickness'), round(size * 0.15, 3)]]]
    if just: eff.append([S('justify'), S(just)])
    graphics.append([S('gr_text'), s, [S('at'), r4(BX + x), r4(BY + y), a], [S('layer'), layer], [S('uuid'), u()], eff])
graphics.append([S('gr_rect'), [S('start'), BX, BY], [S('end'), BX + W, BY + H],
                 [S('stroke'), [S('width'), 0.1], [S('type'), S('solid')]], [S('fill'), S('no')],
                 [S('layer'), 'Edge.Cuts'], [S('uuid'), u()]])
gtext('OUT', 6.47, 51.8 + DY, 1.2); gtext('IN', 73.53, 51.8 + DY, 1.2)
gtext('to next module', 5.47, 30.0, 0.8, a=0) if False else None
gtext('Footswitch module v0.1', 40, 74.6 + DY, 1.0)
gtext('Pico: module 1 only', 52, 12.1, 1.0, layer='F.Fab')

# GND pour on both layers
zones = []
for layer in ('F.Cu', 'B.Cu'):
    m = 0.5
    zones.append([S('zone'), [S('net'), netcode['GND']], [S('net_name'), 'GND'], [S('layer'), layer], [S('uuid'), u()],
                  [S('hatch'), S('edge'), 0.5], [S('connect_pads'), [S('clearance'), 0.4]],
                  [S('min_thickness'), 0.25], [S('filled_areas_thickness'), S('no')],
                  [S('fill'), S('yes'), [S('thermal_gap'), 0.5], [S('thermal_bridge_width'), 0.6]],
                  [S('polygon'), [S('pts')] + [[S('xy'), BX + px, BY + py] for px, py in
                                                [(m, m), (W - m, m), (W - m, H - m), (m, H - m)]]]])

# ---------------------------------------------------------------- write board
tmpl = sx.parse(open('/usr/share/kicad/template/Arduino_Uno/Arduino_Uno.kicad_pcb').read())
head = [e for e in tmpl[1:] if isinstance(e, list) and e[0] in ('version', 'generator', 'generator_version', 'general', 'layers', 'setup')]
for e in head:
    if e[0] == 'setup':
        for k in ('aux_axis_origin', 'grid_origin'):
            f = find1(e, k)
            if f: f[1], f[2] = BX, BY
board = [S('kicad_pcb')] + head[:4] + [[S('paper'), 'A4'],
         [S('title_block'), [S('title'), 'Footswitch module'], [S('date'), '2026-11-21'], [S('rev'), '0.1']]] + head[4:] + \
        [[S('net'), 0, '']] + [[S('net'), netcode[n], n] for n in netnames] + footprints + graphics + zones
extra = []
if len(sys.argv) > 3:
    extra = json.load(open(sys.argv[3]))   # routed tracks/vias
    for t in extra['tracks']:
        board.append([S('segment'), [S('start'), r4(t['x0']), r4(t['y0'])], [S('end'), r4(t['x1']), r4(t['y1'])],
                      [S('width'), t['w']], [S('layer'), t['layer']], [S('net'), netcode[t['net']]], [S('uuid'), u()]])
    for v in extra['vias']:
        board.append([S('via'), [S('at'), r4(v['x']), r4(v['y'])], [S('size'), 0.8], [S('drill'), 0.4],
                      [S('layers'), 'F.Cu', 'B.Cu'], [S('net'), netcode[v['net']]], [S('uuid'), u()]])
open(sys.argv[2], 'w').write(dump(board) + '\n')

# ---------------------------------------------------------------- DSN for freerouting (um, y flipped)
def U(v): return int(round(v * 1000))
def q(s): return '"' + s + '"'
POWER = {'GND', '+5V', '+3V3'}
lines = ['(pcb footswitch', ' (parser (string_quote ") (space_in_quoted_tokens on) (host_cad "KiCad") (host_version "10"))',
         ' (resolution um 10) (unit um)', ' (structure', '  (layer F.Cu (type signal) (property (index 0)))',
         '  (layer B.Cu (type signal) (property (index 1)))',
         # inset 0.4 mm so routed copper stays >= 0.6 mm from the real board edge
         f'  (boundary (path pcb 0 {U(BX+.4)} {-U(BY+.4)} {U(BX+W-.4)} {-U(BY+.4)} {U(BX+W-.4)} {-U(BY+H-.4)} {U(BX+.4)} {-U(BY+H-.4)} {U(BX+.4)} {-U(BY+.4)}))',
         '  (via "Via[0-1]_800:400_um")', '  (rule (width 300) (clearance 200.1) (clearance 200.1 (type default_smd)) (clearance 50 (type smd_smd)))']
for (kx, ky, kr) in keepouts:
    lines.append(f'  (keepout "" (circle signal {U(2*kr)} {U(BX+kx)} {-U(BY+ky)}))')
for poly in zone_keepouts:
    pts = ' '.join(f'{U(BX+px)} {-U(BY+py)}' for px, py in poly + [poly[0]])
    lines.append(f'  (keepout "" (polygon signal 0 {pts}))')
lines.append(' )')
# placement: one image per component, placed at the board origin, pins in absolute coords
lines.append(' (placement')
for ref in pads_abs:
    if pads_abs[ref]:
        lines.append(f'  (component IMG_{ref} (place {q(ref)} 0 0 front 0))')
lines.append(' )')
lines.append(' (library')
padstacks = {}
for ref, pads in pads_abs.items():
    if not pads: continue
    lines.append(f'  (image IMG_{ref}')
    for p in pads:
        layers = ['F.Cu'] if p['smd'] else ['F.Cu', 'B.Cu']
        if p['shape'] == 'circle' or (p['shape'] == 'oval' and abs(p['w'] - p['h']) < 1e-3):
            key = f"C{U(p['w'])}_{len(layers)}"; shp = [f'(circle {l} {U(p["w"])})' for l in layers]
        elif p['shape'] == 'oval':
            d = min(p['w'], p['h']); L = (max(p['w'], p['h']) - d) / 2
            if p['w'] > p['h']: seg = f'{-U(L)} 0 {U(L)} 0'
            else: seg = f'0 {-U(L)} 0 {U(L)}'
            key = f"O{U(p['w'])}x{U(p['h'])}_{len(layers)}"; shp = [f'(path {l} {U(d)} {seg})' for l in layers]
        else:
            key = f"R{U(p['w'])}x{U(p['h'])}_{len(layers)}"
            shp = [f'(rect {l} {-U(p["w"]/2)} {-U(p["h"]/2)} {U(p["w"]/2)} {U(p["h"]/2)})' for l in layers]
        padstacks[key] = shp
        lines.append(f'   (pin {key} {q(p["num"])} {U(BX + p["x"])} {-U(BY + p["y"])})')
    lines.append('  )')
for key, shp in padstacks.items():
    lines.append(f'  (padstack {key} ' + ' '.join(f'(shape {s})' for s in shp) + ' (attach off))')
lines.append('  (padstack "Via[0-1]_800:400_um" (shape (circle F.Cu 800)) (shape (circle B.Cu 800)) (attach off))')
lines.append(' )')
lines.append(' (network')
nets_pins = {}
for ref, pads in pads_abs.items():
    for p in pads:
        if p['net'] and not p['net'].startswith('unconnected'):
            nets_pins.setdefault(p['net'], []).append(f'{q(ref)}-{q(p["num"])}')
for n, pins in nets_pins.items():
    lines.append(f'  (net {q(n)} (pins {" ".join(pins)}))')
sig = [n for n in nets_pins if n not in POWER]
lines.append(f'  (class signal {" ".join(q(n) for n in sig)} (circuit (use_via "Via[0-1]_800:400_um")) (rule (width 300) (clearance 200.1)))')
lines.append(f'  (class power {" ".join(q(n) for n in POWER)} (circuit (use_via "Via[0-1]_800:400_um")) (rule (width 600) (clearance 200.1)))')
lines.append(' )')
lines.append(' (wiring)')
lines.append(')')
if len(sys.argv) <= 3:
    open(sys.argv[2].replace('.kicad_pcb', '.dsn'), 'w').write('\n'.join(lines) + '\n')
