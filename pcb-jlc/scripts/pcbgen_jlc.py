"""Board generator for the JLCPCB-assembled SMD variant (pcb-jlc/).

Derived from pcb/scripts/pcbgen.py. Same outline, mounting holes, Pico, LED and footswitch
positions as the THT board, so the plates and walls fit both. All SMD parts are on the top
side. Usage: pcbgen_jlc.py NETLIST.xml OUT.kicad_pcb [routes.json]
"""
import uuid, copy, math, sys, json, os
import xml.etree.ElementTree as ET
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'pcb', 'scripts'))
import sx
from sx import Sym, find, find1, dump
import fpinfo
_fp_path = fpinfo.path
def _path(fpid):   # project footprints come from pcb-jlc/footswitches.pretty
    lib, name = fpid.split(':')
    if lib == 'footswitches':
        return os.path.join(HERE, '..', 'footswitches.pretty', name + '.kicad_mod')
    return _fp_path(fpid)
fpinfo.path = _path
load_fp = fpinfo.load

S = lambda s: Sym(s)
def u(): return str(uuid.uuid4())
BX, BY = 100.0, 60.0          # board origin on the KiCad canvas
W, H = 80.0, 86.0
SHEETFILE = 'footswitch_jlc.kicad_sch'

# ---------------------------------------------------------------- netlist
net = ET.parse(sys.argv[1]).getroot()
comps = {}
for c in net.find('components'):
    extra = {}
    for pr in c.findall('property'):
        if pr.get('name').startswith(('ki_', 'Sim.')) and pr.get('name') not in ('ki_description',):
            extra[pr.get('name')] = pr.get('value')
        if pr.get('name') in ('LCSC', 'Fit'):
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
# Hand-soldered parts and holes: EXACTLY as on the THT board (pcb/footswitch.kicad_pcb).
P['SW1'] = (40, 74, 180)
P['D1'] = (40 - 2.413, 40 - 0.762, 0)
P['U3'] = (80 - 3.17, 3.2, -90)            # Pico, USB to the right edge
HOLES = [(4, 27.2), (76, 27.2), (4, 82), (76, 82)]
# Chain connectors: SMD box headers, footprint origin at the centre. Same pin positions as the
# THT headers (pin 1 at (4.9, 6.2) and (16.9, 6.2)) moved 0.6 mm right, so J2's pads stay
# 1 mm from the left edge. Still 12 mm apart, so the cable length doesn't change.
P['J2'] = (4.9 + 1.27 + 0.6, 6.2 + 3.81, 0)     # OUT
P['J1'] = (16.9 + 1.27 + 0.6, 6.2 + 3.81, 0)    # IN
# SMD parts, all on the top side.
P['U1'] = (21.91, 49.89, 0)                # 74HC165, pin 1 top left (same centre as the DIP)
P['U2'] = (58.09, 49.89, 0)                # 74HC595
P['C1'] = (21.91, 41.8, 180)               # U1 decoupling, above pin 16 / pin 1 row
P['C2'] = (58.09, 41.8, 180)               # U2 decoupling
P['C3'] = (13.5, 50.5, 90)                 # footswitch debounce
P['R9'] = (13.5, 55.5, 90)                 # footswitch pull-up
P['R4'] = (13.5, 45.5, 90)                 # SW_DATA end-of-chain pull-down
P['C4'] = (46.5, 39.5, 0)                  # 5V bulk, next to the LED anode
for i in range(3):                         # LED drivers under the LED: R1-R3, Q1-Q3, R16-R18 per channel
    x = 32 + 8 * i
    P[f'R{1+i}'] = (x, 45.5, 90)            # below the LED's courtyard
    P[f'Q{1+i}'] = (x, 50.0, 90)
    P[f'R{16+i}'] = (x, 55.0, 90)
for i in range(4):                         # Pico series resistors, pad 1 (Pico side) right
    P[f'R{5+i}'] = (21.0, 25.5 + 2.5 * i, 180)
REFPOS = {'C1': (18.4, 41.8), 'C2': (61.6, 41.8)}   # silkscreen reference positions where the default overlaps
for i in range(4):
    REFPOS[f'R{5+i}'] = (24.8, 25.5 + 2.5 * i)

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
                if ref.startswith('H') or ref in ('J1', 'J2'):   # J1/J2: named in the IN/OUT silk text
                    e.insert(4, [S('hide'), S('yes')])
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
        fp += [[S('path'), '/' + path], [S('sheetname'), '/'], [S('sheetfile'), SHEETFILE]]
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
gtext('J2 OUT', P['J2'][0], 21.0, 1.2); gtext('J1 IN', P['J1'][0], 21.0, 1.2)
gtext('Footswitch module v0.2 SMD', 40, 84.6, 1.0)
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
        for k in ('aux_axis_origin', 'grid_origin'):   # bottom-left corner: fab files use positive coordinates
            f = find1(e, k)
            if f: f[1], f[2] = BX, BY + H
board = [S('kicad_pcb')] + head[:4] + [[S('paper'), 'A4'],
         [S('title_block'), [S('title'), 'Footswitch module, JLCPCB SMD assembly'], [S('date'), '2026-11-21'], [S('rev'), '0.2']]] + head[4:] + \
        [[S('net'), 0, '']] + [[S('net'), netcode[n], n] for n in netnames] + footprints + graphics + zones
def clean_tracks(tracks, vias):
    """Drop Freerouting's leftovers: duplicate segments and stubs whose end touches nothing."""
    seen, out = set(), []
    for t in tracks:
        a, b = (round(t['x0'], 3), round(t['y0'], 3)), (round(t['x1'], 3), round(t['y1'], 3))
        key = (t['layer'], t['net'], min(a, b), max(a, b))
        if a != b and key not in seen:
            seen.add(key); out.append(t)
    def on_pad(x, y, layer, netname):
        for pads in pads_abs.values():
            for p in pads:
                if p['net'] == netname and (not p['smd'] or layer == 'F.Cu') and \
                        abs(BX + p['x'] - x) <= p['w'] / 2 + 1e-3 and abs(BY + p['y'] - y) <= p['h'] / 2 + 1e-3:
                    return True
        return False
    via_at = {(round(v['x'], 3), round(v['y'], 3)) for v in vias}
    while True:
        ends = {}
        for t in out:
            for e in ((round(t['x0'], 3), round(t['y0'], 3)), (round(t['x1'], 3), round(t['y1'], 3))):
                ends[(t['layer'], e)] = ends.get((t['layer'], e), 0) + 1
        def dangling(t):
            for e in ((round(t['x0'], 3), round(t['y0'], 3)), (round(t['x1'], 3), round(t['y1'], 3))):
                if ends[(t['layer'], e)] == 1 and e not in via_at and not on_pad(*e, t['layer'], t['net']):
                    return True
            return False
        keep = [t for t in out if not dangling(t)]
        if len(keep) == len(out): return out
        out = keep

extra = []
if len(sys.argv) > 3:
    extra = json.load(open(sys.argv[3]))   # routed tracks/vias
    extra['tracks'] = clean_tracks(extra['tracks'], extra['vias'])
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
lines = ['(pcb footswitch_jlc', ' (parser (string_quote ") (space_in_quoted_tokens on) (host_cad "KiCad") (host_version "10"))',
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
