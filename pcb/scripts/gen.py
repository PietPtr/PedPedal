import uuid, copy, sys
import sx
from sx import Sym, find, find1, dump

def u(): return str(uuid.uuid4())
ROOT = u()
PROJECT = 'footswitch'
POWER = {'+5V': ('power', '+5V'), '+3V3': ('power', '+3V3'), 'GND': ('power', 'GND')}
lib_symbols = {}
items = []
pwr_n = [0]

FP = {
 'R': 'Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal',
 'C': 'Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm',
 'CP': 'Capacitor_THT:CP_Radial_D5.0mm_P2.00mm',
 'DIP16': 'Package_DIP:DIP-16_W7.62mm_Socket_LongPads',
}

def g(v):  # snap to 0.01 and print
    return round(v, 4)

def use_lib(lib, name):
    key = f'{lib}:{name}'
    if key not in lib_symbols:
        s = sx.flat_symbol(lib, name)
        s[1] = key
        lib_symbols[key] = s
    return lib_symbols[key]

OUT = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}
LABEL_ANGLE = {(-1, 0): 180, (1, 0): 0, (0, -1): 90, (0, 1): 270}

class Part:
    def __init__(self, lib, name, ref, value, x, y, footprint='', unit=1, extra=None, rot=0, hide_extra=False, in_bom=True):
        self.sym = use_lib(lib, name)
        self.x, self.y, self.unit = x, y, unit
        self.pins = {}
        for (un, num, pname, typ, px, py, ang) in sx.pins(self.sym):
            if un in (0, unit):
                rx, ry = rotp(px, py, rot)
                self.pins[num] = (x + rx, y - ry, OUT[int(ang + rot) % 360])
        props = []
        for p in find(self.sym, 'property'):
            p = copy.deepcopy(p)
            at = find1(p, 'at')
            rx, ry = rotp(float(at[1]), float(at[2]), rot)
            at[1] = g(x + rx); at[2] = g(y - ry)
            if p[1] == 'Reference': p[2] = ref
            elif p[1] == 'Value': p[2] = value
            elif p[1] == 'Footprint' and footprint: p[2] = footprint
            props.append(p)
        for k, v in (extra or {}).items():
            props.append([Sym('property'), k, v, [Sym('at'), x, y + 8, 0],
                          [Sym('effects'), [Sym('font'), [Sym('size'), 1.27, 1.27]]] + ([[Sym('hide'), Sym('yes')]] if hide_extra else [])])
        node = [Sym('symbol'), [Sym('lib_id'), self.sym[1]], [Sym('at'), x, y, rot], [Sym('unit'), unit],
                [Sym('exclude_from_sim'), Sym('no')], [Sym('in_bom'), Sym('no' if ref.startswith('#') or not in_bom else 'yes')],
                [Sym('on_board'), Sym('no' if ref.startswith('#') else 'yes')], [Sym('dnp'), Sym('no')],
                [Sym('uuid'), u()]] + props
        for num in self.pins:
            node.append([Sym('pin'), num, [Sym('uuid'), u()]])
        node.append([Sym('instances'), [Sym('project'), PROJECT,
                     [Sym('path'), '/' + ROOT, [Sym('reference'), ref], [Sym('unit'), unit]]]])
        items.append(node)

    def c(self, pin, net, stub=2.54):
        px, py, (dx, dy) = self.pins[pin]
        if net == 'NC':
            items.append([Sym('no_connect'), [Sym('at'), g(px), g(py)], [Sym('uuid'), u()]])
            return
        ex, ey = g(px + dx * stub), g(py + dy * stub)
        if stub:
            wire(px, py, ex, ey)
        if net in POWER:
            power(net, ex, ey, (dx, dy))
        else:
            label(net, ex, ey, LABEL_ANGLE[(dx, dy)])

    def cs(self, mapping, stub=2.54):
        for pin, net in mapping.items():
            self.c(pin, net, stub)

def rotp(px, py, rot):
    import math
    if not rot: return px, py
    t = math.radians(rot); c, s_ = round(math.cos(t)), round(math.sin(t))
    return px * c - py * s_, px * s_ + py * c

