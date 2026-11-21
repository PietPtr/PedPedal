import re
class Sym(str): pass
def parse(text):
    toks = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text)
    pos = 0
    def rd():
        nonlocal pos
        t = toks[pos]; pos += 1
        if t == '(':
            l = []
            while toks[pos] != ')':
                l.append(rd())
            pos += 1
            return l
        if t.startswith('"'):
            return t[1:-1].replace('\\"','"').replace('\\\\','\\')
        return Sym(t)
    return rd()
def dump(x, ind=0):
    if isinstance(x, list):
        if all(not isinstance(e, list) for e in x) and len(x) < 12:
            return '(' + ' '.join(dump(e) for e in x) + ')'
        s = '(' + dump(x[0])
        for e in x[1:]:
            s += ('\n' + '\t'*(ind+1) + dump(e, ind+1)) if isinstance(e, list) else ' ' + dump(e)
        return s + '\n' + '\t'*ind + ')'
    if isinstance(x, Sym): return str(x)
    if isinstance(x, (int, float)): 
        return (f'{x:.4f}'.rstrip('0').rstrip('.')) if isinstance(x, float) else str(x)
    return '"' + x.replace('\\','\\\\').replace('"','\\"').replace('\n','\\n') + '"'
def find(l, key):
    return [e for e in l if isinstance(e, list) and e and e[0] == key]
def find1(l, key):
    r = find(l, key); return r[0] if r else None
_libs = {}
def lib(name):
    if name not in _libs:
        _libs[name] = parse(open(f'/usr/share/kicad/symbols/{name}.kicad_sym').read())
    return _libs[name]
def get_symbol(libname, name):
    for s in find(lib(libname), 'symbol'):
        if s[1] == name: return s
    raise KeyError(name)
def flat_symbol(libname, name):
    """Return a flattened copy of a library symbol (resolves extends)."""
    import copy
    s = copy.deepcopy(get_symbol(libname, name))
    ext = find1(s, 'extends')
    if ext is None: return s
    parent = flat_symbol(libname, ext[1])
    out = [Sym('symbol'), name]
    child_props = {p[1]: p for p in find(s, 'property')}
    for e in parent[2:]:
        if isinstance(e, list) and e[0] == 'property' and e[1] in child_props:
            out.append(child_props.pop(e[1]))
        elif isinstance(e, list) and e[0] == 'symbol':
            sub = copy.deepcopy(e); sub[1] = sub[1].replace(parent[1], name, 1); out.append(sub)
        else:
            out.append(e)
    # insert leftover child props after the last property
    idx = max(i for i, e in enumerate(out) if isinstance(e, list) and e[0] == 'property')
    for p in child_props.values():
        idx += 1; out.insert(idx, p)
    return out
def pins(sym):
    """yield (unit, number, name, type, x, y, angle) for every pin in a flattened symbol."""
    res = []
    for sub in find(sym, 'symbol'):
        m = re.search(r'_(\d+)_(\d+)$', sub[1]); unit = int(m.group(1))
        for p in find(sub, 'pin'):
            at = find1(p, 'at'); 
            res.append((unit, find1(p,'number')[1], find1(p,'name')[1], str(p[1]), float(at[1]), float(at[2]), float(at[3]) if len(at)>3 else 0))
    return res
