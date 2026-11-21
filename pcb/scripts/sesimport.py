import sys, json, sx
from sx import find, find1
ses = sx.parse(open(sys.argv[1]).read())
routes = find1(ses, 'routes')
res = find1(routes, 'resolution'); scale = {'um': 1e-3, 'mm': 1.0, 'mil': 0.0254}[str(res[1])] / float(res[2])
tracks, vias = [], []
for n in find(find1(routes, 'network_out'), 'net'):
    name = n[1]
    for w in find(n, 'wire'):
        p = find1(w, 'path'); layer = p[1]; width = float(p[2]) * scale
        pts = [(float(p[i]) * scale, -float(p[i + 1]) * scale) for i in range(3, len(p), 2)]
        for a, b in zip(pts, pts[1:]):
            tracks.append(dict(x0=a[0], y0=a[1], x1=b[0], y1=b[1], w=round(width, 3), layer=layer, net=name))
    for v in find(n, 'via'):
        vias.append(dict(x=float(v[2]) * scale, y=-float(v[3]) * scale, net=name))
json.dump(dict(tracks=tracks, vias=vias), open(sys.argv[2], 'w'))
print(len(tracks), 'segments', len(vias), 'vias')