def wire(x0, y0, x1, y1):
    items.append([Sym('wire'), [Sym('pts'), [Sym('xy'), g(x0), g(y0)], [Sym('xy'), g(x1), g(y1)]],
                  [Sym('stroke'), [Sym('width'), 0], [Sym('type'), Sym('default')]], [Sym('uuid'), u()]])

def label(net, x, y, ang):
    just = [Sym('justify'), Sym('left' if ang in (0, 90) else 'right'), Sym('bottom')]
    items.append([Sym('label'), net, [Sym('at'), x, y, ang], [Sym('fields_autoplaced'), Sym('yes')],
                  [Sym('effects'), [Sym('font'), [Sym('size'), 1.27, 1.27]], just], [Sym('uuid'), u()]])

def power(net, x, y, out=None):
    pwr_n[0] += 1
    if net == 'GND':
        rot = {(1, 0): 90, (-1, 0): 270, (0, -1): 180}.get(out, 0)
    else:
        rot = {(-1, 0): 90, (1, 0): 270, (0, 1): 180}.get(out, 0)
    Part(*POWER[net], f'#PWR{pwr_n[0]:02d}', net, x, y, rot=rot)
    if rot in (90, 270):
        dx, dy = out
        for p in find(items[-1], 'property'):
            if p[1] == 'Value':
                at = find1(p, 'at')
                at[1] = g(x + dx * (3.81 + 1.0 * len(net))); at[2] = g(y - 0.0); at[3] = 90

def text(s, x, y, size=1.27, bold=False):
    font = [Sym('font'), [Sym('size'), size, size]] + ([[Sym('bold'), Sym('yes')]] if bold else [])
    items.append([Sym('text'), s, [Sym('exclude_from_sim'), Sym('no')], [Sym('at'), x, y, 0],
                  [Sym('effects'), font, [Sym('justify'), Sym('left'), Sym('bottom')]], [Sym('uuid'), u()]])

def R(ref, val, x, y, top, bot, extra=None):
    p = Part('Device', 'R', ref, val, x, y, FP['R'], extra=extra, hide_extra=True)
    p.c('1', top, 0 if top in POWER else 2.54); p.c('2', bot, 0 if bot in POWER else 2.54)
    return p

def C(ref, val, x, y, top, bot, pol=False):
    p = Part('Device', 'C_Polarized' if pol else 'C', ref, val, x, y, FP['CP' if pol else 'C'])
    p.c('1', top, 0); p.c('2', bot, 0)
    return p

# ---------------------------------------------------------------- layout
H = 3  # heading size

# Chain connectors -------------------------------------------------------
text('Chain connectors', 25, 30, H, True)
text('J1 IN: from the Pico side.  J2 OUT: to the next module.\n'
     'Same pinout on both. CLK, LATCH and power pass straight through.', 25, 38)
for ref, val, y, d7, d8 in [('J1', 'CHAIN_IN', 54.61, 'LED_DATA', 'SW_DATA'),
                             ('J2', 'CHAIN_OUT', 85.09, 'LED_DATA_NEXT', 'SW_DATA_NEXT')]:
    j = Part('Connector_Generic', 'Conn_02x04_Odd_Even', ref, val, 45.72, y,
             'Connector_IDC:IDC-Header_2x04_P2.54mm_Vertical')
    j.cs({'1': '+5V', '3': '+3V3', '5': 'CLK', '7': d7}, 5.08)
    j.cs({'2': 'GND', '4': 'GND', '6': 'LATCH', '8': d8}, 5.08)

# Pico ------------------------------------------------------------------
text('Raspberry Pi Pico  (fit U3 and R5-R8 on module 1 only)', 25, 115, H, True)
text('PIO: GP16 = CLK (side-set 0), GP17 = LATCH (side-set 1),\n'
     'GP18 = LED_DATA (OUT), GP19 = SW_DATA (IN).\n'
     '33R series resistors damp ringing on the ribbon cable.', 25, 123)
