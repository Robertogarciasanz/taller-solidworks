"""Plano PDF (vectorial) -> receta de pieza (ver RECETA.md).

Uso:  py receta_pdf.py plano.pdf [espesor_mm] [salida.receta.json]

Un saliente en Alzado: el contorno exterior con los agujeros como lazos interiores del mismo croquis,
extruido el espesor (parametro > cajetin > cota llamada "espesor" > 10 mm por defecto).
Lectura con los modulos de la app de SolidWorks (pdfgeo, pdfcotas, pdf2vba), sin tocarlos.
"""
import os
import sys

import receta_comun as rc          # pone el directorio padre en sys.path

import pdf2vba
import pdfcotas
import pdfgeo

ESPESOR_DEFECTO = 10.0


def analizar(ruta):
    """Lee el PDF y propone exterior, agujeros, escala y cotas, como el asistente de la app de SolidWorks.

    -> dict(cont, roles, escala, motivo, cajetin, nums)  (roles: 'exterior' / 'agujero' / 'ignorar')
    """
    g = pdfgeo.leer_geometria(ruta)
    cont = g["contornos"]
    if not cont:
        raise ValueError("no hay contornos cerrados en el PDF (¿es un escaneo o una foto?)")
    # exterior: el mayor contorno que no sea un circulo, salvo que el circulo sea mucho mayor (pieza redonda)
    mayor = cont[0]["area"]
    ie = next((i for i, c in enumerate(cont) if c["tipo"] != "circulo" and c["area"] >= 0.25 * mayor), 0)
    if ie:
        cont.insert(0, cont.pop(ie))
    ext = cont[0]
    nums = pdfgeo.textos_numericos(ruta)
    caj = pdfgeo.datos_cajetin(ruta)
    escala, motivo = pdfgeo.sugerir_escala(ext, nums, caj["escala"])
    ex0, ey0, ex1, ey1 = ext["bbox"]
    roles = []
    for i, c in enumerate(cont):
        x0, y0, x1, y1 = c["bbox"]
        dentro = x0 >= ex0 - 1 and y0 >= ey0 - 1 and x1 <= ex1 + 1 and y1 <= ey1 + 1
        peq = (x1 - x0) * escala < 1 and (y1 - y0) * escala < 1
        flecha = (c["tipo"] == "contorno" and len(c["items"]) <= 4 and all(it[0] == "l" for it in c["items"])
                  and max(x1 - x0, y1 - y0) * escala < 15)
        roles.append("exterior" if i == 0 else ("agujero" if dentro and not peq and not flecha else "ignorar"))
    return dict(cont=cont, roles=roles, escala=escala, motivo=motivo, cajetin=caj, nums=nums, geometria=g)


def cotas_con_nombre(ruta, geometria, escala, espesor_cajetin):
    try:
        cotas, _ = pdfcotas.leer_cotas(ruta, 0, geometria, escala, espesor_cajetin)
    except Exception:
        cotas = []
    return cotas


def receta_desde_contornos(nombre, origen, exterior, agujeros, escala, espesor, cotas=(), espesor_de=""):
    """Contornos de pdfgeo ya clasificados -> (receta, info).

    El origen del croquis es la esquina inferior izquierda del exterior; el eje y del PDF se invierte.
    """
    validos, malos = pdf2vba.validar(exterior, agujeros, escala)
    x0, y0, x1, y1 = exterior["bbox"]
    origen_hoja = (x0, y1)
    perfiles = [rc.cerrar_lazo([rc.ent_de_prim(p) for p in pdf2vba.primitivas([exterior], escala, origen_hoja)])]
    for c in validos:
        lazo = rc.cerrar_lazo([rc.ent_de_prim(p) for p in pdf2vba.primitivas([c], escala, origen_hoja)])
        if lazo:
            perfiles.append(lazo)
    espesor = float(espesor)
    variables = {}
    for c in cotas or ():
        n = c.get("nombre", "")
        if n in ("ancho_exterior", "alto_exterior") and n not in variables and c.get("usar", True):
            variables[n] = float(c["valor"])
    variables["espesor"] = rc._r(espesor)
    op = {"tipo": "saliente", "nombre": "Saliente-Extruir1", "plano": "Alzado", "desde": 0.0,
          "hasta": rc._r(espesor), "perfiles": perfiles, "cotas": {"hasta": "espesor"}}
    receta = {"version": 1, "nombre": nombre, "origen": origen, "variables": variables,
              "operaciones": [op], "redondeos": []}
    info = dict(ancho=(x1 - x0) * escala, alto=(y1 - y0) * escala, agujeros=len(perfiles) - 1,
                descartados=[(c, m) for c, m in malos], espesor=espesor, espesor_de=espesor_de, escala=escala)
    return receta, info


