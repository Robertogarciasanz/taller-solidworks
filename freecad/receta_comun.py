"""Utilidades comunes de las recetas de pieza (ver RECETA.md): entidades, volumen, validacion y escritura.

Python puro (shapely); no necesita FreeCAD ni SolidWorks.
"""
import json
import math
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)            # pdfgeo, pdfcotas, pdf2vba, stl_vba... estan en el directorio padre

PLANOS = ("Alzado", "Planta", "Lateral")
DEC = 6                                 # decimales de las coordenadas en el JSON
TOL_UNION = 1e-3                        # mm: hueco maximo admitido entre entidades consecutivas


def _r(x):
    v = round(float(x), DEC)
    return 0.0 if v == 0 else v


def _p(q):
    return [_r(q[0]), _r(q[1])]


# ------------------------------------------------------------------ entidades
def ent_de_stl(e):
    """Entidad de stl_vba (('L', p, q) / ('A', c, p, q, s) / ('C', cx, cy, r)) -> entidad de receta."""
    if e[0] == "L":
        return ["L", _p(e[1]), _p(e[2])]
    if e[0] == "A":
        return ["A", _p(e[1]), _p(e[2]), _p(e[3]), 1 if e[4] > 0 else -1]
    return ["C", [_r(e[1]), _r(e[2])], _r(e[3])]


def ent_de_prim(p):
    """Primitiva de pdf2vba (('line', x0, y0, x1, y1) / ('arc', xc, yc, x0, y0, x1, y1, s) / ('circle', cx, cy, r))."""
    if p[0] == "line":
        return ["L", _p(p[1:3]), _p(p[3:5])]
    if p[0] == "arc":
        return ["A", _p(p[1:3]), _p(p[3:5]), _p(p[5:7]), 1 if p[7] > 0 else -1]
    return ["C", [_r(p[1]), _r(p[2])], _r(p[3])]


def _ini(e):
    return e[1] if e[0] == "L" else e[2]


def _fin(e):
    return e[2] if e[0] == "L" else e[3]


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def cerrar_lazo(lazo, tol=0.05):
    """Encadena exactamente un lazo: cada entidad empieza donde acaba la anterior (huecos < tol)."""
    if len(lazo) == 1 and lazo[0][0] == "C":
        return lazo
    out = [list(e) for e in lazo]
    for i in range(len(out)):
        prev, e = out[i - 1], out[i]
        if _d(_fin(prev), _ini(e)) <= tol:
            if e[0] == "L":
                e[1] = list(_fin(prev))
            else:
                e[2] = list(_fin(prev))
    # quita lineas de longitud nula que pudieran quedar
    out = [e for e in out if not (e[0] == "L" and _d(e[1], e[2]) < 1e-6)]
    return out


def muestrear(lazo, paso=0.05):
    """Lazo de receta -> lista de puntos (u, v) para shapely."""
    pts = []
    for e in lazo:
        if e[0] == "C":
            (cx, cy), r = e[1], e[2]
            n = max(48, int(2 * math.pi / paso))
            return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]
        if e[0] == "L":
            pts.append(tuple(e[1]))
            continue
        c, p, q, s = e[1], e[2], e[3], e[4]
        r = _d(p, c)
        a0, a1 = math.atan2(p[1] - c[1], p[0] - c[0]), math.atan2(q[1] - c[1], q[0] - c[0])
        bar = (a1 - a0) % (2 * math.pi) if s > 0 else -((a0 - a1) % (2 * math.pi))
        if abs(bar) < 1e-12:
            bar = 2 * math.pi * (1 if s > 0 else -1)
        m = max(2, int(abs(bar) / paso))
        pts += [(c[0] + r * math.cos(a0 + bar * k / m), c[1] + r * math.sin(a0 + bar * k / m)) for k in range(m)]
    return pts


def poligono(perfiles):
    """Lazos de un croquis -> region de shapely (regla par-impar: los lazos interiores son agujeros)."""
    from shapely.geometry import Polygon
    res = None
    for lazo in perfiles:
        pg = Polygon(muestrear(lazo))
        if not pg.is_valid:
            pg = pg.buffer(0)
        res = pg if res is None else res.symmetric_difference(pg)
    return res if res is not None else Polygon()


