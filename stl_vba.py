"""Segunda parte de STL -> macro: arcos y escritura del VBA / .swp (usa stl_a_macro)."""
import math
import os
import sys

import tareas
import swp_escribir
from stl_a_macro import (capas, circulo, reconstruido, volumen)

USAR_ARCOS = False   # los arcos exigen mas de 2 decimales; con lineas el contorno siempre cierra
TAM_TROZO = 250     # entidades por Sub (VBA limita el tamano de cada procedimiento)


# ------------------------------------------------------------------ arcos
def _circ3(a, b, c):
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-9:
        return None
    ux = ((a[0] ** 2 + a[1] ** 2) * (b[1] - c[1]) + (b[0] ** 2 + b[1] ** 2) * (c[1] - a[1]) + (c[0] ** 2 + c[1] ** 2) * (a[1] - b[1])) / d
    uy = ((a[0] ** 2 + a[1] ** 2) * (c[0] - b[0]) + (b[0] ** 2 + b[1] ** 2) * (a[0] - c[0]) + (c[0] ** 2 + c[1] ** 2) * (b[0] - a[0])) / d
    return ux, uy, math.hypot(a[0] - ux, a[1] - uy)


def _giro(a, b, c):
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])


def _angulo(a, b, c):
    """Angulo de giro (rad) en el vertice b."""
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    return abs(math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1]))


def _limpiar(l):
    """Quita duplicados y puntos alineados de verdad (los de los arcos se conservan)."""
    p = [l[0]]
    for q in l[1:]:
        if math.hypot(q[0] - p[-1][0], q[1] - p[-1][1]) > 0.005:
            p.append(q)
    if len(p) > 1 and math.hypot(p[0][0] - p[-1][0], p[0][1] - p[-1][1]) <= 0.005:
        p.pop()
    cambio = True
    while cambio and len(p) > 3:
        cambio = False
        for i in range(len(p)):
            a, b, c = p[i - 1], p[i], p[(i + 1) % len(p)]
            if abs(_giro(a, b, c)) < 1e-4 * max(1.0, math.hypot(c[0] - a[0], c[1] - a[1])):
                p.pop(i)
                cambio = True
                break
    return p


def _encadenar(ents):
    """Hace que cada entidad empiece exactamente donde acaba la anterior.

    Un arco de SolidWorks toma el radio del punto de inicio y solo el angulo del final:
    si los radios difieren unas centesimas, el contorno queda abierto.
    """
    n = len(ents)
    for r in range(n):                                   # que la ultima sea una linea
        if ents[-1][0] == "L":
            break
        ents = ents[1:] + ents[:1]
    res = []
    cur = ents[0][1] if ents[0][0] == "L" else ents[0][2]
    ini = cur
    for j, e in enumerate(ents):
        if e[0] == "L":
            fin = ini if j == n - 1 else e[2]
            res.append(("L", cur, fin))
        else:
            c = e[1]
            r = math.hypot(cur[0] - c[0], cur[1] - c[1])
            d = math.hypot(e[3][0] - c[0], e[3][1] - c[1]) or 1.0
            fin = (c[0] + r * (e[3][0] - c[0]) / d, c[1] + r * (e[3][1] - c[1]) / d)
            res.append(("A", c, cur, fin, e[4]))
        cur = fin
    return res