def elegir_espesor(espesor, cajetin, cotas):
    if espesor:
        return float(espesor), "indicado"
    if cajetin.get("espesor"):
        return float(cajetin["espesor"]), "cajetín"
    for c in cotas:
        if c.get("nombre", "").startswith("espesor"):
            return float(c["valor"]), "cota del plano"
    return ESPESOR_DEFECTO, "por defecto (no aparece en el plano)"


# ------------------------------------------------------------------ lectura por vistas
# pdfgeo encadena trazos por sus extremos y pierde los contornos con uniones tangentes o en T (alma del
# Brazo_engranaje, interior de caja23). Aqui se engordan los trazos visibles EPS puntos y las caras son los
# huecos que quedan entre ellos (robusto a huecos de hasta 2*EPS).
EPS = 0.25                     # puntos PDF
COLOR_VISIBLE = (0.0, 0.0, 0.0)


def _trazos_visibles(pagina):
    """Trazos continuos negros del grosor de arista visible (el mayor grosor frecuente) -> [LineString]."""
    import collections
    from shapely.geometry import LineString
    drs = [d for d in pagina.get_drawings() if d.get("type") == "s"
           and (d.get("dashes") or "").strip() in ("[] 0", "[] 0.0", "")
           and tuple(d.get("color") or ()) == COLOR_VISIBLE]
    cuenta = collections.Counter()
    for d in drs:
        cuenta[round(d.get("width") or 0, 2)] += len(d["items"])
    frecuentes = [w for w, n in cuenta.items() if n >= 50] or list(cuenta)
    if not frecuentes:
        return []
    ancho = max(frecuentes)
    out = []
    for d in drs:
        if abs(round(d.get("width") or 0, 2) - ancho) > 0.02:
            continue
        for it in d["items"]:
            if it[0] == "l":
                pts = [(it[1].x, it[1].y), (it[2].x, it[2].y)]
            elif it[0] == "c":
                P = [(p.x, p.y) for p in it[1:5]]
                pts = [pdfgeo._bezier(*P, k / 8) for k in range(9)]
            elif it[0] == "re":
                r = it[1]
                pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)]
            else:
                continue
            ls = LineString(pts)
            if ls.length > 1e-6:
                out.append(ls)
    return out


def _vistas(trazos):
    """Agrupa los trazos en vistas: grupos conexos, y los grupos dentro de la caja de otro van con el."""
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
    if not trazos:
        return []
    zona = unary_union([t.buffer(1.0) for t in trazos])
    grupos = [dict(bbox=g.bounds, g=g) for g in getattr(zona, "geoms", [zona])]
    grupos.sort(key=lambda g: -(g["bbox"][2] - g["bbox"][0]) * (g["bbox"][3] - g["bbox"][1]))
    vistas = []
    for g in grupos:
        x0, y0, x1, y1 = g["bbox"]
        madre = next((v for v in vistas if v["bbox"][0] <= x0 and v["bbox"][1] <= y0
                      and v["bbox"][2] >= x1 and v["bbox"][3] >= y1), None)
        if madre:
            madre["partes"].append(g["g"])
        else:
            vistas.append(dict(bbox=g["bbox"], partes=[g["g"]]))
    arbol = STRtree(trazos)
    for v in vistas:
        zona_v = unary_union(v["partes"])
        v["lineas"] = [trazos[i] for i in arbol.query(zona_v, predicate="intersects")]
        v["caja"] = unary_union(v["lineas"]).bounds         # caja de los trazos (sin engordar)
        del v["partes"]
    return vistas


def _cotas_cerca(vista, nums, margen=60.0):
    x0, y0, x1, y1 = vista["caja"]
    return [n for n in nums if x0 - margen <= n[1] <= x1 + margen and y0 - margen <= n[2] <= y1 + margen]


