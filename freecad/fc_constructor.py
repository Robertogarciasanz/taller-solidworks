# -*- coding: utf-8 -*-
"""Constructor de piezas FreeCAD a partir de una receta JSON (ver RECETA.md).

Uso (freecadcmd interpreta mal los argumentos extra, por eso van en variables de entorno):
    set FC_RECETA=ruta\\pieza.receta.json
    set FC_SALIDA=ruta\\pieza.FCStd
    freecadcmd.exe ruta\\fc_constructor.py

Al terminar imprime una línea:
    RESULTADO {"ok":..., "volumen":..., "caja":[xmin,ymin,zmin,xmax,ymax,zmax],
               "n_operaciones":..., "valido":..., "errores":[...]}

Solo usa FreeCAD + biblioteca estándar.
"""
import json
import math
import os
import sys
import traceback

import FreeCAD as App
import Part
import Sketcher  # noqa: F401  (registra Sketcher::SketchObject)

V = App.Vector
TOL_PUNTO = 1e-6        # tolerancia para decidir si dos extremos son el mismo punto
TOL_ARISTA = 1.0        # mm: distancia máxima de un punto de redondeo a su arista

# Plano de la receta -> (Role del plano del Origin, giro del AttachmentOffset)
# Convención SolidWorks (Y arriba):
#   Alzado : croquis x->+X, y->+Y, normal +Z
#   Planta : croquis x->+X, y->-Z, normal +Y
#   Lateral: croquis x->-Z, y->+Y, normal +X
PLANOS = {
    "Alzado": ("XY_Plane", App.Rotation()),
    "Planta": ("XZ_Plane", App.Rotation(V(1, 0, 0), 180)),
    "Lateral": ("YZ_Plane", App.Rotation(V(0, 0, 1), -90)),
}


def _num(x):
    """Número con formato corto para expresiones."""
    return repr(float(x)).rstrip("0").rstrip(".") if float(x) != int(x) else str(int(x))


def plano_origen(body, role):
    for f in body.Origin.OriginFeatures:
        if getattr(f, "Role", "") == role or f.Name.startswith(role):
            return f
    raise RuntimeError("No encuentro el plano %s en el Origin del Body" % role)


def crear_hoja(doc, variables, errores):
    hoja = doc.addObject("Spreadsheet::Sheet", "Variables")
    hoja.Label = "Variables"
    hoja.set("A1", "Variable")
    hoja.set("B1", "Valor")
    fila = 2
    for nombre, valor in variables.items():
        hoja.set("A%d" % fila, str(nombre))
        hoja.set("B%d" % fila, _num(valor))
        try:
            hoja.setAlias("B%d" % fila, str(nombre))
        except Exception as e:
            errores.append("Variable '%s': alias no válido (%s)" % (nombre, e))
        fila += 1
    doc.recompute()
    return hoja


# ---------------------------------------------------------------- croquis
def _p(xy):
    return V(float(xy[0]), float(xy[1]), 0)


def dibujar_perfiles(sk, perfiles, errores, nombre_op):
    """Añade los lazos al croquis con restricciones Coincident entre extremos consecutivos."""
    for n_lazo, lazo in enumerate(perfiles, 1):
        # (indice geometría, vértice de inicio del encadenado, vértice de fin, punto ini, punto fin)
        cadena = []
        for ent in lazo:
            t = ent[0]
            if t == "L":
                a, b = _p(ent[1]), _p(ent[2])
                if (a - b).Length < TOL_PUNTO:
                    continue  # línea degenerada
                g = sk.addGeometry(Part.LineSegment(a, b), False)
                cadena.append((g, 1, 2, a, b))
            elif t == "A":
                c, pi, pf = _p(ent[1]), _p(ent[2]), _p(ent[3])
                s = ent[4] if len(ent) > 4 else 1
                r = (pi - c).Length
                a_i = math.atan2(pi.y - c.y, pi.x - c.x)
                a_f = math.atan2(pf.y - c.y, pf.x - c.x)
                if s < 0:
                    # FreeCAD: arcos siempre antihorarios -> intercambiar inicio y fin
                    a0, a1 = a_f, a_i
                else:
                    a0, a1 = a_i, a_f
                while a1 <= a0 + 1e-12:
                    a1 += 2 * math.pi
                arco = Part.ArcOfCircle(Part.Circle(c, V(0, 0, 1), r), a0, a1)
                g = sk.addGeometry(arco, False)
                if s < 0:
                    # en el encadenado se entra por pi (= fin del arco, vértice 2) y se sale por pf (vértice 1)
                    cadena.append((g, 2, 1, pi, pf))
                else:
                    cadena.append((g, 1, 2, pi, pf))
            elif t == "C":
                sk.addGeometry(Part.Circle(_p(ent[1]), V(0, 0, 1), float(ent[2])), False)
            else:
                errores.append("%s: entidad desconocida %r" % (nombre_op, t))
        # restricciones de coincidencia entre extremos consecutivos (cerrando el lazo)
        n = len(cadena)
        if n >= 2:
            for k in range(n):
                g1, _, fin1, _, pfin1 = cadena[k]
                g2, ini2, _, pini2, _ = cadena[(k + 1) % n]
                if (pfin1 - pini2).Length < 1e-3:
                    sk.addConstraint(Sketcher.Constraint("Coincident", g1, fin1, g2, ini2))
                else:
                    errores.append("%s: lazo %d abierto entre entidades %d y %d (%.4f mm)"
                                   % (nombre_op, n_lazo, k + 1, (k + 1) % n + 1, (pfin1 - pini2).Length))