def _dp(p, tol):
    """Douglas-Peucker sobre un camino abierto."""
    if len(p) < 3:
        return p
    a, b = p[0], p[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    nn = math.hypot(dx, dy)
    mx, im = -1.0, 0
    for i in range(1, len(p) - 1):
        d = (abs(dy * (p[i][0] - a[0]) - dx * (p[i][1] - a[1])) / nn) if nn else math.hypot(p[i][0] - a[0], p[i][1] - a[1])
        if d > mx:
            mx, im = d, i
    if mx <= tol:
        return [a, b]
    return _dp(p[:im + 1], tol)[:-1] + _dp(p[im:], tol)


def entidades_lineas(l, tol=0.02):
    """Contorno -> circulo o lista de lineas con coordenadas a 2 decimales."""
    c = circulo(l)
    if c:
        return [("C", round(c[0], 2), round(c[1], 2), round(c[2], 2))]
    p = [(round(x, 2), round(y, 2)) for x, y in l]
    q = [p[0]]
    for x in p[1:]:
        if x != q[-1]:
            q.append(x)
    if q[0] == q[-1]:
        q.pop()
    n = len(q)
    j = max(range(n), key=lambda i: math.hypot(q[i][0] - q[0][0], q[i][1] - q[0][1]))
    anillo = _dp(q[:j + 1], tol)[:-1] + _dp(q[j:] + [q[0]], tol)[:-1]
    anillo = _limpiar_exacto(anillo)
    return [("L", anillo[i], anillo[(i + 1) % len(anillo)]) for i in range(len(anillo))]


def _limpiar_exacto(p):
    cambio = True
    while cambio and len(p) > 3:
        cambio = False
        for i in range(len(p)):
            a, b, c = p[i - 1], p[i], p[(i + 1) % len(p)]
            if abs(_giro(a, b, c)) < 1e-9 or a == b:
                p.pop(i)
                cambio = True
                break
    return p


def entidades(l):
    """Contorno -> ('C', cx, cy, r) o lista de ('L', p, q) y ('A', centro, p, q, sentido)."""
    c = circulo(l)
    if c:
        return [("C",) + c]
    p = _limpiar(l)
    n = len(p)
    ang = []
    for i in range(n):
        a, b, d = p[i - 1], p[i], p[(i + 1) % n]
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (d[0] - b[0], d[1] - b[1])
        ang.append(abs(math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1])))
    i0 = max(range(n), key=lambda i: ang[i])         # empezar en la esquina mas marcada
    p = p[i0:] + p[:i0]
    p.append(p[0])
    ents = []
    i = 0
    while i < n:
        cc = _circ3(p[i], p[i + 1], p[i + 2]) if i + 2 <= n else None
        k = i + 3
        if cc and cc[2] < 5000:
            tol = 0.004 + 0.002 * cc[2]
            sg = _giro(p[i], p[i + 1], p[i + 2])
            l0 = math.hypot(p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1])
            a0 = _angulo(p[i], p[i + 1], p[i + 2])
            if a0 > 0.8 or a0 < 0.005:
                cc = None
            while cc and k <= n:
                if abs(math.hypot(p[k][0] - cc[0], p[k][1] - cc[1]) - cc[2]) > tol:
                    break
                if _giro(p[k - 2], p[k - 1], p[k]) * sg <= 0:
                    break
                ak = _angulo(p[k - 2], p[k - 1], p[k])
                if ak > 1.6 * a0 or ak < 0.5 * a0:
                    break
                lk = math.hypot(p[k][0] - p[k - 1][0], p[k][1] - p[k - 1][1])
                if lk > 1.6 * l0 or lk < 0.4 * l0:
                    break
                k += 1
            if k - i >= 4:                            # al menos 3 tramos
                ents.append(("A", (cc[0], cc[1]), p[i], p[k - 1], 1 if sg > 0 else -1))
                i = k - 1
                continue
        ents.append(("L", p[i], p[i + 1]))
        i += 1
    return _encadenar(ents)


# ------------------------------------------------------------------ VBA
def _f(x):
    s = ("%.2f" % x).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _linea_vba(e):
    if e[0] == "C":
        return "    C %s, %s, %s" % (_f(e[1]), _f(e[2]), _f(e[3]))
    if e[0] == "L":
        return "    L %s, %s, %s, %s" % (_f(e[1][0]), _f(e[1][1]), _f(e[2][0]), _f(e[2][1]))
    return "    A %s, %s, %s, %s, %s, %s, %d" % (_f(e[1][0]), _f(e[1][1]), _f(e[2][0]), _f(e[2][1]), _f(e[3][0]), _f(e[3][1]), e[4])


