"""Paso 2: del contorno leido en el PDF al codigo VBA que SolidWorks entiende (croquis + extrusion)."""
import math

import pdfgeo


def _rdp(pts, eps):
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    mejor, idx = -1, 0
    for i in range(1, len(pts) - 1):
        d = (abs(dy * pts[i][0] - dx * pts[i][1] + x1 * y0 - y1 * x0) / L) if L > 1e-9 else math.hypot(pts[i][0] - x0, pts[i][1] - y0)
        if d > mejor:
            mejor, idx = d, i
    if mejor > eps:
        return _rdp(pts[:idx + 1], eps)[:-1] + _rdp(pts[idx:], eps)
    return [pts[0], pts[-1]]


def primitivas(contornos, escala, origen, eps_mm=0.05):
    """contornos: lista de dicts de pdfgeo. -> lista de ('circle',...), ('line',...), ('arc',...) en mm.
    origen = (x, y) de la hoja que pasa a (0, 0); el eje y se invierte (en la hoja crece hacia abajo)."""
    ox, oy = origen

    def T(p):
        return ((p[0] - ox) * escala, (oy - p[1]) * escala)

    prims = []
    for c in contornos:
        if c["tipo"] == "circulo":
            x, y = T((c["cx"], c["cy"]))
            prims.append(("circle", x, y, c["r"] * escala))
            continue
        # contorno: agrupa lineas consecutivas para simplificar los splines exportados como mil segmentos
        items = c["items"]
        i = 0
        while i < len(items):
            it = items[i]
            if it[0] == "l":
                j = i
                pts = [T(it[1])]
                while j < len(items) and items[j][0] == "l":
                    pts.append(T(items[j][2]))
                    j += 1
                for a, b in zip(_rdp(pts, eps_mm), _rdp(pts, eps_mm)[1:]):
                    if math.hypot(a[0] - b[0], a[1] - b[1]) > 1e-4:
                        prims.append(("line", a[0], a[1], b[0], b[1]))
                i = j
            else:
                a, m, b = T(it[1]), T(it[2]), T(it[3])
                cc = pdfgeo._circ3(a, m, b)
                if cc is None or cc[2] > 1e5:
                    prims.append(("line", a[0], a[1], b[0], b[1]))
                else:
                    xc, yc, r = cc
                    ang = lambda p: math.atan2(p[1] - yc, p[0] - xc)
                    a0, am, a1 = ang(a), ang(m), ang(b)
                    ccw = ((am - a0) % (2 * math.pi)) < ((a1 - a0) % (2 * math.pi))
                    prims.append(("arc", xc, yc, a[0], a[1], b[0], b[1], 1 if ccw else -1))
                i += 1
    return prims


def vba(prims_exterior, prims_agujeros, espesor_mm, nombre="Pieza_desde_PDF", cotas=None, notas=""):
    """Texto de una macro VBA que crea la pieza: croquis en Alzado y extrusion del espesor."""
    f = lambda v: f"{v / 1000:.6f}".rstrip("0").rstrip(".") if abs(v) > 1e-9 else "0"
    L = []
    L.append("' " + "=" * 68)
    L.append(f"' {nombre}: macro generada desde un plano PDF (Taller SolidWorks)")
    L.append("' Contorno exterior + agujeros en el plano Alzado, extruidos " + f"{espesor_mm:g} mm.")
    L.append("' REVISA las medidas antes de fiarte: salen de medir el dibujo del PDF.")
    for n in notas.splitlines():
        L.append("' " + n)
    L.append("' " + "=" * 68)
    L.append("Option Explicit")
    L.append("")
    L.append("Dim swApp As SldWorks.SldWorks")
    L.append("Dim Part As SldWorks.ModelDoc2")
    L.append("Dim skM As SldWorks.SketchManager")
    L.append("")
    if cotas:
        L.append("' Cotas leidas del texto del plano (mm -> m)")
        for c in cotas:
            L.append(f"Const {c['nombre']} As Double = {c['valor'] / 1000:g}   ' {c['valor']:g} mm")
        L.append("")
    L.append(f"Const ESPESOR As Double = {espesor_mm / 1000:g}   ' {espesor_mm:g} mm")
    L.append("")
    L.append("Sub main()")
    L.append("    Set swApp = Application.SldWorks")
    L.append("    Set Part = swApp.NewDocument(swApp.GetUserPreferenceStringValue(8), 0, 0, 0)")
    L.append("    If Part Is Nothing Then MsgBox \"No se pudo crear la pieza.\": Exit Sub")
    L.append("    Set skM = Part.SketchManager")
    L.append("")
    L.append("    ' Primer plano de referencia = Alzado")
    L.append("    Dim feat As SldWorks.Feature")
    L.append("    Set feat = Part.FirstFeature")
    L.append("    Do While Not feat Is Nothing")
    L.append("        If feat.GetTypeName2 = \"RefPlane\" Then Exit Do")
    L.append("        Set feat = feat.GetNextFeature")
    L.append("    Loop")
    L.append("    feat.Select2 False, 0")
    L.append("    skM.InsertSketch True")
    L.append("    skM.AddToDB = True             ' sin auto-ajustes del croquis: los puntos quedan exactos")
    L.append("")

    def dibuja(prims, titulo):
        L.append(f"    ' --- {titulo} ---")
        for p in prims:
            if p[0] == "circle":
                L.append(f"    skM.CreateCircleByRadius {f(p[1])}, {f(p[2])}, 0, {f(p[3])}")
            elif p[0] == "line":
                L.append(f"    skM.CreateLine {f(p[1])}, {f(p[2])}, 0, {f(p[3])}, {f(p[4])}, 0")
            else:
                L.append(f"    skM.CreateArc {f(p[1])}, {f(p[2])}, 0, {f(p[3])}, {f(p[4])}, 0, {f(p[5])}, {f(p[6])}, 0, {p[7]}")
        L.append("")

    dibuja(prims_exterior, "contorno exterior")
    if prims_agujeros:
        dibuja(prims_agujeros, "agujeros y ventanas")
    L.append("    skM.AddToDB = False")
    L.append("    skM.InsertSketch True          ' cierra el croquis")
    L.append("    Part.ClearSelection2 True")
    L.append("    Dim croquis As SldWorks.Feature")
    L.append("    Set croquis = Part.FeatureByPositionReverse(0)   ' el croquis recien cerrado")
    L.append("    croquis.Select2 False, 0")
    L.append("")
    L.append("    Dim op As Object")
    L.append("    Set op = Part.FeatureManager.FeatureExtrusion3(True, False, False, 0, 0, ESPESOR, 0, False, False, " +
             "False, False, 0, 0, False, False, False, False, True, True, True, 0, 0, False)")
    L.append("    If op Is Nothing Then")
    L.append("        MsgBox \"La extrusion ha fallado: revisa que el contorno este cerrado.\", vbExclamation, \"" + nombre + "\"")
    L.append("    Else")
    L.append("        Part.ViewZoomtofit2")
    L.append("    End If")
    L.append("End Sub")
    return "\r\n".join(L) + "\r\n"