# ---------------------------------------------------------------- operaciones
def expr_param(op, clave):
    """Expresión (texto) del parámetro 'desde'/'hasta': variable si está en cotas, si no el número."""
    cotas = op.get("cotas") or {}
    if clave in cotas:
        return "Variables.%s" % cotas[clave]
    return None


def crear_operacion(doc, body, op, n_croquis, errores):
    nombre = op.get("nombre") or op["tipo"]
    plano = op.get("plano", "Alzado")
    if plano not in PLANOS:
        raise RuntimeError("%s: plano desconocido '%s'" % (nombre, plano))
    role, giro = PLANOS[plano]
    desde = float(op.get("desde", 0))
    hasta = float(op.get("hasta", 0))
    pasante = bool(op.get("pasante", False))
    tipo = op["tipo"]

    # Croquis en 'desde' (desplazado a lo largo de la normal del plano)
    sk = body.newObject("Sketcher::SketchObject", "Croquis%d" % n_croquis)
    sk.Label = "Croquis%d" % n_croquis
    sk.AttachmentSupport = [(plano_origen(body, role), "")]
    sk.MapMode = "FlatFace"
    sk.AttachmentOffset = App.Placement(V(0, 0, desde), giro)
    dibujar_perfiles(sk, op.get("perfiles", []), errores, nombre)

    e_desde = expr_param(op, "desde")
    e_hasta = expr_param(op, "hasta")
    if e_desde:
        sk.setExpression(".AttachmentOffset.Base.z", e_desde)

    # Sentido: el material/corte va de 'desde' a 'hasta' a lo largo de la normal.
    adelante = hasta >= desde
    longitud = abs(hasta - desde)
    expr_len = None
    if e_desde or e_hasta:
        a = e_desde or _num(desde)
        b = e_hasta or _num(hasta)
        mayor, menor = (b, a) if adelante else (a, b)
        expr_len = mayor if menor == "0" else "%s - (%s)" % (mayor, menor)

    if tipo == "saliente":
        f = body.newObject("PartDesign::Pad", "Saliente")
        f.Profile = sk
        f.Type = "Length"
        f.Length = longitud
        f.Reversed = not adelante  # Pad: por defecto hacia la normal del croquis
    elif tipo == "corte":
        if body.Tip is None or body.Tip == sk:
            prev = [o for o in body.Group if o.isDerivedFrom("PartDesign::FeatureAddSub")]
            if not prev:
                raise RuntimeError("%s: un corte no puede ser la primera operación" % nombre)
        f = body.newObject("PartDesign::Pocket", "Corte")
        f.Profile = sk
        # Pocket: por defecto corta en contra de la normal -> Reversed para ir hacia la normal
        f.Reversed = adelante
        if pasante:
            f.Type = "ThroughAll"
            expr_len = None
        else:
            f.Type = "Length"
            f.Length = longitud
    else:
        raise RuntimeError("%s: tipo desconocido '%s'" % (nombre, tipo))

    if expr_len:
        f.setExpression("Length", expr_len)
    for clave in (op.get("cotas") or {}):
        if clave not in ("desde", "hasta"):
            errores.append("%s: cota '%s' no soportada (solo desde/hasta)" % (nombre, clave))

    f.Label = nombre
    sk.Visibility = False
    return f


# ---------------------------------------------------------------- redondeos
def aristas_cercanas(shape, puntos, errores, etiqueta):
    nombres = []
    for p in puntos:
        vx = Part.Vertex(V(*[float(c) for c in p]))
        mejor, dmin = None, None
        for i, e in enumerate(shape.Edges, 1):
            d = vx.distToShape(e)[0]
            if dmin is None or d < dmin:
                mejor, dmin = i, d
        if mejor is None or dmin > TOL_ARISTA:
            errores.append("%s: ninguna arista cerca del punto %s (mín %.3f mm)"
                           % (etiqueta, p, dmin if dmin is not None else -1))
            continue
        nom = "Edge%d" % mejor
        if nom not in nombres:
            nombres.append(nom)
    return nombres