# ------------------------------------------------------------------ volumen
def volumen(receta, con_redondeos=True):
    """Volumen (mm3) de la receta (redondeos aproximados en el croquis, ver _redondear_2d): por tramos a lo largo de la normal, aplicando las
    operaciones en orden (saliente = union, corte = diferencia). Todas deben ir en el mismo plano."""
    from shapely.geometry import Polygon
    ops = receta["operaciones"]
    planos = {o["plano"] for o in ops}
    if len(planos) > 1:
        raise ValueError("volumen(): operaciones en planos distintos (%s)" % ", ".join(sorted(planos)))
    geoms = [poligono(o["perfiles"]) for o in ops]
    if con_redondeos:
        geoms = [_redondear_2d(o, g, receta.get("redondeos", [])) for o, g in zip(ops, geoms)]
    zs = sorted({float(o[k]) for o in ops for k in ("desde", "hasta") if o["tipo"] == "saliente"})
    lo, hi = zs[0], zs[-1]
    marcas = sorted(set(zs + [min(max(float(o[k]), lo), hi) for o in ops for k in ("desde", "hasta")]))
    total = 0.0
    for z0, z1 in zip(marcas, marcas[1:]):
        if z1 - z0 < 1e-9:
            continue
        zm = (z0 + z1) / 2
        reg = Polygon()
        for o, g in zip(ops, geoms):
            a, b = sorted((float(o["desde"]), float(o["hasta"])))
            if o.get("pasante"):
                a, b = -math.inf, math.inf
            if not a <= zm <= b:
                continue
            reg = reg.union(g) if o["tipo"] == "saliente" else reg.difference(g)
        total += reg.area * (z1 - z0)
    return total


def de_modelo(x, y, z, plano):
    """Inversa de a_modelo: (x, y, z) del modelo -> (u, v, distancia a lo largo de la normal)."""
    if plano == "Alzado":
        return (x, y, z)
    if plano == "Planta":
        return (x, -z, y)
    if plano == "Lateral":
        return (-z, y, x)
    raise ValueError("plano desconocido: %r" % plano)


def _esquinas(perfiles):
    """[(vertice, punto anterior, punto siguiente)] de las esquinas entre dos lineas de los lazos."""
    out = []
    for lazo in perfiles:
        for k, e in enumerate(lazo):
            prev = lazo[k - 1]
            if e[0] == "L" and prev[0] == "L":
                out.append((tuple(e[1]), tuple(prev[1]), tuple(e[2])))
    return out


def _parche(v, p, n, r, paso=0.05):
    """Region entre la esquina v (lados hacia p y n) y el arco de radio r tangente a ambos lados."""
    from shapely.geometry import Polygon
    l1, l2 = _d(p, v), _d(n, v)
    if l1 < 1e-9 or l2 < 1e-9:
        return None
    d1 = ((p[0] - v[0]) / l1, (p[1] - v[1]) / l1)
    d2 = ((n[0] - v[0]) / l2, (n[1] - v[1]) / l2)
    ang = math.acos(max(-1.0, min(1.0, d1[0] * d2[0] + d1[1] * d2[1])))
    if ang < 1e-3 or ang > math.pi - 1e-3:
        return None
    t = r / math.tan(ang / 2)
    if t > 3 * min(l1, l2):
        return None                                    # no cabe ni de lejos: el redondeo fallaria tambien en el CAD
    bis = (d1[0] + d2[0], d1[1] + d2[1])
    lb = math.hypot(*bis)
    c = (v[0] + bis[0] / lb * r / math.sin(ang / 2), v[1] + bis[1] / lb * r / math.sin(ang / 2))
    t1 = (v[0] + d1[0] * t, v[1] + d1[1] * t)
    t2 = (v[0] + d2[0] * t, v[1] + d2[1] * t)
    a0 = math.atan2(t1[1] - c[1], t1[0] - c[0])
    a1 = math.atan2(t2[1] - c[1], t2[0] - c[0])
    da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi     # arco corto (el del lado de la esquina)
    m = max(4, int(abs(da) * r / paso))
    arco = [(c[0] + r * math.cos(a0 + da * k / m), c[1] + r * math.sin(a0 + da * k / m)) for k in range(m + 1)]
    pg = Polygon([v] + arco)
    return pg if pg.is_valid else pg.buffer(0)