def _ajustar_a_cota(valor, nums, tol=0.015):
    """Si alguna cota escrita esta a menos del 1,5 % del valor medido, se usa la cota (medida exacta)."""
    cerca = [n[0] for n in nums if n[0] > 0 and abs(n[0] - valor) <= tol * max(valor, 1.0)]
    return min(cerca, key=lambda c: abs(c - valor)) if cerca else round(valor, 2)


def _profundidad(vistas, principal, escala, nums):
    """Profundidad (mm) y niveles intermedios a partir de una vista alineada con la principal.

    -> (profundidad, [niveles], texto) o (None, [], motivo)."""
    px0, py0, px1, py1 = principal["caja"]
    tol = 2.0
    for v in vistas:
        if v is principal:
            continue
        x0, y0, x1, y1 = v["caja"]
        if abs(y0 - py0) < tol and abs(y1 - py1) < tol:            # lateral: misma altura, la anchura es la profundidad
            t = (x1 - x0) * escala
            cerca = _cotas_cerca(v, nums)
            t = _ajustar_a_cota(t, cerca)
            niveles = set()
            alto = y1 - y0
            for ln in v["lineas"]:
                (a, b), (c, d) = ln.coords[0], ln.coords[-1]
                if abs(a - c) < 0.05 and abs(b - d) > 0.1 * alto:
                    z = (a - x0) * escala
                    if 0.3 < z < t - 0.3:
                        niveles.add(_ajustar_a_cota(z, cerca))
            return t, sorted(niveles), "vista lateral"
    for v in vistas:
        if v is principal:
            continue
        x0, y0, x1, y1 = v["caja"]
        if abs(x0 - px0) < tol and abs(x1 - px1) < tol:            # superior / inferior: la altura es la profundidad
            t = _ajustar_a_cota((y1 - y0) * escala, _cotas_cerca(v, nums))
            return t, [], "vista superior/inferior"
    return None, [], "no hay vista alineada con la principal"