def objetos_con_error(doc):
    malos = []
    for o in doc.Objects:
        st = o.State
        if "Invalid" in st or "Error" in st:
            malos.append("%s (%s): %s" % (o.Label, o.Name, ",".join(st)))
    return malos


def crear_redondeos(doc, body, redondeos, errores):
    n_ok = 0
    for i, grupo in enumerate(redondeos, 1):
        etiqueta = "Redondeo%d" % i  # grupo de la receta (para los avisos)
        tip = body.Tip
        radio = float(grupo["radio"])
        aristas = aristas_cercanas(tip.Shape, grupo.get("puntos", []), errores, etiqueta)
        if not aristas:
            errores.append("%s: sin aristas, se omite" % etiqueta)
            continue
        f = body.newObject("PartDesign::Fillet", "Redondeo")
        f.Base = (tip, aristas)
        f.Radius = radio
        f.Label = "Redondeo%d" % (n_ok + 1)  # numeración del árbol como SolidWorks
        fallo = None
        try:
            doc.recompute()
            if "Invalid" in f.State or "Error" in f.State:
                fallo = "error de recompute"
            elif f.Shape.isNull() or not f.Shape.isValid():
                fallo = "sólido no válido"
        except Exception as e:
            fallo = str(e)
        if fallo:
            errores.append("%s (r=%g, %s) falló: %s; se quita" % (etiqueta, radio, ",".join(aristas), fallo))
            doc.removeObject(f.Name)
            body.Tip = tip
            doc.recompute()
        else:
            n_ok += 1
    return n_ok


# ---------------------------------------------------------------- principal
def construir(ruta_receta, ruta_salida):
    errores = []
    with open(ruta_receta, "r", encoding="utf-8") as fh:
        receta = json.load(fh)

    nombre_doc = "".join(ch if ch.isalnum() else "_" for ch in str(receta.get("nombre", "Pieza"))) or "Pieza"
    doc = App.newDocument(nombre_doc)
    # Con el "hasher" de nombres topológicos activado (por defecto en 1.1), los redondeos pierden
    # sus aristas al cambiar una cota (probado: caja + Fillet, cambiar Length -> '?Edge1').
    # Sin hasher los nombres se guardan completos y el redondeo sobrevive a los cambios.
    try:
        doc.UseHasher = False
    except Exception as e:
        errores.append("No se pudo desactivar UseHasher: %s" % e)
    try:
        crear_hoja(doc, receta.get("variables") or {}, errores)
        body = doc.addObject("PartDesign::Body", "Body")
        body.Label = receta.get("nombre", "Pieza")

        n_ops = 0
        for k, op in enumerate(receta.get("operaciones", []), 1):
            crear_operacion(doc, body, op, k, errores)
            n_ops += 1
            doc.recompute()
            malos = objetos_con_error(doc)
            if malos:
                raise RuntimeError("Operación %s falla: %s" % (op.get("nombre", k), "; ".join(malos)))

        n_ops += crear_redondeos(doc, body, receta.get("redondeos") or [], errores)

        doc.recompute()
        malos = objetos_con_error(doc)
        if malos:
            raise RuntimeError("Objetos con error: " + "; ".join(malos))

        sh = body.Shape
        bb = sh.BoundBox
        res = {
            "ok": True,
            "volumen": round(sh.Volume, 4),
            "caja": [round(c, 4) for c in (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)],
            "n_operaciones": n_ops,
            "valido": bool(sh.isValid()),
            "errores": errores,
        }
        if ruta_salida:
            carpeta = os.path.dirname(os.path.abspath(ruta_salida))
            if carpeta and not os.path.isdir(carpeta):
                os.makedirs(carpeta)
            doc.saveAs(ruta_salida)
        return res
    finally:
        App.closeDocument(doc.Name)


def main():
    ruta_receta = os.environ.get("FC_RECETA", "")
    ruta_salida = os.environ.get("FC_SALIDA", "")
    try:
        if not ruta_receta or not os.path.isfile(ruta_receta):
            raise RuntimeError("FC_RECETA no apunta a un archivo: %r" % ruta_receta)
        res = construir(ruta_receta, ruta_salida)
    except Exception as e:
        res = {"ok": False, "volumen": 0, "caja": [], "n_operaciones": 0, "valido": False,
               "errores": ["%s: %s" % (type(e).__name__, e), traceback.format_exc(limit=3)]}
    sys.stdout.write("RESULTADO " + json.dumps(res) + "\n")
    sys.stdout.flush()


main()
