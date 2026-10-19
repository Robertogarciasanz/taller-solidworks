"""STL -> receta de pieza (ver RECETA.md), con el planificador "saliente base + cortes" de stl_vba.

Uso:  py receta_stl.py pieza.STL [salida.receta.json]

Coordenadas: stl_a_macro._uv / stl_vba._modelo ya siguen la convencion de SolidWorks de RECETA.md
(eje Z -> Alzado (X, Y); eje Y -> Planta (X, -Z); eje X -> Lateral (-Z, Y)), asi que el croquis (u, v)
del planificador se usa tal cual y la distancia a lo largo de la normal es la coordenada del eje.
"""
import math
import os
import sys

import receta_comun as rc          # pone el directorio padre en sys.path

import tareas
import stl_vba
from stl_a_macro import volumen as volumen_stl

PLANO = {2: "Alzado", 1: "Planta", 0: "Lateral"}
ALARGAR = 1.0                       # mm: los cortes pasantes sobresalen para no dejar caras coincidentes


# ------------------------------------------------------------------ copias corregidas de stl_vba
# stl_vba._arco_ok solo comprueba los vertices: aceptaba "arcos" que se tragan una recta larga entre dos
# esquinas redondeadas (caja66: fondo de un vaciado con flecha de 2 mm). Aqui ademas cada tramo
# del poligono debe separarse poco del arco (flecha pequena), como en una teselacion de verdad.
def _arco_ok(pts):
    r = stl_vba._arco_ok(pts)
    if not r:
        return None
    (cx, cy, rad), _ = r
    fmax = min(0.3, max(0.06, 0.03 * rad))
    for a, b in zip(pts, pts[1:]):
        cuerda = math.hypot(b[0] - a[0], b[1] - a[1])
        if cuerda > rad:                                   # tramo de mas de 60 grados: no es un arco teselado
            return None
        if rad - math.sqrt(max(rad * rad - cuerda * cuerda / 4, 0.0)) > fmax:
            return None                                    # el tramo recto se separa demasiado del arco
    return r


def entidades(l):
    """stl_vba.entidades con el _arco_ok de arriba."""
    c = stl_vba.circulo(l)
    if c:
        return [("C",) + c]
    p = stl_vba._limpiar(l)
    n = len(p)
    ang = [stl_vba._angulo(p[i - 1], p[i], p[(i + 1) % n]) for i in range(n)]
    i0 = max(range(n), key=lambda i: ang[i])
    p = p[i0:] + p[:i0]
    p.append(p[0])
    ents = []
    i = 0
    while i < n:
        mejor = None
        k = i + 3
        while k <= n:
            r = _arco_ok(p[i:k + 1])
            if not r:
                break
            mejor = (k, r)
            k += 1
        if mejor:
            k, (cc, sg) = mejor
            ents.append(("A", (cc[0], cc[1]), p[i], p[k], sg))
            i = k
            continue
        ents.append(("L", p[i], p[i + 1]))
        i += 1
    return stl_vba._encadenar(ents)


def ents_anillo(anillo):
    try:
        e = entidades(anillo)
        if stl_vba._valido(e):
            return e
    except (ValueError, IndexError, ZeroDivisionError):
        pass
    return stl_vba.entidades_lineas(anillo, 0.01, 4)


R_STD = (0.25, 0.5, 0.75, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 15)


def radio_std(r):
    """Radio normalizado solo si esta muy cerca (stl_vba.radio_std convertia 7 mm en 8 mm)."""
    s = min(R_STD, key=lambda x: abs(x - r))
    return s if abs(s - r) <= max(0.02, 0.02 * r) else round(r, 1)


CRECER_ISLA = 0.05     # mm


def _tangente(h, borde):
    """True si el lazo h toca el contorno borde y se separa de el de forma tangente (sin esquina)."""
    from shapely.geometry import Point
    zona = borde.buffer(0.02)
    contacto = h.intersection(zona)
    if contacto.is_empty:
        return False
    L = h.length
    for c in getattr(contacto, "geoms", [contacto]):
        extremos = list(c.boundary.geoms) if c.geom_type == "LineString" else [c] if c.geom_type == "Point" else []
        for e in extremos:
            s = h.project(e)
            for ds in (1.0, -1.0):
                q = h.interpolate((s + ds) % L)
                if not zona.contains(q) and q.distance(borde) < 0.3:
                    return True                    # a 1 mm del contacto sigue casi pegado: tangencia
    return False