CABECERA = '''Option Explicit
Dim swApp As Object
Dim Part As Object
Const Q As Double = 0.001

Sub L(x1 As Double, y1 As Double, x2 As Double, y2 As Double)
    Dim s As Object
    Set s = Part.SketchManager.CreateLine(x1 * Q, y1 * Q, 0#, x2 * Q, y2 * Q, 0#)
End Sub

Sub A(cx As Double, cy As Double, x1 As Double, y1 As Double, x2 As Double, y2 As Double, d As Long)
    Dim s As Object
    Set s = Part.SketchManager.CreateArc(cx * Q, cy * Q, 0#, x1 * Q, y1 * Q, 0#, x2 * Q, y2 * Q, 0#, d)
End Sub

Sub C(cx As Double, cy As Double, r As Double)
    Dim s As Object
    Set s = Part.SketchManager.CreateCircleByRadius(cx * Q, cy * Q, 0#, r * Q)
End Sub

Sub Croquis(plano As Long)
    Dim f As Object, n As Long
    Set f = Part.FirstFeature
    Do While Not f Is Nothing
        If f.GetTypeName2 = "RefPlane" Then
            n = n + 1
            If n = plano Then
                f.Select2 False, 0
                Exit Do
            End If
        End If
        Set f = f.GetNextFeature
    Loop
    Part.SketchManager.InsertSketch True
    Part.SetAddToDB True
    Part.SetDisplayWhenAdded False
End Sub

Sub Extruir(nombre As String, z0 As Double, z1 As Double)
    Dim sk As Object, ft As Object, t0 As Long
    Part.SetAddToDB False
    Part.SetDisplayWhenAdded True
    Part.SketchManager.InsertSketch True
    Set sk = Part.FeatureByPositionReverse(0)
    Part.ClearSelection2 True
    sk.Select2 False, 0
    If z0 > 0.0001 Or z0 < -0.0001 Then t0 = 3 Else t0 = 0
    Set ft = Part.FeatureManager.FeatureExtrusion2(True, False, False, 0, 0, (z1 - z0) * Q, 0#, False, False, False, False, 0#, 0#, False, False, False, False, True, True, True, t0, z0 * Q, False)
    If ft Is Nothing Then
        MsgBox "Fallo la capa " & nombre & ". Se detiene la macro.", vbExclamation, "STL a macro"
        End
    Else
        ft.Name = nombre
    End If
End Sub
'''


def elegir_eje(tri):
    """Eje con menos capas entre los que reconstruyen bien el volumen (error < 1 %)."""
    v = volumen(tri)
    cand = []
    for e in (2, 1, 0):
        cp = capas(tri, e)
        err = abs(reconstruido(cp) - v) / v
        cand.append((err, e, cp))
    buenos = [c for c in cand if c[0] < 0.01] or [min(cand)]
    err, e, cp = min(buenos, key=lambda c: (len(c[2]), c[0]))
    return e, cp, err, 0


def regiones(lazos):
    """Union par-impar de los contornos de una capa -> [(exterior, [huecos])].

    Los bloques que tocan una pared se funden en una sola region: asi cada croquis
    tiene contornos que no se tocan y SolidWorks puede extruirlo.
    """
    from shapely.geometry import Polygon
    res = None
    for l in lazos:
        pts = [(round(x, 2), round(y, 2)) for x, y in l]
        pg = Polygon(pts)
        if not pg.is_valid:
            pg = pg.buffer(0)
        if pg.is_empty:
            continue
        res = pg if res is None else res.symmetric_difference(pg)
    if res is None or res.is_empty:
        return []
    geoms = list(res.geoms) if hasattr(res, "geoms") else [res]
    out = []
    for g in geoms:
        if g.geom_type != "Polygon" or g.area < 0.01:
            continue
        out.append((list(g.exterior.coords)[:-1], [list(h.coords)[:-1] for h in g.interiors]))
    return out


