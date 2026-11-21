import sx, sys
FPD='/usr/share/kicad/footprints/'
def path(fpid):
    lib, name = fpid.split(':')
    d = '/home/pieter/projects/rust/footswitches/pcb/footswitches.pretty' if lib == 'footswitches' else FPD + lib + '.pretty'
    return f'{d}/{name}.kicad_mod'
def load(fpid): return sx.parse(open(path(fpid)).read())
def crtyd(fp):
    xs, ys = [], []
    for e in fp:
        if isinstance(e, list) and e and str(e[0]).startswith('fp_') and sx.find1(e, 'layer') and sx.find1(e, 'layer')[1] == 'F.CrtYd':
            if e[0] == 'fp_circle':
                c = sx.find1(e,'center'); en = sx.find1(e,'end'); r = ((float(en[1])-float(c[1]))**2+(float(en[2])-float(c[2]))**2)**.5
                xs += [float(c[1])-r, float(c[1])+r]; ys += [float(c[2])-r, float(c[2])+r]
            for k in ('start', 'end', 'mid', 'center'):
                if e[0] == 'fp_circle': break
                p = sx.find1(e, k)
                if p: xs.append(float(p[1])); ys.append(float(p[2]))
            pts = sx.find1(e, 'pts')
            if pts:
                for xy in sx.find(pts, 'xy'): xs.append(float(xy[1])); ys.append(float(xy[2]))
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None
def pads(fp):
    return [(p[1], float(sx.find1(p,'at')[1]), float(sx.find1(p,'at')[2])) for p in sx.find(fp, 'pad')]
if __name__ == '__main__':
    for f in sys.argv[1:]:
        fp = load(f); print(f, 'crtyd', crtyd(fp)); print('   ', pads(fp))
