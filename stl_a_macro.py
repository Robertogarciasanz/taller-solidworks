"""STL -> macro SolidWorks (.swp): reconstruye la pieza por capas (cortes + extrusiones).

1. Elige el eje con el que la pieza se parece mas a una pila de extrusiones.
2. Corta la malla en cada tramo entre caras planas y saca los contornos (con huecos).
3. Detecta circulos y quita puntos alineados.
4. Escribe VBA que dibuja cada contorno y lo extruye; lo guarda como .swp.
"""
import math
import os

import tareas
import swp_escribir

TOL_NIVEL = 0.05      # mm: caras planas a esta distancia son el mismo nivel
TOL_PUNTO = 1e-4


# ------------------------------------------------------------------ geometria
def _normal_area(t):
    a, b, c = t
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    l = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
    return ((n[0] / l, n[1] / l, n[2] / l) if l else (0, 0, 0)), l / 2


def volumen(tri):
    s = 0.0
    for a, b, c in tri:
        s += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0]))
    return abs(s / 6)


def niveles(tri, eje):
    """Posiciones de las caras planas perpendiculares al eje (mm)."""
    pos = []
    for t in tri:
        n, _ = _normal_area(t)
        if abs(n[eje]) > 0.999:
            pos.append(sum(p[eje] for p in t) / 3)
    pos.sort()
    res = []
    for p in pos:
        if not res or p - res[-1][-1] > TOL_NIVEL:
            res.append([p])
        else:
            res[-1].append(p)
    return [sum(g) / len(g) for g in res]


def _uv(p, eje):
    # coordenadas del croquis sobre el plano base de cada eje (Alzado, Planta, Vista lateral)
    if eje == 2:
        return (p[0], p[1])
    if eje == 1:
        return (p[0], -p[2])
    return (-p[2], p[1])


def seccion(tri, eje, c):
    """Contornos cerrados (listas de (u,v)) del corte a altura c."""
    segs = []
    for t in tri:
        d = [p[eje] - c for p in t]
        if all(x > 0 for x in d) or all(x < 0 for x in d):
            continue
        pts = []
        for i in range(3):
            j = (i + 1) % 3
            if (d[i] > 0) != (d[j] > 0):
                s = d[i] / (d[i] - d[j])
                q = tuple(t[i][k] + s * (t[j][k] - t[i][k]) for k in range(3))
                pts.append(_uv(q, eje))
        if len(pts) == 2:
            segs.append(pts)
    clave = lambda p: (round(p[0] / 1e-3), round(p[1] / 1e-3))
    ady = {}
    for a, b in segs:
        ady.setdefault(clave(a), []).append((a, b))
        ady.setdefault(clave(b), []).append((b, a))
    usado = set()
    lazos = []
    for a, b in segs:
        ka, kb = clave(a), clave(b)
        if (ka, kb) in usado or (kb, ka) in usado:
            continue
        lazo = [a]
        usado.add((ka, kb))
        actual, kact = b, kb
        while kact != ka:
            lazo.append(actual)
            sig = None
            for p, q in ady.get(kact, []):
                kp, kq = clave(p), clave(q)
                if (kp, kq) not in usado and (kq, kp) not in usado:
                    sig = (p, q); usado.add((kp, kq)); break
            if sig is None:
                break
            actual, kact = sig[1], clave(sig[1])
        else:
            if len(lazo) >= 3:
                lazos.append(lazo)
    return lazos


def area_firmada(l):
    return sum(l[i][0] * l[(i + 1) % len(l)][1] - l[(i + 1) % len(l)][0] * l[i][1] for i in range(len(l))) / 2


def area_seccion(lazos):
    """Area neta con regla par-impar (huecos restan)."""
    tot = 0.0
    for l in lazos:
        prof = sum(1 for m in lazos if m is not l and _dentro(l[0], m))
        tot += abs(area_firmada(l)) * (1 if prof % 2 == 0 else -1)
    return tot