def _caras(lineas):
    """Trazos de una vista -> (silueta, caras). Cada cara: dict(g, hueco, contiene) en puntos PDF.

    hueco: lazo aislado (componente de un solo lazo, dentro de otra) que no contiene nada -> agujero pasante.
    contiene: indices de los componentes que hay dentro de la cara (agujeros, cubos...)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    red = unary_union([l.buffer(EPS, quad_segs=4) for l in lineas])
    comps = list(getattr(red, "geoms", [red]))
    llenos = [Polygon(c.exterior) for c in comps]
    arriba = [i for i, f in enumerate(llenos)
              if not any(j != i and llenos[j].contains(f) for j in range(len(comps)))]
    silueta = unary_union([llenos[i] for i in arriba]).buffer(-EPS)
    caras = []
    for i, c in enumerate(comps):
        for h in c.interiors:
            f = Polygon(h)
            dentro = [j for j in range(len(comps)) if j != i and f.contains(llenos[j])]
            # solo los componentes inmediatamente dentro (no los que estan dentro de otro de ellos)
            inmediatos = [j for j in dentro if not any(k != j and llenos[k].contains(llenos[j]) for k in dentro)]
            g = f.buffer(EPS)
            if inmediatos:
                g = g.difference(unary_union([llenos[j] for j in inmediatos]).buffer(-EPS))
            aislado = len(c.interiors) == 1 and i not in arriba
            caras.append(dict(g=g, comp=i, hueco=aislado and not dentro, contiene=inmediatos,
                              area_comp=llenos[i].area))
    return silueta, caras, llenos


def _a_mm(g, x0, y1, escala):
    """Geometria en puntos PDF (y hacia abajo) -> mm con origen en (x0, y1) e y hacia arriba."""
    from shapely import affinity
    g = affinity.affine_transform(g, [escala, 0, 0, -escala, -x0 * escala, y1 * escala])
    return g.simplify(0.01)


def receta_por_vistas(ruta, espesor=None):
    """Plano PDF -> (receta, info) leyendo las vistas: silueta del alzado + agujeros pasantes, profundidad de la
    vista lateral; con escalones (lateral con niveles) o vaciado (componente interior grande) como corte.
    Devuelve None si el plano no tiene vistas legibles."""
    import receta_stl
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    pg = pdfgeo.fitz.open(ruta)[0]
    trazos = _trazos_visibles(pg)
    vistas = _vistas(trazos)
    if not vistas:
        return None
    H = pg.rect.height
    nums = [n for n in pdfgeo.textos_numericos(ruta) if 40 < n[2] < H - 40]   # sin las letras/numeros del marco
    def alineada(v):                              # la isometrica no tiene ninguna vista alineada con ella
        x0, y0, x1, y1 = v["caja"]
        return any(w is not v and ((abs(w["caja"][1] - y0) < 2 and abs(w["caja"][3] - y1) < 2)
                                   or (abs(w["caja"][0] - x0) < 2 and abs(w["caja"][2] - x1) < 2)) for w in vistas)
    principal = max(vistas, key=lambda v: (len(_cotas_cerca(v, nums)), alineada(v),
                                           (v["caja"][2] - v["caja"][0]) * (v["caja"][3] - v["caja"][1])))
    caj = pdfgeo.datos_cajetin(ruta)
    x0, y0, x1, y1 = principal["caja"]
    escala, motivo = pdfgeo.sugerir_escala({"bbox": principal["caja"]}, nums, caj["escala"])
    silueta, caras, llenos = _caras(principal["lineas"])
    if silueta.is_empty or silueta.area < 1:
        return None
    cerca = _cotas_cerca(principal, nums)
    t, niveles, de = _profundidad(vistas, principal, escala, nums)
    if espesor:
        t, de = float(espesor), "indicado"
    elif not t:
        cotas = cotas_con_nombre(ruta, pdfgeo.leer_geometria(ruta), escala, caj.get("espesor"))
        t, de = elegir_espesor(None, caj, cotas)
    huecos = [c for c in caras if c["hueco"]]
    materia = [c for c in caras if not c["hueco"]]
    # vaciado: un componente interior (no un lazo simple) que ocupa buena parte de la silueta (caja)
    vaciado = None
    for c in caras:
        for j in c["contiene"]:
            comp_lazos = [k for k in caras if k["comp"] == j]
            if len(comp_lazos) > 1 and llenos[j].area > 0.3 * silueta.area:
                vaciado = llenos[j].buffer(-EPS)
    nota = []
    perf_base = silueta
    agujeros = [c["g"] for c in huecos if vaciado is None or not vaciado.contains(c["g"])]
    if agujeros:
        perf_base = silueta.difference(unary_union(agujeros))
    sil_mm = _a_mm(silueta, x0, y1, escala)
    ops, esquinas = [], []
    perf, esq = receta_stl.croquis_ents(_a_mm(perf_base, x0, y1, escala))
    variables = {"espesor": rc._r(round(t, 2))}
    ops.append({"tipo": "saliente", "nombre": "Saliente-Extruir1", "plano": "Alzado", "desde": 0.0,
                "hasta": rc._r(round(t, 2)), "perfiles": perf, "cotas": {"hasta": "espesor"}})
    esquinas += [(u, v, 0.0, t, r) for (u, v), r in esq]
    if vaciado is not None:
        g = _a_mm(vaciado, x0, y1, escala)
        pared = round(g.exterior.distance(sil_mm.exterior) if g.geom_type == "Polygon" else 3.0, 2)
        fondo = max(pared, 1.0)
        variables["fondo"] = rc._r(fondo)
        perf, esq = receta_stl.croquis_ents(g)
        ops.append({"tipo": "corte", "nombre": "Cortar-Extruir1", "plano": "Alzado", "desde": rc._r(fondo),
                    "hasta": rc._r(round(t + 1, 2)), "pasante": False, "perfiles": perf, "cotas": {"desde": "fondo"}})
        esquinas += [(u, v, fondo, t, r) for (u, v), r in esq]
        nota.append("vaciado de %.2f mm de fondo (supuesto igual a la pared, %.2f mm); los detalles interiores "
                    "(tabiques, alojamientos) no tienen profundidad en el plano y no se modelan" % (fondo, pared))
    elif niveles:
        nivel = niveles[0]
        # cubos: caras que rodean un agujero; el resto de la materia (alma) baja al nivel intermedio
        ids_hueco = {c["comp"] for c in huecos}
        cubos = [c for c in materia if any(j in ids_hueco for j in c["contiene"])]
        alma = [c for c in materia if c not in cubos and silueta.buffer(-EPS).intersects(c["g"])]
        if cubos and alma:
            ga = unary_union([c["g"] for c in alma])
            llenos_cubos = unary_union([Polygon(c["g"].exterior) for c in cubos])
            corte = ga.buffer(1.0 / escala, join_style="mitre").difference(llenos_cubos)
            corte = corte.difference(unary_union(agujeros).buffer(EPS)) if agujeros else corte
            g = _a_mm(corte, x0, y1, escala)
            variables["espesor_alma"] = rc._r(nivel)
            perf, esq = receta_stl.croquis_ents(g)
            ops.append({"tipo": "corte", "nombre": "Cortar-Extruir1", "plano": "Alzado", "desde": rc._r(nivel),
                        "hasta": rc._r(round(t + 1, 2)), "pasante": False, "perfiles": perf,
                        "cotas": {"desde": "espesor_alma"}})
            esquinas += [(u, v, nivel, t, r) for (u, v), r in esq]
            nota.append("alma rebajada a %.2f mm (nivel de la vista lateral); cubos y lobulos a %.2f mm" % (nivel, t))
    for o in ops:                                 # el trazado del PDF deja huecos de milesimas entre entidades
        o["perfiles"] = [rc.cerrar_lazo(l, tol=0.05) for l in o["perfiles"]]
    redondeos = receta_stl.redondeos_finales(ops, esquinas, 2, 0.0, t)
    nombre = os.path.splitext(os.path.basename(ruta))[0]
    receta = {"version": 1, "nombre": nombre, "origen": "PDF " + os.path.basename(ruta), "variables": variables,
              "operaciones": ops, "redondeos": redondeos}
    bx = sil_mm.bounds
    info = dict(ancho=bx[2] - bx[0], alto=bx[3] - bx[1], agujeros=len(agujeros), descartados=[],
                espesor=t, espesor_de=de, escala=escala, motivo_escala=motivo, metodo="vistas",
                n_vistas=len(vistas), niveles=niveles, notas=nota, cotas=[])
    return receta, info


def receta_desde_pdf(ruta, espesor=None):
    """Archivo PDF -> (receta, info): primero por vistas; si no se puede, con los contornos de pdfgeo."""
    try:
        r = receta_por_vistas(ruta, espesor)
    except Exception as e:                       # plano raro: se usa el metodo de contornos
        r = None
        motivo_fallo = "lectura por vistas fallida: %s" % e
    else:
        motivo_fallo = "sin vistas legibles"
    if r is not None and not rc.validar(r[0]):
        return r
    receta, info = receta_por_contornos(ruta, espesor)
    info.setdefault("notas", []).append(motivo_fallo)
    info["metodo"] = "contornos"
    return receta, info


def receta_por_contornos(ruta, espesor=None):
    """Archivo PDF -> (receta, info), con la clasificacion automatica de contornos de pdfgeo."""
    a = analizar(ruta)
    cont, roles, esc = a["cont"], a["roles"], a["escala"]
    cotas = cotas_con_nombre(ruta, a["geometria"], esc, a["cajetin"].get("espesor"))
    esp, de = elegir_espesor(espesor, a["cajetin"], cotas)
    ext = cont[roles.index("exterior")]
    ag = [c for c, r in zip(cont, roles) if r == "agujero"]
    nombre = os.path.splitext(os.path.basename(ruta))[0]
    receta, info = receta_desde_contornos(nombre, "PDF " + os.path.basename(ruta), ext, ag, esc, esp, cotas, de)
    info.update(motivo_escala=a["motivo"], n_contornos=len(cont), cotas=cotas)
    return receta, info


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    ruta = argv[1]
    esp = float(argv[2].replace(",", ".")) if len(argv) > 2 and argv[2].strip() else None
    destino = argv[3] if len(argv) > 3 else rc.ruta_receta(ruta)
    receta, info = receta_desde_pdf(ruta, esp)
    errores = rc.validar(receta)
    rc.guardar(receta, destino)
    print("%s: exterior %.2f x %.2f mm, %d agujero(s), espesor %g mm (%s); escala %.4f mm/pt (%s)"
          % (os.path.basename(ruta), info["ancho"], info["alto"], info["agujeros"], info["espesor"],
             info["espesor_de"], info["escala"], info["motivo_escala"]))
    print("  variables: %s" % receta["variables"])
    print("  volumen %.1f mm3; receta: %s" % (rc.volumen(receta), destino))
    for c, m in info["descartados"][:8]:
        print("  descartado: %s (%s)" % (c["tipo"], m))
    for e in errores:
        print("  ERROR: " + e)
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
