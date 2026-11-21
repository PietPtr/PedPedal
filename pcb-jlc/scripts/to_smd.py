"""One-off: turn the copied THT schematic into the JLCPCB SMD variant.

Already applied to footswitch_jlc.kicad_sch, which is now the source of truth. Kept as a
record of what changed. Running it again on the converted file does nothing harmful, but
it would overwrite edits made since to the fields it sets.

Usage: python3 to_smd.py footswitch_jlc.kicad_sch
"""
import copy, re, sys, uuid
sys.path.insert(0, __file__.rsplit('/', 3)[0] + '/pcb/scripts')
import sx
from sx import Sym, find, find1, dump

R0805 = 'Resistor_SMD:R_0805_2012Metric'
C0805 = 'Capacitor_SMD:C_0805_2012Metric'
SOIC16 = 'Package_SO:SOIC-16_3.9x9.9mm_P1.27mm'
SOT23 = 'Package_TO_SOT_SMD:SOT-23'
IDC = 'footswitches:IDC-Header_2x04_P2.54mm_Vertical_SMD_JLC'

# ref -> (footprint, LCSC part, value or None to keep). LCSC parts are from JLCPCB's parts
# library, Basic where one exists (see docs/bom.md). '' = hand-soldered, not assembled by JLC.
PARTS = {
    'U1': (SOIC16, 'C5613', None),          # 74HC165D,653 (Nexperia), preferred extended
    'U2': (SOIC16, 'C5947', None),          # 74HC595D,118 (Nexperia), basic
    'Q1': (SOT23, 'C8512', 'MMBT2222A'), 'Q2': (SOT23, 'C8512', 'MMBT2222A'), 'Q3': (SOT23, 'C8512', 'MMBT2222A'),
    'R1': (R0805, 'C28636', None),          # 560
    'R2': (R0805, 'C17655', None), 'R3': (R0805, 'C17655', None),   # 390
    'R4': (R0805, 'C17414', None), 'R9': (R0805, 'C17414', None),   # 10k
    'R5': (R0805, 'C17634', None), 'R6': (R0805, 'C17634', None),   # 33
    'R7': (R0805, 'C17634', None), 'R8': (R0805, 'C17634', None),
    'R16': (R0805, 'C17673', None), 'R17': (R0805, 'C17673', None), 'R18': (R0805, 'C17673', None),  # 4k7
    'C1': (C0805, 'C49678', None), 'C2': (C0805, 'C49678', None), 'C3': (C0805, 'C49678', None),     # 100n 50V X7R
    'C4': (C0805, 'C15850', None),          # 10u 25V X5R
    'J1': (IDC, 'C56143593', None), 'J2': (IDC, 'C56143593', None),
    'D1': (None, '', None), 'SW1': (None, '', None), 'U3': (None, '', None),
}
NEW_SYMBOL = {'Q': ('Transistor_BJT', 'MMBT2222A'), 'C4': ('Device', 'C')}


def u(): return str(uuid.uuid4())


def prop(sym, name):
    for p in find(sym, 'property'):
        if p[1] == name: return p


def main(path):
    text = open(path).read()
    text = text.replace('(project "footswitch"', '(project "footswitch_jlc"')
    sch = sx.parse(text)
    libsyms = find1(sch, 'lib_symbols')
    have = {s[1] for s in find(libsyms, 'symbol')}
    for lib, name in NEW_SYMBOL.values():
        key = f'{lib}:{name}'
        if key not in have:
            s = sx.flat_symbol(lib, name); s[1] = key; libsyms.append(s); have.add(key)
    for sym in find(sch, 'symbol'):
        ref = prop(sym, 'Reference')
        if not ref or ref[2] not in PARTS: continue
        r = ref[2]
        fp, lcsc, value = PARTS[r]
        key = 'Q' if r.startswith('Q') else r
        if key in NEW_SYMBOL:
            find1(sym, 'lib_id')[1] = ':'.join(NEW_SYMBOL[key])
        if fp: prop(sym, 'Footprint')[2] = fp
        if value: prop(sym, 'Value')[2] = value
        fit = prop(sym, 'Fit')
        if fit: sym.remove(fit)       # JLC fits R5-R8 on every module; only the Pico is module 1 only
        if r == 'U3':
            sym.insert(sym.index(prop(sym, 'Footprint')) + 1,
                       [Sym('property'), 'Fit', 'Module 1 only, hand-soldered', [Sym('at'), *find1(sym, 'at')[1:3], 0],
                        [Sym('effects'), [Sym('font'), [Sym('size'), 1.27, 1.27]], [Sym('hide'), Sym('yes')]]])
        old = prop(sym, 'LCSC')
        if old: sym.remove(old)
        at = find1(sym, 'at')
        sym.insert(sym.index(prop(sym, 'Footprint')) + 1,
                   [Sym('property'), 'LCSC', lcsc, [Sym('at'), at[1], at[2], 0],
                    [Sym('effects'), [Sym('font'), [Sym('size'), 1.27, 1.27]], [Sym('hide'), Sym('yes')]]])
    tb = find1(sch, 'title_block')
    find1(tb, 'title')[1] = 'Footswitch module (JLCPCB SMD assembly)'
    for c in find(tb, 'comment'):
        if str(c[1]) == '1': c[2] = 'USB MIDI footswitch, chainable module. SMD variant, see docs/design.md'
    open(path, 'w').write(dump(sch) + '\n')


main(sys.argv[1])