def _redondear_2d(op, g, redondeos):
    """Aplica en el croquis de una operacion los redondeos cuyas aristas son paralelas a la normal y pasan por
    una esquina linea-linea suya: quita (esquina convexa) o anade (concava) el parche entre esquina y arco.
    Es una estimacion para comparar volumenes; los redondeos de verdad los hace el constructor."""
    a, b = sorted((float(op["desde"]), float(op["hasta"])))
    esq = _esquinas(op["perfiles"])
    elegidas = {}                                       # indice de esquina -> radio (una vez cada una)
    for rd in redondeos:
        for pt in rd["puntos"]:
            u, v, w = de_modelo(pt[0], pt[1], pt[2], op["plano"])
            if not a + 1e-6 < w < b - 1e-6:
                continue
            for k, (vert, p, n) in enumerate(esq):
                if abs(u - vert[0]) < 1e-3 and abs(v - vert[1]) < 1e-3:
                    elegidas.setdefault(k, float(rd["radio"]))
    parches = []
    for k, r in elegidas.items():
        pa = _parche(*esq[k], r)
        if pa is not None and not pa.is_empty:
            parches.append((pa, g.intersection(pa).area > 0.5 * pa.area))
    for pa, dentro in parches:
        g = g.difference(pa) if dentro else g.union(pa)
    return g


def region_en(receta, z, con_redondeos=False):
    """Seccion (shapely) de la pieza a la distancia z del plano, aplicando las operaciones en orden."""
    from shapely.geometry import Polygon
    reg = Polygon()
    for o in receta["operaciones"]:
        a, b = sorted((float(o["desde"]), float(o["hasta"])))
        if o.get("pasante"):
            a, b = -math.inf, math.inf
        if not a <= z <= b:
            continue
        g = poligono(o["perfiles"])
        if con_redondeos:
            g = _redondear_2d(o, g, receta.get("redondeos", []))
        reg = reg.union(g) if o["tipo"] == "saliente" else reg.difference(g)
    return reg


def caja(receta):
    """Caja envolvente (mm) en coordenadas del modelo, sin redondeos: [[xmin, ymin, zmin], [xmax, ymax, zmax]]."""
    ops = receta["operaciones"]
    sal = [o for o in ops if o["tipo"] == "saliente"]
    from shapely.ops import unary_union
    u0, v0, u1, v1 = unary_union([poligono(o["perfiles"]) for o in sal]).bounds
    z0 = min(min(o["desde"], o["hasta"]) for o in sal)
    z1 = max(max(o["desde"], o["hasta"]) for o in sal)
    pts = [a_modelo(u, v, z, sal[0]["plano"]) for u in (u0, u1) for v in (v0, v1) for z in (z0, z1)]
    return [[min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]]


def a_modelo(u, v, z, plano):
    """Punto del croquis (u, v) a distancia z de su plano -> (x, y, z) del modelo (convencion de RECETA.md)."""
    if plano == "Alzado":
        return (u, v, z)
    if plano == "Planta":
        return (u, z, -v)
    if plano == "Lateral":
        return (z, v, -u)
    raise ValueError("plano desconocido: %r" % plano)


# ------------------------------------------------------------------ validacion
def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _pt(x):
    return isinstance(x, list) and len(x) == 2 and all(_num(c) for c in x)