pico = Part('MCU_Module', 'RaspberryPi_Pico', 'U3', 'RaspberryPi_Pico', 60.96, 180.34,
            'Module:RaspberryPi_Pico_Common_THT', extra={'Fit': 'Module 1 only'})
pico.cs({'21': 'PICO_CLK', '22': 'PICO_LATCH', '24': 'PICO_LED_DATA', '25': 'PICO_SW_DATA'}, 5.08)
pico.c('40', '+5V'); pico.c('36', '+3V3'); pico.c('3', 'GND')
for n in ['30', '37', '1', '2', '4', '5', '6', '7', '9', '10', '11', '12', '14', '15', '16', '17', '19', '20',
          '26', '27', '29', '31', '32', '34', '35', '33', '39']:
    pico.c(n, 'NC')
for i, (sig) in enumerate(['CLK', 'LATCH', 'LED_DATA', 'SW_DATA']):
    R(f'R{5+i}', '33', 101.6 + i * 10.16, 165.1, f'PICO_{sig}', sig, extra={'Fit': 'Module 1 only'})

# 74HC165: inputs -------------------------------------------------------
text('Inputs: 74HC165 at 3V3', 150, 30, H, True)
text('Shifts toward the Pico. H = board-present marker (always 1), G = footswitch,\n'
     'F..A = spare inputs IN1..IN6. All inputs active low, 3.3 V max.\n'
     'R4 pulls the chain input low, so the bytes after the last module read 0.', 150, 38)
u1 = Part('74xx', '74HC165', 'U1', '74HC165', 233.68, 81.28, FP['DIP16'])
u1.cs({'6': '+3V3', '5': 'FOOTSW', '4': 'IN1', '3': 'IN2', '14': 'IN3', '13': 'IN4',
       '12': 'IN5', '11': 'IN6', '10': 'SW_DATA_NEXT', '1': 'LATCH', '2': 'CLK', '15': 'GND'}, 5.08)
u1.c('16', '+3V3'); u1.c('8', 'GND'); u1.c('9', 'SW_DATA', 5.08); u1.c('7', 'NC')
for i, net in enumerate(['FOOTSW', 'IN1', 'IN2', 'IN3', 'IN4', 'IN5', 'IN6']):
    R(f'R{9+i}', '10k', 152.4 + i * 7.62, 66.04, '+3V3', net)
R('R4', '10k', 190.5, 104.14, 'SW_DATA_NEXT', 'GND')
C('C1', '100n', 266.7, 63.5, '+3V3', 'GND')
C('C3', '100n', 162.56, 104.14, 'FOOTSW', 'GND')
sw = Part('Switch', 'SW_DPDT_x2', 'SW1', 'PBS24-202P', 182.88, 116.84, 'footswitches:PBS24-202P', unit=1)
sw.c('2', 'GND', 5.08); sw.c('3', 'FOOTSW', 5.08); sw.c('1', 'NC')
sw2 = Part('Switch', 'SW_DPDT_x2', 'SW1', 'PBS24-202P', 210.82, 116.84, 'footswitches:PBS24-202P', unit=2)
sw2.cs({'4': 'NC', '5': 'NC', '6': 'NC'})
text('SW1: pin 2 = common, 1 = NC, 3 = NO (verify when parts arrive).\n'
     'Second pole is unused; its pins are only soldered for strength.\n'
     'R9 + C3: about 1 ms RC on the footswitch.', 152.4, 129.54)

# 74HC595: outputs ------------------------------------------------------
text('Outputs: 74HC595 at 3V3', 290, 30, H, True)
text('Shifts away from the Pico. QA..QC = LED red, green, blue (1 = on). QD..QH = OUT1..OUT5,\n'
     '3.3 V logic. The LED runs from 5V through NPN low-side switches Q1-Q3.', 290, 38)