def sin_tangencias(gcorte, material):
    """Islas de un corte (lazos interiores: material que se queda) tangentes al contorno de la pieza.

    Si una isla se separa del contorno de forma tangente (Brazo_engranaje: resaltes redondos que siguen el
    borde de la placa y se separan de el sin esquina), el booleano de FreeCAD/OCC falla o deja un solido no
    valido. Esas islas se agrandan CRECER_ISLA mm: lo que crece por fuera de la pieza no cambia nada y las
    paredes de la isla quedan 0,05 mm mas gruesas (error de volumen despreciable). Las islas que solo tocan
    el contorno en esquinas (caja66) no se tocan.
    """
    from shapely.geometry import Polygon
    if material.is_empty:
        return gcorte
    borde = material.boundary
    res = []
    for p in stl_vba._polis(gcorte):
        islas = []
        for h in p.interiors:
            isla = Polygon(h)
            if _tangente(h, borde):
                isla = isla.buffer(CRECER_ISLA, join_style="mitre")
            islas.append(isla)
        q = Polygon(p.exterior)
        if islas:
            q = q.difference(stl_vba._union(islas))
        res.append(q)
    return stl_vba._union(res)


def croquis_ents(g):
    """Como stl_vba.croquis, pero devuelve los lazos como entidades de receta (no lineas VBA).

    -> (perfiles, esquinas [((u, v), radio)]): arcos tangentes pasados a esquina viva (redondeo al final)
    salvo que el croquis quede invalido o la esquina toque otro contorno.
    """
    from shapely.geometry import LinearRing
    anillos = []
    for p in stl_vba._polis(g):
        for r in [p.exterior] + list(p.interiors):
            e = ents_anillo(list(r.coords)[:-1])
            ea, esq = stl_vba.afilar(e)
            anillos.append([e, ea, esq])
    lr = []
    for a in anillos:
        try:
            x = LinearRing(stl_vba._muestrear(a[1]))
            ok = x.is_valid
        except ValueError:
            ok = False
        if not ok:
            a[1], a[2] = a[0], []
            x = LinearRing(stl_vba._muestrear(a[0]))
        lr.append(x)
    for i in range(len(anillos)):                      # una esquina viva no puede tocar otro contorno
        for j in range(len(anillos)):
            if i != j and anillos[i][2] and lr[i].distance(lr[j]) < 0.01:
                anillos[i][1], anillos[i][2] = anillos[i][0], []
                lr[i] = LinearRing(stl_vba._muestrear(anillos[i][0]))
    perfiles = [rc.cerrar_lazo([rc.ent_de_stl(e) for e in a[1]], tol=1e-3) for a in anillos]
    return perfiles, [s for a in anillos for s in a[2]]


def receta_desde_tri(tri, nombre, origen, plan=None):
    """Triangulos -> (receta, info)."""
    pl = plan or stl_vba.elegir(tri)
    eje = pl["eje"]
    plano = PLANO[eje]
    zs = [p[eje] for t in tri for p in t]
    zlo, zhi = min(zs), max(zs)
    ops, esquinas = [], []                                      # esquinas: (u, v, z0, z1, radio)
    for k, (a, b, g) in enumerate(pl["salientes"], 1):
        z0, z1 = pl["z"][a][0], pl["z"][b][1]
        perf, esq = croquis_ents(g)
        ops.append({"tipo": "saliente", "nombre": "Saliente-Extruir%d" % k, "plano": plano,
                    "desde": rc._r(z0), "hasta": rc._r(z1), "perfiles": perf})
        esquinas += [(u, v, z0, z1, r) for (u, v), r in esq]
    for k, (a, b, g) in enumerate(pl["cortes"], 1):
        z0, z1 = pl["z"][a][0], pl["z"][b][1]
        abajo, arriba = z0 <= zlo + 1e-6, z1 >= zhi - 1e-6
        if abajo:
            z0 -= ALARGAR
        if arriba:
            z1 += ALARGAR
        material = stl_vba._union([gs for a2, b2, gs in pl["salientes"]
                                   if pl["z"][a2][0] < min(z1, zhi) and pl["z"][b2][1] > max(z0, zlo)])
        perf, esq = croquis_ents(sin_tangencias(g, material))
        ops.append({"tipo": "corte", "nombre": "Cortar-Extruir%d" % k, "plano": plano,
                    "desde": rc._r(z0), "hasta": rc._r(z1), "pasante": bool(abajo and arriba), "perfiles": perf})
        esquinas += [(u, v, max(z0, zlo), min(z1, zhi), r) for (u, v), r in esq]
    redondeos = redondeos_finales(ops, esquinas, eje, zlo, zhi)
    variables = {}
    s0 = ops[0]
    if abs(s0["desde"]) < 1e-6:                                 # altura del saliente base como variable principal
        variables["altura_base"] = s0["hasta"]
        s0["cotas"] = {"hasta": "altura_base"}
    receta = {"version": 1, "nombre": nombre, "origen": origen, "variables": variables,
              "operaciones": ops, "redondeos": redondeos}
    info = dict(eje="XYZ"[eje], plano=plano, salientes=len(pl["salientes"]), cortes=len(pl["cortes"]),
                err_plan=pl["err"], vol_stl=volumen_stl(tri), zlo=zlo, zhi=zhi)
    return receta, info