def validar(receta):
    """Lista de errores de estructura (vacia si la receta es correcta)."""
    err = []
    if not isinstance(receta, dict):
        return ["la receta no es un objeto JSON"]
    if receta.get("version") != 1:
        err.append("version debe ser 1")
    for k in ("nombre", "origen"):
        if not isinstance(receta.get(k), str) or not receta.get(k):
            err.append("falta '%s' (texto)" % k)
    var = receta.get("variables", {})
    if not isinstance(var, dict) or not all(isinstance(k, str) and k.isidentifier() and _num(v) for k, v in var.items()):
        err.append("'variables' debe ser {nombre: numero} con nombres validos")
        var = {}
    ops = receta.get("operaciones")
    if not isinstance(ops, list) or not ops:
        return err + ["'operaciones' debe ser una lista no vacia"]
    if ops[0].get("tipo") != "saliente":
        err.append("la primera operacion debe ser un saliente")
    nombres = set()
    for i, o in enumerate(ops):
        q = "operacion %d (%s)" % (i + 1, o.get("nombre", "?"))
        if o.get("tipo") not in ("saliente", "corte"):
            err.append(q + ": tipo debe ser saliente o corte")
        if not isinstance(o.get("nombre"), str) or o.get("nombre") in nombres:
            err.append(q + ": nombre ausente o repetido")
        nombres.add(o.get("nombre"))
        if o.get("plano") not in PLANOS:
            err.append(q + ": plano debe ser uno de " + ", ".join(PLANOS))
        if not (_num(o.get("desde")) and _num(o.get("hasta"))) or o["hasta"] - o["desde"] <= 1e-6:
            err.append(q + ": desde/hasta numericos con hasta > desde")
        if "pasante" in o and not isinstance(o["pasante"], bool):
            err.append(q + ": pasante debe ser true/false")
        for par, nv in (o.get("cotas") or {}).items():
            if par not in ("desde", "hasta"):
                err.append(q + ": cota de parametro desconocido '%s'" % par)
            elif nv not in var:
                err.append(q + ": la cota '%s' usa la variable '%s', que no existe" % (par, nv))
            elif abs(var[nv] - o.get(par, 0)) > 1e-6:
                err.append(q + ": %s=%s no coincide con la variable %s=%s" % (par, o.get(par), nv, var[nv]))
        perf = o.get("perfiles")
        if not isinstance(perf, list) or not perf:
            err.append(q + ": sin perfiles")
            continue
        for j, lazo in enumerate(perf):
            e = _validar_lazo(lazo)
            if e:
                err.append(q + ", lazo %d: %s" % (j + 1, e))
        if not any(q_.startswith(q) for q_ in err):
            g = poligono(perf)
            if g.is_empty or g.area <= 1e-6:
                err.append(q + ": el croquis no encierra area")
            elif not g.is_valid:
                err.append(q + ": el croquis no es una region valida")
    for i, rd in enumerate(receta.get("redondeos", [])):
        if not (_num(rd.get("radio")) and rd["radio"] > 0):
            err.append("redondeo %d: radio > 0" % (i + 1))
        pts = rd.get("puntos")
        if not isinstance(pts, list) or not pts or not all(isinstance(p, list) and len(p) == 3 and all(_num(c) for c in p) for p in pts):
            err.append("redondeo %d: puntos debe ser una lista de [x, y, z]" % (i + 1))
    return err


def _validar_lazo(lazo):
    if not isinstance(lazo, list) or not lazo:
        return "lazo vacio"
    for e in lazo:
        if not isinstance(e, list) or not e or e[0] not in ("L", "A", "C"):
            return "entidad desconocida %r" % (e,)
        if e[0] == "L" and not (len(e) == 3 and _pt(e[1]) and _pt(e[2])):
            return "linea mal formada"
        if e[0] == "A" and not (len(e) == 5 and _pt(e[1]) and _pt(e[2]) and _pt(e[3]) and e[4] in (1, -1)):
            return "arco mal formado"
        if e[0] == "C" and not (len(e) == 3 and _pt(e[1]) and _num(e[2]) and e[2] > 0):
            return "circulo mal formado"
    if any(e[0] == "C" for e in lazo):
        return "" if len(lazo) == 1 else "un circulo debe ir solo en su lazo"
    if len(lazo) < 2:
        return "lazo de una sola entidad que no es circulo"
    for k in range(len(lazo)):
        a, b = lazo[k - 1], lazo[k]
        if _d(_fin(a), _ini(b)) > TOL_UNION:
            return "abierto entre la entidad %d y la %d (%.4f mm)" % (k or len(lazo), k + 1, _d(_fin(a), _ini(b)))
        if b[0] == "A":
            r1, r2 = _d(b[2], b[1]), _d(b[3], b[1])
            if abs(r1 - r2) > max(0.01, 0.002 * r1):
                return "arco %d con radios distintos en sus extremos (%.4f / %.4f)" % (k + 1, r1, r2)
    return ""