def _dentro(p, poli):
    x, y = p
    d = False
    for i in range(len(poli)):
        x1, y1 = poli[i]
        x2, y2 = poli[(i + 1) % len(poli)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            d = not d
    return d


def simplificar(l):
    """Quita puntos alineados y duplicados."""
    p = [l[0]]
    for q in l[1:]:
        if math.hypot(q[0] - p[-1][0], q[1] - p[-1][1]) > 0.01:
            p.append(q)
    if len(p) > 1 and math.hypot(p[0][0] - p[-1][0], p[0][1] - p[-1][1]) <= 0.01:
        p.pop()
    cambio = True
    while cambio and len(p) > 3:
        cambio = False
        for i in range(len(p)):
            a, b, c = p[i - 1], p[i], p[(i + 1) % len(p)]
            cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            if abs(cr) < 0.002 * max(1.0, math.hypot(c[0] - a[0], c[1] - a[1])):
                p.pop(i); cambio = True; break
    return p


def circulo(l):
    """(cx, cy, r) si el contorno es un circulo, si no None."""
    if len(l) < 10:
        return None
    cx = sum(p[0] for p in l) / len(l)
    cy = sum(p[1] for p in l) / len(l)
    rs = [math.hypot(p[0] - cx, p[1] - cy) for p in l]
    r = sum(rs) / len(rs)
    if r > 0.05 and max(abs(x - r) for x in rs) < 0.01 * r + 0.01:
        return (cx, cy, r)
    return None


def firma(lazos):
    """Huella de una seccion para unir capas iguales."""
    return sorted((round(abs(area_firmada(l)), 1),
                   round(sum(p[0] for p in l) / len(l), 1), round(sum(p[1] for p in l) / len(l), 1)) for l in lazos)


def iguales(f1, f2):
    return len(f1) == len(f2) and all(abs(a[0] - b[0]) <= 0.02 * max(1, a[0]) + 0.1 and abs(a[1] - b[1]) < 0.3 and abs(a[2] - b[2]) < 0.3
                                       for a, b in zip(f1, f2))


# ------------------------------------------------------------------ capas
def capas(tri, eje):
    """[(z0, z1, lazos)] ya fusionando tramos iguales."""
    niv = niveles(tri, eje)
    zs = [p[eje] for t in tri for p in t]
    lo, hi = min(zs), max(zs)
    marcas = sorted(set([round(lo, 4), round(hi, 4)] + [round(n, 4) for n in niv if lo < n < hi]))
    res = []
    for a, b in zip(marcas, marcas[1:]):
        if b - a < 0.02:
            continue
        areas = []
        for f in (0.25, 0.5, 0.75):
            areas.append(area_seccion(seccion(tri, eje, a + (b - a) * f)))
        if max(areas) - min(areas) > 0.01 * max(1.0, max(areas)):
            n = 8                       # superficie inclinada o curva: aproximar por escalones
            sub = [(a + (b - a) * i / n, a + (b - a) * (i + 1) / n) for i in range(n)]
        else:
            sub = [(a, b)]
        for s0, s1 in sub:
            res.append((s0, s1, seccion(tri, eje, (s0 + s1) / 2)))
    fus = []
    for z0, z1, lz in res:
        f = firma(lz)
        if fus and iguales(fus[-1][3], f) and abs(fus[-1][1] - z0) < 1e-6:
            fus[-1] = (fus[-1][0], z1, fus[-1][2], fus[-1][3])
        else:
            fus.append((z0, z1, lz, f))
    return [(a, b, lz) for a, b, lz, _ in fus]


def reconstruido(cp):
    return sum(area_seccion(lz) * (b - a) for a, b, lz in cp)


def mejor_eje(tri):
    v = volumen(tri)
    mejor = None
    for e in (2, 1, 0):
        cp = capas(tri, e)
        err = abs(reconstruido(cp) - v) / v
        nseg = sum(len(simplificar(l)) for _, _, lz in cp for l in lz)
        puntos = err * 1000 + nseg / 100
        if mejor is None or puntos < mejor[0]:
            mejor = (puntos, e, cp, err, nseg)
    return mejor[1], mejor[2], mejor[3], mejor[4]


if __name__ == "__main__":
    import sys
    tri = tareas._leer_stl(sys.argv[1])
    print("volumen STL %.1f mm3" % volumen(tri))
    for e in (2, 1, 0):
        cp = capas(tri, e)
        err = abs(reconstruido(cp) - volumen(tri)) / volumen(tri)
        seg = 0; circ = 0
        for _, _, lz in cp:
            for l in lz:
                if circulo(l): circ += 1
                else: seg += len(simplificar(l))
        print("eje", "XYZ"[e], "capas", len(cp), "error vol %.2f%%" % (err * 100), "segmentos", seg, "circulos", circ)