u2 = Part('74xx', '74HC595', 'U2', '74HC595', 314.96, 76.2, FP['DIP16'])
u2.cs({'14': 'LED_DATA', '11': 'CLK', '10': '+3V3', '12': 'LATCH', '13': 'GND'}, 5.08)
u2.cs({'15': 'R_DRV', '1': 'G_DRV', '2': 'B_DRV', '3': 'OUT1', '4': 'OUT2', '5': 'OUT3',
       '6': 'OUT4', '7': 'OUT5', '9': 'LED_DATA_NEXT'}, 5.08)
u2.c('16', '+3V3'); u2.c('8', 'GND')
C('C2', '100n', 345.44, 60.96, '+3V3', 'GND')
C('C4', '10u', 355.6, 60.96, '+5V', 'GND', pol=True)
for i, c in enumerate('RGB'):
    R(f'R{16+i}', '4k7', 297.18 + i * 10.16, 119.38, f'{c}_DRV', f'{c}_BASE')
    q = Part('Transistor_BJT', 'PN2222A', f'Q{1+i}', '2N2222A', 304.8 + i * 30.48, 149.86,
             'Package_TO_SOT_THT:TO-92_Inline_Wide')
    q.c('2', f'{c}_BASE'); q.c('3', f'{c}_SINK'); q.c('1', 'GND')
for i, (rv, c) in enumerate([('560', 'R'), ('390', 'G'), ('390', 'B')]):
    R(f'R{1+i}', rv, 342.9 + i * 10.16, 109.22, f'LED_{c}', f'{c}_SINK')
d1 = Part('Device', 'LED_RAGB', 'D1', 'RGB LED (common anode)', 386.08, 109.22, 'LED_THT:LED_D5.0mm-4_RGB_Staggered_Pins')
d1.cs({'1': 'LED_R', '3': 'LED_G', '4': 'LED_B', '2': '+5V'}, 5.08)
text('LED: common anode only, anode on 5V. Series resistors give about 5 mA per channel:\n'
     '  red (5 - 2.0 - 0.1) / 560 = 5.2 mA, green/blue (5 - 3.1 - 0.1) / 390 = 4.6 mA.\n'
     'Base resistors: (3.3 - 0.7) / 4k7 = 0.55 mA, so Q1-Q3 saturate (Vce about 0.1 V).\n'
     'Q1-Q3: 2N2222A / PN2222A in TO-92, pins E-B-C. Check the pinout of the parts you buy.', 290, 175.26)

# Spare I/O ------------------------------------------------------------
text('Spare I/O header', 150, 170, H, True)
text('Inputs: 3.3 V max, pulled up, active low.  Outputs: 5 V logic, 6 mA max.', 150, 178)
j3 = Part('Connector_Generic', 'Conn_02x08_Odd_Even', 'J3', 'SPARE_IO', 175.26, 205.74,
          'Connector_PinHeader_2.54mm:PinHeader_2x08_P2.54mm_Vertical')
j3.cs({'1': 'IN1', '3': 'IN2', '5': 'IN3', '7': 'IN4', '9': 'IN5', '11': 'IN6', '13': '+3V3', '15': 'GND'}, 5.08)
j3.cs({'2': 'OUT1', '4': 'OUT2', '6': 'OUT3', '8': 'OUT4', '10': 'OUT5', '12': 'GND', '14': '+5V', '16': 'GND'}, 5.08)

# ---------------------------------------------------------------- write
sch = [Sym('kicad_sch'), [Sym('version'), 20250114], [Sym('generator'), 'eeschema'],
       [Sym('generator_version'), '9.0'], [Sym('uuid'), ROOT], [Sym('paper'), 'A3'],
       [Sym('title_block'), [Sym('title'), 'Footswitch module'], [Sym('date'), '2026-11-21'],
        [Sym('rev'), '0.1'], [Sym('comment'), 1, 'USB MIDI footswitch, chainable module. See docs/design.md']],
       [Sym('lib_symbols')] + list(lib_symbols.values())] + items + \
      [[Sym('sheet_instances'), [Sym('path'), '/', [Sym('page'), '1']]], [Sym('embedded_fonts'), Sym('no')]]
open(sys.argv[1], 'w').write(dump(sch) + '\n')