def crear_en_solidworks(prims_exterior, prims_agujeros, espesor_mm):
    """Lo mismo que hace la macro, pero directo por COM (sirve para probar el resultado sin pegar codigo)."""
    import pythoncom
    import win32com.client.dynamic as dyn
    sw = dyn.Dispatch("SldWorks.Application")
    part = sw.NewDocument(sw.GetUserPreferenceStringValue(8), 0, 0, 0)
    sk = part.SketchManager
    feat = part.FirstFeature
    while feat is not None and feat.GetTypeName2 != "RefPlane":
        feat = feat.GetNextFeature
    feat.Select2(False, 0)
    sk.InsertSketch(True)
    sk.AddToDB = True
    m = 0.001
    n = 0
    for p in list(prims_exterior) + list(prims_agujeros):
        if p[0] == "circle":
            r = sk.CreateCircleByRadius(p[1] * m, p[2] * m, 0, p[3] * m)
        elif p[0] == "line":
            r = sk.CreateLine(p[1] * m, p[2] * m, 0, p[3] * m, p[4] * m, 0)
        else:
            r = sk.CreateArc(p[1] * m, p[2] * m, 0, p[3] * m, p[4] * m, 0, p[5] * m, p[6] * m, 0, p[7])
        n += r is not None
    sk.AddToDB = False
    sk.InsertSketch(True)
    part.ClearSelection2(True)
    part.FeatureByPositionReverse(0).Select2(False, 0)
    op = part.FeatureManager.FeatureExtrusion3(True, False, False, 0, 0, espesor_mm * m, 0, False, False, False, False,
                                               0, 0, False, False, False, False, True, True, True, 0, 0, False)
    part.ViewZoomtofit2()
    return part, n, op is not None


# ---------------------------------------------------------------- validacion geometrica
def _poligono(c, n_arco=10):
    """Poligono (shapely) de un contorno de pdfgeo, en puntos de la hoja."""
    from shapely.geometry import Point, Polygon
    if c["tipo"] == "circulo":
        return Point(c["cx"], c["cy"]).buffer(c["r"], 48)
    pts = []
    for it in c["items"]:
        if it[0] == "l":
            pts.append(it[1])
        else:
            a, m, b = it[1], it[2], it[3]
            cc = pdfgeo._circ3(a, m, b)
            if cc is None:
                pts += [a, m]
                continue
            xc, yc, r = cc
            a0, am, a1 = (math.atan2(p[1] - yc, p[0] - xc) for p in (a, m, b))
            ccw = ((am - a0) % (2 * math.pi)) < ((a1 - a0) % (2 * math.pi))
            barrido = ((a1 - a0) % (2 * math.pi)) if ccw else -((a0 - a1) % (2 * math.pi))
            for k in range(n_arco):
                t = a0 + barrido * k / n_arco
                pts.append((xc + r * math.cos(t), yc + r * math.sin(t)))
    poly = Polygon(pts)
    return poly if poly.is_valid else poly.buffer(0)


def validar(exterior, candidatos, escala, min_mm=1.2):
    """Devuelve (agujeros_validos, descartados[(contorno, motivo)]).
    Un agujero vale si esta dentro del exterior, no es diminuto (letras, simbolos), no esta repetido
    y no se cruza con otro agujero ni con el borde (SolidWorks no extruye croquis que se solapan)."""
    ext = _poligono(exterior)
    validos, malos, polis = [], [], []
    for c in sorted(candidatos, key=lambda c: -c["area"]):
        x0, y0, x1, y1 = c["bbox"]
        if min(x1 - x0, y1 - y0) * escala < min_mm:
            malos.append((c, f"muy pequeño ({(x1 - x0) * escala:.1f} × {(y1 - y0) * escala:.1f} mm): flecha, letra o símbolo"))
            continue
        p = _poligono(c)
        if p.is_empty or p.area <= 0:
            malos.append((c, "contorno vacío"))
            continue
        if not ext.buffer(0.2).contains(p):
            malos.append((c, "sale del contorno exterior o toca su borde"))
            continue
        if any(p.intersects(q) or q.contains(p) or p.contains(q) for q in polis):
            malos.append((c, "se solapa con otro agujero"))
            continue
        validos.append(c)
        polis.append(p)
    return validos, malos