def redondeos_finales(ops, esquinas, eje, zlo, zhi):
    """Esquinas afiladas [(u, v, z0, z1, radio)] -> lista de redondeos de la receta (al final).

    Agrupados por radio normalizado; solo las esquinas que siguen siendo arista de la pieza terminada (la de
    un corte que cae fuera del material o que otro corte borra no existe). El punto se pone a media altura del
    tramo mas largo (entre cotas de operaciones) donde la esquina sigue en el contorno de la seccion final.
    """
    from shapely.geometry import Point
    plano_ops = {"operaciones": ops}
    marcas = sorted({min(max(float(o[k]), zlo), zhi) for o in ops for k in ("desde", "hasta")} | {zlo, zhi})
    secciones = {}
    vivas = []
    for u, v, za, zb, r in esquinas:
        tramos = [(a, b) for a, b in zip(marcas, marcas[1:]) if a >= za - 1e-6 and b <= zb + 1e-6 and b - a > 1e-6]
        for a, b in sorted(tramos, key=lambda t: t[0] - t[1]):
            w = (a + b) / 2
            if w not in secciones:
                secciones[w] = rc.region_en(plano_ops, w).boundary
            if secciones[w].distance(Point(u, v)) < 0.01:
                vivas.append((stl_vba._modelo(u, v, w, eje), r))
                break
    esquinas = vivas
    grupos = {}
    for pt, r in esquinas:
        pts = grupos.setdefault(radio_std(r), [])
        q = [rc._r(c) for c in pt]
        if q not in pts:
            pts.append(q)
    return [{"radio": r, "puntos": pts} for r, pts in sorted(grupos.items(), reverse=True)]


def receta_desde_stl(ruta):
    """Archivo STL -> (receta, info). info lleva vol_stl, vol_receta, err_vol y caja_stl."""
    tri = tareas._leer_stl(ruta)
    if not tri:
        raise ValueError("el STL no tiene triangulos: " + ruta)
    nombre = os.path.splitext(os.path.basename(ruta))[0]
    receta, info = receta_desde_tri(tri, nombre, "STL " + os.path.basename(ruta))
    info["vol_receta"] = rc.volumen(receta)                     # con los redondeos aproximados en 2D
    info["vol_sin_redondeos"] = rc.volumen(receta, con_redondeos=False)
    info["err_vol"] = abs(info["vol_receta"] - info["vol_stl"]) / info["vol_stl"]
    info["caja_stl"] = [[min(p[i] for t in tri for p in t) for i in range(3)],
                        [max(p[i] for t in tri for p in t) for i in range(3)]]
    return receta, info


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    ruta = argv[1]
    destino = argv[2] if len(argv) > 2 else rc.ruta_receta(ruta)
    receta, info = receta_desde_stl(ruta)
    errores = rc.validar(receta)
    rc.guardar(receta, destino)
    print("%s: eje %s (%s), %s" % (os.path.basename(ruta), info["eje"], info["plano"], rc.resumen(receta)))
    print("  volumen STL %.1f mm3, receta %.1f mm3 (sin redondeos %.1f), error %.2f %%"
          % (info["vol_stl"], info["vol_receta"], info["vol_sin_redondeos"], info["err_vol"] * 100))
    print("  receta: " + destino)
    for e in errores:
        print("  ERROR: " + e)
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