# ------------------------------------------------------------------ escritura
def guardar(receta, ruta):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(receta, f, ensure_ascii=False, indent=1)
    return ruta


def ruta_receta(ruta_origen):
    return os.path.splitext(ruta_origen)[0] + ".receta.json"


def resumen(receta):
    ops = receta["operaciones"]
    ns = sum(o["tipo"] == "saliente" for o in ops)
    nc = len(ops) - ns
    nr = sum(len(r["puntos"]) for r in receta.get("redondeos", []))
    ent = sum(len(l) for o in ops for l in o["perfiles"])
    return "%d saliente(s) + %d corte(s) en %s, %d entidades de croquis, %d arista(s) a redondear" % (
        ns, nc, ops[0]["plano"], ent, nr)


# ------------------------------------------------------------------ constructor FreeCAD
FREECAD_BIN = r"C:\Users\xaxaj\AppData\Local\Programs\FreeCAD 1.1\bin"
FREECADCMD = os.path.join(FREECAD_BIN, "freecadcmd.exe")
FREECAD_GUI = os.path.join(FREECAD_BIN, "freecad.exe")
CONSTRUCTOR = os.path.join(AQUI, "fc_constructor.py")


def construir(ruta_receta, ruta_salida, log=print, timeout=900):
    """Lanza freecadcmd con fc_constructor.py (receta y salida en variables de entorno, sin argumentos).

    Cada linea de su salida va a log(); devuelve el dict de la linea "RESULTADO {json}"
    (ok, volumen, caja, n_operaciones, valido, errores) o {"ok": False, "errores": [...]} si no aparece.
    """
    import subprocess
    import threading
    if not os.path.isfile(FREECADCMD):
        return {"ok": False, "errores": ["no encuentro freecadcmd.exe en " + FREECAD_BIN]}
    if not os.path.isfile(CONSTRUCTOR):
        return {"ok": False, "errores": ["todavia no existe " + CONSTRUCTOR]}
    env = dict(os.environ, FC_RECETA=os.path.abspath(ruta_receta), FC_SALIDA=os.path.abspath(ruta_salida))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen([FREECADCMD, CONSTRUCTOR], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, cwd=AQUI, creationflags=flags)
    vigilante = threading.Timer(timeout, proc.kill)
    vigilante.start()
    resultado = None
    try:
        for bruto in proc.stdout:
            linea = bruto.decode("utf-8", errors="replace").rstrip()
            i = linea.find("RESULTADO {")                 # puede llegar pegada a la barra de progreso (CR)
            if i >= 0:
                try:
                    resultado = json.loads(linea[i + len("RESULTADO "):])
                except ValueError as e:
                    resultado = {"ok": False, "errores": ["RESULTADO ilegible: %s" % e]}
                continue
            linea = linea.split(chr(13))[-1].replace(chr(9), " ").strip()
            if linea and not linea.startswith(("Recompute", "(")):
                log("  [FreeCAD] " + linea)
        proc.wait()
    finally:
        vigilante.cancel()
    if resultado is None:
        resultado = {"ok": False, "errores": ["freecadcmd termino (codigo %s) sin linea RESULTADO" % proc.returncode]}
    return resultado


def texto_resultado(res):
    """Resumen de una linea del RESULTADO del constructor."""
    if not res.get("ok"):
        return "FALLO: " + "; ".join(str(e) for e in res.get("errores", [])[:5])
    c = res.get("caja") or []
    caja_txt = ""
    if len(c) == 6:
        caja_txt = ", caja %.1f x %.1f x %.1f mm" % (c[3] - c[0], c[4] - c[1], c[5] - c[2])
    extra = ""
    if res.get("errores"):
        extra = "; avisos: " + "; ".join(str(e) for e in res["errores"][:5])
    return "volumen %.1f mm3%s, %s operaciones, solido %s%s" % (
        res.get("volumen") or 0, caja_txt, res.get("n_operaciones"), "valido" if res.get("valido") else "NO valido", extra)
