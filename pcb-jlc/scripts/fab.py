"""Write the JLCPCB order files for the SMD board into pcb-jlc/fab/.

  fab/footswitch_jlc-gerbers.zip   gerbers + Excellon drill files (upload as the PCB)
  fab/footswitch_jlc-bom.csv       BOM: Comment, Designator, Footprint, LCSC Part #
  fab/footswitch_jlc-cpl.csv       placement: Designator, Mid X, Mid Y, Layer, Rotation

Parts with an empty LCSC field (D1, SW1, U3) are hand-soldered and left out of the BOM and
CPL. Everything uses the board's drill/place origin (bottom-left corner), so the coordinates
are positive and the gerbers, drill files and CPL line up.

Usage: python3 scripts/fab.py        (from anywhere)
"""
import csv, os, re, shutil, subprocess, sys, tempfile, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PRJ, '..', 'pcb', 'scripts'))
import sx
from sx import find, find1

BOARD = os.path.join(PRJ, 'footswitch_jlc.kicad_pcb')
OUT = os.path.join(PRJ, 'fab')
NAME = 'footswitch_jlc'
LAYERS = 'F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts'

# JLC's footprints (from EasyEDA, checked against KiCad's) are rotated differently from
# KiCad's for some packages. CPL rotation = KiCad rotation + offset.
ROT_OFFSET = [
    (r'^Package_SO:SOIC-', 270),        # JLC: long axis horizontal, pin 1 bottom left
    (r'^Package_TO_SOT_SMD:SOT-23', 180),  # JLC: pins 1, 2 on the right
    (r'^footswitches:IDC-Header_2x04_P2.54mm_Vertical_SMD_JLC', 270),  # C56143593: rows horizontal, pin 1 bottom left
    (r'.', 0),
]


def run(*args):
    subprocess.run(['kicad-cli', *args], check=True, stdout=subprocess.DEVNULL)


def footprints():
    board = sx.parse(open(BOARD).read())
    res = []
    for fp in find(board, 'footprint'):
        props = {p[1]: p[2] for p in find(fp, 'property')}
        res.append(dict(ref=props['Reference'], value=props.get('Value', ''), fpid=fp[1],
                        lcsc=props.get('LCSC', ''), layer=find1(fp, 'layer')[1]))
    return res


def natural(ref):
    m = re.match(r'([A-Za-z]+)(\d+)', ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def main():
    os.makedirs(OUT, exist_ok=True)
    fps = [f for f in footprints() if f['lcsc']]
    assert all(f['layer'] == 'F.Cu' for f in fps), 'JLC economic assembly: all SMD parts on the top side'

    # gerbers + drill
    with tempfile.TemporaryDirectory() as tmp:
        g = os.path.join(tmp, 'g')
        run('pcb', 'export', 'gerbers', BOARD, '-o', g + '/', '-l', LAYERS, '--use-drill-file-origin',
            '--subtract-soldermask')
        run('pcb', 'export', 'drill', BOARD, '-o', g + '/', '--drill-origin', 'plot', '--excellon-separate-th',
            '--excellon-units', 'mm', '--excellon-zeros-format', 'decimal')
        files = sorted(os.listdir(g))
        zpath = os.path.join(OUT, f'{NAME}-gerbers.zip')
        with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(os.path.join(g, f), f)
        print('wrote', zpath, f'({len(files)} files: {", ".join(files)})')

        # placement: KiCad's position file, then JLC's column names and rotations
        pos = os.path.join(tmp, 'pos.csv')
        run('pcb', 'export', 'pos', BOARD, '-o', pos, '--side', 'front', '--format', 'csv', '--units', 'mm',
            '--use-drill-file-origin')
        rows = list(csv.DictReader(open(pos)))
    byref = {f['ref']: f for f in fps}
    cpl = []
    for r in rows:
        f = byref.get(r['Ref'])
        if not f: continue
        off = next(o for pat, o in ROT_OFFSET if re.search(pat, f['fpid']))
        cpl.append([r['Ref'], f"{float(r['PosX']):.4f}mm", f"{float(r['PosY']):.4f}mm", 'Top',
                    f"{(float(r['Rot']) + off) % 360:g}"])
    missing = set(byref) - {c[0] for c in cpl}
    assert not missing, f'not in the position file: {missing}'
    cpl.sort(key=lambda c: natural(c[0]))
    with open(os.path.join(OUT, f'{NAME}-cpl.csv'), 'w', newline='') as fh:
        w = csv.writer(fh); w.writerow(['Designator', 'Mid X', 'Mid Y', 'Layer', 'Rotation']); w.writerows(cpl)

    # BOM, exactly one line per LCSC part: JLC rejects two lines matched to the same part
    # (J1 and J2 have different values but are the same connector).
    groups = {}
    for f in fps:
        groups.setdefault(f['lcsc'], []).append(f)
    with open(os.path.join(OUT, f'{NAME}-bom.csv'), 'w', newline='') as fh:
        w = csv.writer(fh); w.writerow(['Comment', 'Designator', 'Footprint', 'LCSC Part #'])
        for lcsc, parts in sorted(groups.items(), key=lambda kv: min((natural(f['ref']) for f in kv[1]))):
            parts.sort(key=lambda f: natural(f['ref']))
            fpnames = {f['fpid'].split(':')[1] for f in parts}
            assert len(fpnames) == 1, f'{lcsc} used with different footprints: {fpnames}'
            value = ' / '.join(dict.fromkeys(f['value'] for f in parts))
            w.writerow([value, ','.join(f['ref'] for f in parts), fpnames.pop(), lcsc])
    print('wrote', f'{NAME}-bom.csv ({len(groups)} lines) and {NAME}-cpl.csv ({len(cpl)} parts) in', OUT)


main()