def generar_vba(tri, nombre, aviso=True):
    eje, cp, err, _ = elegir_eje(tri)
    vol = volumen(tri)
    plano = {2: 1, 1: 2, 0: 3}[eje]
    out = ["' Macro generada por Taller SolidWorks a partir de %s" % nombre.replace('"', ""),
           "' Reconstruccion por capas (eje %s): %d capas, error de volumen estimado %.2f%%." % ("XYZ"[eje], len(cp), err * 100),
           "Const AVISO As Boolean = %s" % ("True" if aviso else "False"),
           "Const VOL_STL As Double = %s   ' mm3" % _f(vol)]
    out += CABECERA.split("\n")
    llamadas = []
    nent = 0
    for i, (z0, z1, lz) in enumerate(cp, 1):
        for r, (ext, huecos) in enumerate(regiones(lz), 1):
            lineas = []
            for anillo in [ext] + huecos:
                lineas += [_linea_vba(e) for e in (entidades(anillo) if USAR_ARCOS else entidades_lineas(anillo))]
            nent += len(lineas)
            trozos = [lineas[k:k + TAM_TROZO] for k in range(0, len(lineas), TAM_TROZO)] or [[]]
            for j, tz in enumerate(trozos):
                out.append("Sub Capa%02d_%d_%d()" % (i, r, j + 1))
                out += tz or ["    ' (vacia)"]
                out += ["End Sub", ""]
            llamadas.append((i, r, z0, z1, len(trozos)))
    out += ["Sub main()",
            "    Set swApp = Application.SldWorks",
            "    swApp.NewDocument swApp.GetUserPreferenceStringValue(8), 0, 0, 0",
            "    Set Part = swApp.ActiveDoc",
            "    If Part Is Nothing Then",
            '        MsgBox "No se pudo crear la pieza nueva.", vbExclamation, "STL a macro"',
            "        Exit Sub",
            "    End If"]
    for i, r, z0, z1, nt in llamadas:
        out.append("    Croquis %d" % plano)
        out += ["    Capa%02d_%d_%d" % (i, r, j + 1) for j in range(nt)]
        out.append('    Extruir "Capa_%02d_%d", %s, %s' % (i, r, _f(z0), _f(z1)))
    out += ["    Part.ViewZoomtofit2",
            "    Dim vol As Double, nb As Long, cuerpos As Variant",
            "    vol = Part.Extension.CreateMassProperty.Volume * 1000000000#",
            "    cuerpos = Part.GetBodies2(0, False)",
            "    If Not IsEmpty(cuerpos) Then nb = UBound(cuerpos) + 1",
            "    If AVISO Then",
            '        MsgBox "Pieza reconstruida: " & nb & " solido(s), volumen " & Format(vol, "0.0") & " mm3 (STL: " & Format(VOL_STL, "0.0") & " mm3).", vbInformation, "STL a macro"',
            "    End If",
            "End Sub"]
    return "\r\n".join(out), dict(eje="XYZ"[eje], capas=len(cp), error=err, entidades=nent, volumen=vol)


def stl_a_swp(ruta_stl, destino=None, aviso=True):
    tri = tareas._leer_stl(ruta_stl)
    nombre = os.path.basename(ruta_stl)
    cod, info = generar_vba(tri, nombre, aviso)
    destino = destino or os.path.join(os.path.dirname(ruta_stl), os.path.splitext(nombre)[0] + "_macro.swp")
    swp_escribir.escribir_swp(cod, destino)
    open(os.path.splitext(destino)[0] + ".bas", "w", encoding="cp1252", newline="").write(cod)
    print(f"{nombre}: eje {info['eje']}, {info['capas']} capas, {info['entidades']} entidades, error de volumen {info['error'] * 100:.2f}%")
    print(f"  macro: {destino}  ({len(cod.splitlines())} lineas)")
    return destino, info


if __name__ == "__main__":
    stl_a_swp(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None, aviso=("--sin-aviso" not in sys.argv))
