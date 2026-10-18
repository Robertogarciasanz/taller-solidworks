r"""Plano PDF (o foto) -> macro VBA que modela la pieza en SolidWorks.

1) Gemini lee el plano y describe la pieza como cajas y cilindros (salientes y cortes) + redondeos.
2) Esta receta se convierte en VBA con las funciones probadas de biblioteca_sw.bas.
3) Se ejecuta en el SolidWorks abierto y se comprueba el resultado.

Uso:  py plano_a_macro.py plano.pdf [--solo-macro]
Deja junto al plano: <plano>_receta.json, <plano>_macro.bas y <plano>_macro.swp
"""
import json
import os
import sys

import gemini_plano

AQUI = os.path.dirname(os.path.abspath(__file__))

PROMPT = """Eres un delineante experto en SolidWorks. Lee el plano y describe la pieza para modelarla.
Ejes: X = largo (horizontal del alzado), Y = alto (vertical del alzado), Z = profundidad.
Origen en X e Y: el centro del taladro o cubo principal si lo hay; si no, el centro de la pieza.
Z va de 0 (cara trasera o de apoyo) a la profundidad total.
Antes de responder, sigue cada cota por sus líneas de referencia para saber ENTRE QUÉ DOS ELEMENTOS se mide
(una cota encadenada no siempre parte del origen), y comprueba que el tamaño total cuadra con la vista.
Describe la pieza con cajas, cilindros y perfiles (contorno, ranura_arco), en mm y en coordenadas de la pieza:
- "saliente": añade material. "corte": quita material. Ponlas en ORDEN DE CONSTRUCCIÓN: cuerpo exterior,
  vaciado, después los tabiques/nervios/torretas interiores (si van antes, el vaciado se los come),
  después ventanas y agujeros, y los redondeos al final.
- caja: {"forma":"caja","x":[x0,x1],"y":[y0,y1],"z":[z0,z1],"eje":"z|y|x"}  (eje = dirección de extrusión)
- cilindro: {"forma":"cilindro","eje":"z|y|x","centro":[c1,c2],"d":diametro,"desde":s0,"hasta":s1}
  (centro en los otros dos ejes por orden: eje z -> [x,y]; eje y -> [x,z]; eje x -> [y,z])
- contorno (perfil plano con arcos, solo eje z): {"forma":"contorno","eje":"z","desde":z0,"hasta":z1,
   "circulos":[{"c":[x,y],"r":radio,"union":"tangente|arco","R":radio_arco}, ...]}
  Círculos en orden ANTIHORARIO alrededor del perfil; "union" dice cómo se une cada círculo con el
  SIGUIENTE (el último con el primero): "tangente" = recta tangente exterior; "arco" = arco cóncavo de
  radio R tangente a los dos (los R44, R16... que unen cubos y lóbulos). Sirve para almas, orejetas
  y perfiles de varios círculos (para un coliso suelto usa "ranura").
- ranura_arco (colisón curvo, solo eje z): {"forma":"ranura_arco","eje":"z","desde":z0,"hasta":z1,
   "centro":[x,y],"radio":radio_medio,"ancho":ancho,"angulo_inicio":grados,"angulo_fin":grados}
  (ángulos desde +X en sentido antihorario). El lóbulo que la rodea = equidistancia de la ranura.
- ranura recta (colisos, solo eje z): {"forma":"ranura","eje":"z","desde":z0,"hasta":z1,"centros":[[x1,y1],[x2,y2]],"ancho":a}
  Unión "arco_centro" con "centro":[x,y] = arco CONVEXO concéntrico a ese punto (p.ej. el borde exterior de un
  lóbulo curvo alrededor del cubo).
- spline (contorno libre, solo eje z): {"forma":"spline","eje":"z","desde":z0,"hasta":z1,"puntos":[[x,y],...]}
  Úsalo solo para curvas que no sean arcos.
- equidistancia (la herramienta Equidistanciar entidades): {"forma":"equidistancia","de":"nombre de otra operación",
   "distancia":d,"desde":z0,"hasta":z1}: mismo perfil desplazado d mm hacia fuera. P.ej. el lóbulo alrededor de un
  colisón R11 con borde R22 = equidistancia de 11 del colisón. Úsala siempre que dos contornos sean paralelos.
- Una caja hueca = saliente exterior + corte interior dejando el espesor de pared y la cara abierta.
- Agujeros pasantes: corte cilindro que sobresalga 1 mm por cada lado.
- Nada de contactos tangentes: los salientes que se unen deben solaparse al menos 0,5 mm.
- Redondeos de aristas paralelas a un eje: {"op":"redondeo","eje":"z","r":radio,"puntos":[[x,y],...]}
  (puntos = posición de cada arista en los otros dos ejes; p.ej. las 4 esquinas exteriores de la caja).
Devuelve SOLO JSON:
{"pieza": str, "notas": str,
 "variables": [{"nombre": "largo", "valor": num}],   // solo las 3-6 medidas principales
 "operaciones": [{"op":"saliente|corte|redondeo", "nombre": "Paredes", ...}]}
Usa las cotas del plano; si falta alguna, supón un valor razonable y dilo en "notas".
Lecciones aprendidas (errores que ya se cometieron):
- Una cota lineal entre el centro del cubo y el centro del extremo de una ranura FIJA esa coordenada
  (p.ej. "60" del cubo al extremo inferior del colisón curvo -> ese extremo está en (60, 0)).
- El ángulo de una ranura en arco se mide entre sus dos extremos desde el centro del arco; comprueba que un
  extremo cuadra con las cotas lineales antes de decidir angulo_inicio y angulo_fin.
- Las cotas encadenadas (148 = 88 + 60) se reparten entre los elementos que unen sus líneas de referencia."""


def _ejemplos(excluir=""):
    """Recetas ya comprobadas contra la pieza real (carpeta ejemplos): se dan a Gemini como modelo."""
    import glob
    txt = ""
    fs = [f for f in sorted(glob.glob(os.path.join(AQUI, "ejemplos", "*.json")))
          if not excluir or gemini_plano._limpio(excluir) not in gemini_plano._limpio(os.path.basename(f))]
    for f in fs[:4]:
        with open(f, encoding="utf-8") as fh:
            txt += "\n\nEJEMPLO RESUELTO Y COMPROBADO (" + os.path.basename(f) + "):\n" + fh.read()
    return txt

EJES = {"x": 0, "y": 1, "z": 2}
PLANO = {"z": "plFront", "y": "plTop", "x": "plRight"}

EXTRA_VBA = r'''
' ===================== PERFILES (plano_a_macro) =====================
Private Sub LnF(ByVal x1 As Double, ByVal y1 As Double, ByVal x2 As Double, ByVal y2 As Double)
    Dim a As Variant, b As Variant
    a = ToSk(x1, y1, 0): b = ToSk(x2, y2, 0)
    If Part.SketchManager.CreateLine(a(0), a(1), 0, b(0), b(1), 0) Is Nothing Then gLog = gLog & "Linea de perfil no creada" & vbCrLf
End Sub

' Arco de centro (cx,cy) de (x1,y1) a (x2,y2); sentido 1 antihorario, -1 horario (vista de frente)
Private Sub ArcF(ByVal cx As Double, ByVal cy As Double, ByVal x1 As Double, ByVal y1 As Double, ByVal x2 As Double, ByVal y2 As Double, ByVal sentido As Integer, Optional ByVal mx As Double = 0, Optional ByVal my As Double = 0)
    Dim c As Variant, a As Variant, b As Variant, seg As SldWorks.SketchSegment, m As Variant
    c = ToSk(cx, cy, 0): a = ToSk(x1, y1, 0): b = ToSk(x2, y2, 0)
    Set seg = Part.SketchManager.CreateArc(c(0), c(1), 0, a(0), a(1), 0, b(0), b(1), 0, sentido)
    If seg Is Nothing Then gLog = gLog & "Arco de perfil no creado" & vbCrLf: Exit Sub
    If mx <> 0 Or my <> 0 Then   ' cota de radio (para el plano): se pone al cerrar el contorno
        m = ToSk(mx, my, 0)
        gNArc = gNArc + 1
        ReDim Preserve gArcs(gNArc): ReDim Preserve gArcU(gNArc): ReDim Preserve gArcW(gNArc)
        Set gArcs(gNArc) = seg: gArcU(gNArc) = m(0): gArcW(gNArc) = m(1)
    End If
End Sub

' Cotas de radio de los arcos del contorno, con todo el contorno ya dibujado y unido
Private Sub DimArcos()
    Dim k As Integer
    Part.SketchManager.AddToDB = False
    Part.SketchManager.AddToDB = True
    For k = 1 To gNArc
        DimSeg gArcs(k), gArcU(k), gArcW(k)
    Next
    gNArc = 0
End Sub

' Punto en (x,y) acotado al origen: deja en el plano la posicion de un centro (ranuras)
Private Sub PosF(ByVal x As Double, ByVal y As Double)
    Dim c As Variant, p As SldWorks.SketchPoint, m As Variant
    c = ToSk(x, y, 0)
    Set p = Part.SketchManager.CreatePoint(c(0), c(1), 0)
    If p Is Nothing Then Exit Sub
    If Abs(c(0)) > 0.000001 Then
        Part.ClearSelection2 True: p.Select4 False, Nothing
        If SelOrigin Then m = ToMd(c(0) / 2, c(1) - 0.012): Part.AddHorizontalDimension2 m(0), m(1), m(2)
    End If
    If Abs(c(1)) > 0.000001 Then
        Part.ClearSelection2 True: p.Select4 False, Nothing
        If SelOrigin Then m = ToMd(c(0) - 0.012, c(1) / 2): Part.AddVerticalDimension2 m(0), m(1), m(2)
    End If
    Part.ClearSelection2 True
End Sub

' Ranura recta nativa (Croquis > Ranura recta por centros), w = ancho total (mm)
Private Function RanuraF(ByVal x1 As Double, ByVal y1 As Double, ByVal x2 As Double, ByVal y2 As Double, ByVal w As Double) As Boolean
    Dim a As Variant, b As Variant
    a = ToSk(x1, y1, 0): b = ToSk(x2, y2, 0)
    RanuraF = Not Part.SketchManager.CreateSketchSlot(swSketchSlotCreationType_line, swSketchSlotLengthType_CenterCenter, _
        w / 1000, a(0), a(1), 0, b(0), b(1), 0, 0, 0, 0, 1, True) Is Nothing
End Function

' Ranura en arco nativa (centro, extremo inicial, extremo final, antihorario)
Private Function RanuraArcoF(ByVal cx As Double, ByVal cy As Double, ByVal x1 As Double, ByVal y1 As Double, ByVal x2 As Double, ByVal y2 As Double, ByVal w As Double) As Boolean
    Dim c As Variant, a As Variant, b As Variant
    c = ToSk(cx, cy, 0): a = ToSk(x1, y1, 0): b = ToSk(x2, y2, 0)
    RanuraArcoF = Not Part.SketchManager.CreateSketchSlot(swSketchSlotCreationType_arc, swSketchSlotLengthType_CenterCenter, _
        w / 1000, c(0), c(1), 0, a(0), a(1), 0, b(0), b(1), 0, 1, True) Is Nothing
End Function

' Spline cerrado por puntos (x1, y1, x2, y2, ...) en mm
Private Sub SplineF(ByVal xy As Variant)
    Dim n As Integer, k As Integer, d() As Double, c As Variant
    n = (UBound(xy) + 1) / 2
    ReDim d(3 * n - 1)
    For k = 0 To n - 1
        c = ToSk(xy(2 * k), xy(2 * k + 1), 0)
        d(3 * k) = c(0): d(3 * k + 1) = c(1): d(3 * k + 2) = 0
    Next
    If Part.SketchManager.CreateSpline2((d), True) Is Nothing Then gLog = gLog & "Spline no creado" & vbCrLf
End Sub

' Equidistanciar entidades (herramienta de SolidWorks): todo lo del croquis activo pasa a construccion
' y se crea su equidistancia a dist mm hacia fuera (si sale hacia dentro se deshace y se invierte)
Private Sub OffsetTodo(ByVal dist As Double)
    Dim sk As SldWorks.Sketch, segs As Variant, k As Integer
    Set sk = Part.SketchManager.ActiveSketch
    segs = sk.GetSketchSegments
    If IsEmpty(segs) Then Exit Sub
    Part.ClearSelection2 True
    For k = 0 To UBound(segs)
        segs(k).Select4 True, Nothing
    Next
    If Not Part.SketchManager.SketchOffset2(dist / 1000, False, True, 0, True, True) Then gLog = gLog & "Equidistancia no creada" & vbCrLf
    Part.ClearSelection2 True
End Sub

' ===================== OPERACIONES POR EJE (plano_a_macro) =====================
' Comprueba que la operacion va de s0 a s1 (mm) en el eje 0=X, 1=Y, 2=Z:
' ninguna cara queda entera fuera del tramo y las tapas (caras planas normales al eje) estan en s0 o s1.
' (Una cara coplanaria con otra existente se une a ella y puede salirse del tramo: eso se admite.)
Private Function AxOk(ByVal f As SldWorks.Feature, ByVal eje As Integer, ByVal s0 As Double, ByVal s1 As Double) As Boolean
    Dim fcs As Variant, k As Integer, bx As Variant, a As Double, b As Double, t As Double
    t = 0.00002
    AxOk = True
    fcs = f.GetFaces
    If IsEmpty(fcs) Then Exit Function
    For k = 0 To UBound(fcs)
        bx = fcs(k).GetBox
        a = bx(eje): b = bx(eje + 3)
        If a < s0 / 1000 - t And b <= s0 / 1000 + t Then AxOk = False: Exit Function
        If b > s1 / 1000 + t And a >= s1 / 1000 - t Then AxOk = False: Exit Function
        If Abs(b - a) < t Then
            If Abs(a - s0 / 1000) > t And Abs(a - s1 / 1000) > t Then AxOk = False: Exit Function
        End If
    Next
End Function

' Saliente o corte (esCorte) de s0 a s1 a lo largo del eje normal al croquis; prueba direcciones
Private Function OpAx(ByVal sk As SldWorks.Feature, ByVal esCorte As Boolean, ByVal eje As Integer, ByVal s0 As Double, ByVal s1 As Double, ByVal nm As String) As SldWorks.Feature
    Dim f As SldWorks.Feature, k As Integer, v0 As Double, st As Integer, off As Double
    v0 = BodyVol
    If Abs(s0) < 0.0001 Then st = swStartSketchPlane Else st = swStartOffset
    off = Abs(s0) / 1000
    For k = 0 To 3
        If st = swStartSketchPlane And (k And 2) = 2 Then Exit For
        Part.ClearSelection2 True
        sk.Select2 False, 0
        If esCorte Then
            Set f = Part.FeatureManager.FeatureCut4(True, False, (k And 1) = 1, swEndCondBlind, swEndCondBlind, (s1 - s0) / 1000, 0, _
                False, False, False, False, 0, 0, False, False, False, False, False, True, True, True, True, False, _
                st, off, (k And 2) = 2, False)
        Else
            Set f = Part.FeatureManager.FeatureExtrusion3(True, False, (k And 1) = 1, swEndCondBlind, swEndCondBlind, (s1 - s0) / 1000, 0, _
                False, False, False, False, 0, 0, False, False, False, False, True, True, True, st, off, (k And 2) = 2)
        End If
        If Not f Is Nothing Then
            If AxOk(f, eje, s0, s1) And (Not esCorte Or v0 - BodyVol > 0.0000000001) Then Exit For
            DelFeat f: Set f = Nothing
        End If
    Next
    Set OpAx = Named(f, nm)
End Function
'''


RESERVA = ["gemini-3-flash-preview", "gemini-flash-lite-latest"]


def _generar(contents, config):
    """Llama a Gemini; si esta saturado (503/429) reintenta y prueba los modelos de reserva."""
    import time
    from google import genai
    from google.genai import errors
    gemini_plano._clave()
    cliente = genai.Client()
    ultimo = None
    for modelo in [gemini_plano.MODELO] + RESERVA:
        for intento in range(1):   # un intento por modelo: si esta saturado se pasa al siguiente enseguida
            try:
                return cliente.models.generate_content(model=modelo, contents=contents, config=config)
            except (errors.ServerError, errors.ClientError) as e:
                if getattr(e, "code", 0) not in (429, 500, 503):
                    raise
                ultimo = e
                print(f"    Gemini ({modelo}) saturado, reintento…")
                time.sleep(2)
    raise SystemExit(f"Gemini no responde ahora mismo ({ultimo}). Prueba dentro de un rato.")


def receta(ruta):
    from google.genai import types
    gemini_plano._clave()
    extra = ""
    if ruta.lower().endswith(".pdf"):   # planos del Taller: traen las medidas incrustadas
        import planos_gemini
        medidas = planos_gemini.leer_medidas_pdf(ruta)
        for m in medidas:
            if m.get("receta"):
                print(f"    El PDF trae la receta de {m['pieza']}: se reconstruye sin que Gemini adivine.")
                return m["receta"]
        if medidas:
            print(f"    El PDF trae las medidas exactas de {', '.join(m['pieza'] for m in medidas)}: se dan a Gemini.")
            extra = ("\n\nMEDIDAS EXACTAS DEL MODELO ORIGINAL (úsalas en vez de leerlas del dibujo; tamano_xyz es el "
                     "tamaño total y cada cota es nombre@operación):\n" + json.dumps(
                         [{k: m[k] for k in ("pieza", "tamano_xyz", "volumen", "cotas")} for m in medidas],
                         ensure_ascii=False))
    mime = gemini_plano.mimetypes.guess_type(ruta)[0] or "application/pdf"
    with open(ruta, "rb") as f:
        datos = f.read()
    r = _generar(
        contents=[types.Part.from_bytes(data=datos, mime_type=mime),
                  PROMPT + _ejemplos(os.environ.get("TALLER_SIN_EJEMPLO", "")) + extra],
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1))
    return gemini_plano.a_json(r.text)


REVISAR = """Te paso el PLANO original, dos IMÁGENES de la pieza que ha salido en SolidWorks (vista frontal, que mira
el plano XY desde +Z, e isométrica) y la RECETA JSON con la que se ha construido. {extra}
Compara pieza y plano elemento a elemento: posición y tamaño de cada cubo, taladro, ranura, lóbulo y arco de unión,
ángulos, espesores y tamaño total. Devuelve SOLO JSON:
{{"ok": true|false, "diferencias": [str], "receta": {{...la receta COMPLETA corregida, mismo formato...}}}}
Si todo coincide con el plano, "ok": true y la misma receta. Reglas del formato:
""" + PROMPT


def revisar(ruta, rec, imagenes, extra=""):
    """Gemini compara el resultado con el plano y devuelve (ok, diferencias, receta corregida)."""
    from google import genai
    from google.genai import types
    gemini_plano._clave()
    partes = [types.Part.from_bytes(data=open(ruta, "rb").read(),
                                    mime_type=gemini_plano.mimetypes.guess_type(ruta)[0] or "application/pdf")]
    for im in imagenes:
        partes.append(types.Part.from_bytes(data=open(im, "rb").read(), mime_type="image/png"))
    partes.append(REVISAR.replace("{extra}", extra).replace("{{", "{").replace("}}", "}") + "\n\nRECETA:\n" + json.dumps(rec, ensure_ascii=False))
    r = _generar( contents=partes,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1))
    res = gemini_plano.a_json(r.text)
    return bool(res.get("ok")), res.get("diferencias") or [], res.get("receta") or rec


def capturas(base):
    """Vista frontal e isometrica de la pieza activa en PNG."""
    import sw as swmod
    from PIL import Image
    d = swmod.connect().ActiveDoc
    res = []
    for vista, cod, suf in (("*Front", 1, "frente"), ("*Isometric", 7, "iso")):
        d.ShowNamedView2(vista, cod)
        d.ViewZoomtofit2()
        bmp = f"{base}_{suf}.bmp"
        d.SaveBMP(bmp, 1000, 700)
        Image.open(bmp).save(f"{base}_{suf}.png")
        os.remove(bmp)
        res.append(f"{base}_{suf}.png")
    d.ShowNamedView2("*Isometric", 7)
    d.ViewZoomtofit2()
    return res


def cerrar_activa():
    import tareas
    s = tareas._sw()   # tareas._sw prepara el enlace COM que usa tareas.val
    d = tareas.val(s, "ActiveDoc")
    if d is not None and not tareas.val(d, "GetPathName"):
        s.CloseDoc(tareas.val(d, "GetTitle"))


def _n(v):
    return f"{float(v):.4f}".rstrip("0").rstrip(".")


def _nombre(op, i):
    return gemini_plano._limpio(op.get("nombre") or f"{op['op']}_{i}").capitalize()[:30]


def _redondeos_interiores(ops):
    """Regla: antes del redondeo exterior R de una caja vaciada con pared e, redondear el interior con R-e
    (si no, el exterior atraviesa la pared y falla)."""
    extra = []
    for o in ops:
        if o.get("op") != "redondeo" or (o.get("eje") or "z") != "z" or len(o.get("puntos") or []) < 4:
            continue
        xs, ys = [p[0] for p in o["puntos"]], [p[1] for p in o["puntos"]]
        for c in ops:
            if c.get("op") != "corte" or c.get("forma") != "caja" or (c.get("eje") or "z") != "z":
                continue
            ins = [c["x"][0] - min(xs), max(xs) - c["x"][1], c["y"][0] - min(ys), max(ys) - c["y"][1]]
            e = ins[0]
            r = float(o["r"]) - e
            if e > 0 and r > 0.2 and all(abs(v - e) < 0.01 for v in ins):
                ya = any(x.get("op") == "redondeo" and abs(float(x.get("r", 0)) - r) < 0.01 for x in ops)
                if not ya:
                    x0, x1, y0, y1 = c["x"][0], c["x"][1], c["y"][0], c["y"][1]
                    extra.append({"op": "redondeo", "nombre": "Redondeo_interior", "eje": "z", "r": round(r, 3),
                                  "puntos": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]})
    return ops + extra


# ---------------------------------------------------------------- perfiles con arcos (plano XY)
def _tramos_contorno(circ):
    """Tramos ('L', p1, p2) y ('A', centro, p1, p2, sentido) del contorno de circulos (antihorario).
    sentido: 1 antihorario, -1 horario."""
    import math
    n = len(circ)
    # orden antihorario: si los centros van en horario se invierte (la union i->i+1 pasa a ser la del nuevo par)
    area = sum(float(circ[i]["c"][0]) * float(circ[(i + 1) % n]["c"][1]) -
               float(circ[(i + 1) % n]["c"][0]) * float(circ[i]["c"][1]) for i in range(n))
    if n > 2 and area < 0:
        uni = [(c.get("union"), c.get("R")) for c in circ]
        circ = [dict(c) for c in reversed(circ)]
        for k in range(n):   # nuevo par k -> k+1 = original (n-1-k) -> (n-2-k), cuya union es la del original (n-2-k)
            u, r = uni[(n - 2 - k) % n]
            circ[k]["union"], circ[k]["R"] = u, r
    C = [(float(c["c"][0]), float(c["c"][1])) for c in circ]
    R = [float(c["r"]) for c in circ]
    uniones = []   # (punto de salida del circulo i, punto de llegada al i+1, tramo intermedio o None)
    for i in range(n):
        j = (i + 1) % n
        (x1, y1), (x2, y2), r1, r2 = C[i], C[j], R[i], R[j]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        ux, uy = dx / L, dy / L
        modo = (circ[i].get("union") or "tangente").lower()
        Rb = float(circ[i].get("R") or 0)
        hecho = False
        if modo == "arco_centro" and circ[i].get("centro"):
            ox, oy = (float(v) for v in circ[i]["centro"])
            d1, d2 = math.hypot(x1 - ox, y1 - oy), math.hypot(x2 - ox, y2 - oy)
            if d1 > 1e-6 and d2 > 1e-6:
                t1 = (x1 + r1 * (x1 - ox) / d1, y1 + r1 * (y1 - oy) / d1)
                t2 = (x2 + r2 * (x2 - ox) / d2, y2 + r2 * (y2 - oy) / d2)
                uniones.append((t1, t2, ("A", (ox, oy), t1, t2, 1)))
                hecho = True
        if modo == "arco" and Rb > 0:
            a_, b_ = r1 + Rb, r2 + Rb      # centro del arco: a distancia a_ de C1 y b_ de C2, por fuera (derecha)
            if L < a_ + b_ and L > abs(a_ - b_):
                m = (a_ * a_ - b_ * b_ + L * L) / (2 * L)
                h = math.sqrt(max(a_ * a_ - m * m, 0))
                bx, by = x1 + m * ux + h * uy, y1 + m * uy - h * ux
                t1 = (x1 + r1 * (bx - x1) / a_, y1 + r1 * (by - y1) / a_)
                t2 = (x2 + r2 * (bx - x2) / b_, y2 + r2 * (by - y2) / b_)
                uniones.append((t1, t2, ("A", (bx, by), t1, t2, -1)))
                hecho = True
        if not hecho:
            k = (r1 - r2) / L
            s = math.sqrt(max(1 - k * k, 0))
            nx, ny = ux * k + uy * s, uy * k - ux * s   # normal exterior (a la derecha del avance)
            t1 = (x1 + r1 * nx, y1 + r1 * ny)
            t2 = (x2 + r2 * nx, y2 + r2 * ny)
            uniones.append((t1, t2, ("L", t1, t2)))
    # Arco de union seguido de recta tangente: si el arco toca el circulo i+1 "por detras" de donde sale la recta
    # (el perfil daria casi una vuelta al circulo), el arco se hace tangente a la RECTA, como en el plano.
    for i in range(n):
        j, k = (i + 1) % n, (i + 2) % n
        u, v = uniones[i], uniones[j]
        if u[2][0] != "A" or u[2][4] != -1 or v[2][0] != "L":
            continue
        cj = C[j]
        a_lleg = math.atan2(u[1][1] - cj[1], u[1][0] - cj[0])
        a_sal = math.atan2(v[0][1] - cj[1], v[0][0] - cj[0])
        if (a_sal - a_lleg) % (2 * math.pi) < math.pi:
            continue
        Rb = math.dist(u[2][1], u[1])
        (px, py), (qx, qy) = v[2][1], v[2][2]
        lx, ly = qx - px, qy - py
        ll = math.hypot(lx, ly)
        lx, ly = lx / ll, ly / ll
        nx, ny = ly, -lx                       # normal exterior de la recta (derecha del avance)
        ox, oy = px + Rb * nx, py + Rb * ny    # el centro del arco va por la paralela a Rb, por fuera
        ax, ay = C[i]
        ra = R[i] + Rb
        fx, fy = ox - ax, oy - ay              # |O + s*l - A| = ra
        b_ = fx * lx + fy * ly
        disc = b_ * b_ - (fx * fx + fy * fy - ra * ra)
        if disc < 0:
            continue
        s = min((-b_ + math.sqrt(disc), -b_ - math.sqrt(disc)), key=abs)
        bx, by = ox + s * lx, oy + s * ly
        t1 = (ax + R[i] * (bx - ax) / ra, ay + R[i] * (by - ay) / ra)
        t2 = (bx - Rb * nx, by - Rb * ny)
        uniones[i] = (t1, t2, ("A", (bx, by), t1, t2, -1))
        uniones[j] = (t2, v[1], ("L", t2, v[1]))
        C[j] = None                            # el circulo j queda de paso: sin arco propio
    tramos = []
    for i in range(n):
        llegada = uniones[i - 1][1]
        salida = uniones[i][0]
        if C[i] is None:
            tramos.append(uniones[i][2])
            continue
        if math.dist(llegada, salida) > 1e-6:
            tramos.append(("A", C[i], llegada, salida, 1))   # por fuera del circulo, antihorario
        tramos.append(uniones[i][2])
    return tramos


def _tramos_ranura_arco(op):
    import math
    cx, cy = (float(v) for v in op["centro"])
    rm, w = float(op["radio"]), float(op["ancho"]) / 2
    a0, a1 = math.radians(float(op["angulo_inicio"])), math.radians(float(op["angulo_fin"]))
    if a1 < a0:
        a0, a1 = a1, a0
    P = lambda r, a: (cx + r * math.cos(a), cy + r * math.sin(a))
    e0, e1 = P(rm, a0), P(rm, a1)
    return [("A", (cx, cy), P(rm + w, a0), P(rm + w, a1), 1),
            ("A", e1, P(rm + w, a1), P(rm - w, a1), 1),
            ("A", (cx, cy), P(rm - w, a1), P(rm - w, a0), -1),
            ("A", e0, P(rm - w, a0), P(rm + w, a0), 1)]


_CUBIERTOS = set()   # (cx, cy, r) que ya acota otra operacion: el contorno no repite esa cota


def _cubiertos(ops):
    import math
    res = set()
    k = lambda x, y, r: (round(float(x), 1), round(float(y), 1), round(float(r), 1))
    for o in ops:
        f = o.get("forma")
        try:
            if f == "cilindro" and (o.get("eje") or "z") == "z":
                res.add(k(o["centro"][0], o["centro"][1], float(o["d"]) / 2))
            elif f == "ranura":
                for c in o["centros"]:
                    res.add(k(c[0], c[1], float(o["ancho"]) / 2))
            elif f == "ranura_arco":
                cx, cy = o["centro"]
                rm, w = float(o["radio"]), float(o["ancho"]) / 2
                res |= {k(cx, cy, rm + w), k(cx, cy, rm - w)}
                for a in (o["angulo_inicio"], o["angulo_fin"]):
                    a = math.radians(float(a))
                    res.add(k(cx + rm * math.cos(a), cy + rm * math.sin(a), w))
        except (KeyError, TypeError, ValueError, IndexError):
            pass
    return res


def _vba_tramos(tramos, holgura=0.0):
    L = []
    for t in tramos:
        if t[0] == "L":
            (x1, y1), (x2, y2) = t[1], t[2]
            L.append(f"    LnF {_n(x1)}, {_n(y1)}, {_n(x2)}, {_n(y2)}")
        else:
            import math
            (cx, cy), (x1, y1), (x2, y2), s = t[1], t[2], t[3], t[4]
            r = math.dist((cx, cy), (x1, y1))
            a0, a1 = math.atan2(y1 - cy, x1 - cx), math.atan2(y2 - cy, x2 - cx)
            barrido = (a1 - a0) % (2 * math.pi) if s == 1 else -((a0 - a1) % (2 * math.pi))
            am = a0 + barrido / 2
            mx, my = cx + (r + 6) * math.cos(am), cy + (r + 6) * math.sin(am)
            cubierto = (round(cx, 1), round(cy, 1), round(r, 1)) in _CUBIERTOS
            cota = f", {_n(mx)}, {_n(my)}" if not cubierto else ""
            L.append(f"    ArcF {_n(cx)}, {_n(cy)}, {_n(x1)}, {_n(y1)}, {_n(x2)}, {_n(y2)}, {s}{cota}")
    return L


def _croquis(op, i, holgura=0.0):
    """Lineas VBA del croquis; devuelve (lineas, eje, s0, s1). holgura: agranda el perfil (mm)."""
    eje = (op.get("eje") or "z").lower()
    e = EJES[eje]
    L = [f"    Begin {PLANO[eje]}"]
    if op.get("forma") == "spline":
        if eje != "z":
            raise ValueError("los splines solo van en el eje z")
        pts = [(float(x), float(y)) for x, y in op["puntos"]]
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        L.append("    SplineF Array(" + ", ".join(f"{_n(x)}, {_n(y)}" for x, y in pts) + ")")
        if holgura:
            L.append(f"    OffsetTodo {_n(holgura)}")
        s0, s1 = sorted((float(op["desde"]), float(op["hasta"])))
    elif op.get("forma") == "ranura":
        if eje != "z":
            raise ValueError("las ranuras solo van en el eje z")
        (x1, y1), (x2, y2) = op["centros"]
        w = float(op["ancho"]) + 2 * holgura
        circ = [{"c": [x1, y1], "r": w / 2, "union": "tangente"}, {"c": [x2, y2], "r": w / 2, "union": "tangente"}]
        L.append(f"    PosF {_n(x1)}, {_n(y1)}")
        L.append(f"    If Not RanuraF({_n(x1)}, {_n(y1)}, {_n(x2)}, {_n(y2)}, {_n(w)}) Then")
        L += ["    " + x for x in _vba_tramos(_tramos_contorno(circ))]
        L.append("    End If")
        s0, s1 = sorted((float(op["desde"]), float(op["hasta"])))
    elif op.get("forma") == "ranura_arco" and not op.get("_arcos"):
        import math
        cx, cy = (float(v) for v in op["centro"])
        rm, w = float(op["radio"]), float(op["ancho"]) + 2 * holgura
        a0, a1 = sorted((math.radians(float(op["angulo_inicio"])), math.radians(float(op["angulo_fin"]))))
        L.append(f"    If Not RanuraArcoF({_n(cx)}, {_n(cy)}, {_n(cx + rm * math.cos(a0))}, {_n(cy + rm * math.sin(a0))}, "
                 f"{_n(cx + rm * math.cos(a1))}, {_n(cy + rm * math.sin(a1))}, {_n(w)}) Then")
        L += ["    " + x for x in _vba_tramos(_tramos_ranura_arco(dict(op, ancho=w)))]
        L.append("    End If")
        s0, s1 = sorted((float(op["desde"]), float(op["hasta"])))
    elif op.get("forma") in ("contorno", "ranura_arco"):
        if eje != "z":
            raise ValueError("los perfiles solo van en el eje z")
        if op["forma"] == "contorno":
            circ = [dict(c, r=float(c["r"]) + holgura, R=max(float(c.get("R") or 0) - holgura, 0.5) if c.get("R") else None)
                    for c in op["circulos"]]
            tramos = _tramos_contorno(circ)
        else:
            tramos = _tramos_ranura_arco(dict(op, ancho=float(op["ancho"]) + 2 * holgura))
        L += _vba_tramos(tramos)
        L.append("    DimArcos")
        s0, s1 = sorted((float(op["desde"]), float(op["hasta"])))
    elif op.get("forma") == "cilindro":
        c1, c2 = op["centro"]
        p = {"z": (c1, c2, 0), "y": (c1, 0, c2), "x": (0, c1, c2)}[eje]
        L.append(f"    CircleF {_n(p[0])}, {_n(p[1])}, {_n(p[2])}, {_n(float(op['d']) / 2 + holgura)}, False")
        s0, s1 = sorted((float(op["desde"]), float(op["hasta"])))
    else:
        rx, ry, rz = (sorted(float(v) for v in op[k]) for k in "xyz")
        a = [rx[0] - holgura, ry[0] - holgura, rz[0] - holgura]
        b = [rx[1] + holgura, ry[1] + holgura, rz[1] + holgura]
        a[e] = b[e] = 0
        L.append(f"    RectSk ToSk({_n(a[0])}, {_n(a[1])}, {_n(a[2])}), ToSk({_n(b[0])}, {_n(b[1])}, {_n(b[2])}), True, 0")
        s0, s1 = sorted([(rx, ry, rz)[e][0], (rx, ry, rz)[e][1]])
    L.append(f'    Set sk = EndSk("Sk_{_nombre(op, i)}")')
    return L, e, s0, s1


def _resolver_equidistancias(ops):
    """forma "equidistancia": {"de": nombre de otra operacion, "distancia": d} -> su mismo perfil desplazado d
    (hacia fuera si d > 0). Se guarda como la operacion de referencia con "_holgura"."""
    por_nombre = {gemini_plano._limpio(o.get("nombre")): o for o in ops if o.get("nombre")}
    res = []
    for o in ops:
        if o.get("forma") == "equidistancia":
            ref = por_nombre.get(gemini_plano._limpio(o.get("de")))
            if not ref or ref.get("forma") == "equidistancia":
                res.append(dict(o, op="aviso"))
                continue
            n = dict(ref, op=o["op"], nombre=o.get("nombre"), _holgura=float(o.get("distancia", 0)))
            for k in ("desde", "hasta"):
                if k in o:
                    n[k] = o[k]
            res.append(n)
        else:
            res.append(o)
    return res


def a_vba(rec, nombre="Pieza"):
    ops = _redondeos_interiores(_resolver_equidistancias(rec.get("operaciones") or []))
    _CUBIERTOS.clear()
    _CUBIERTOS.update(_cubiertos(ops))
    # se respeta el orden de Gemini; los redondeos al final, de menor a mayor radio (interior antes que exterior)
    ops = ([o for o in ops if o.get("op") != "redondeo"] +
           sorted((o for o in ops if o.get("op") == "redondeo"), key=lambda o: float(o.get("r", 0))))
    L = [f"' {nombre}: macro generada por el Taller (plano -> Gemini -> VBA)",
         f"' {rec.get('notas', '')}".replace("\n", " "), ""]
    L += open(os.path.join(AQUI, "biblioteca_sw.bas"), encoding="utf-8").read().splitlines()
    L += EXTRA_VBA.splitlines()
    L += ["", "Private Sub Globals()"]
    for v in rec.get("variables") or []:
        try:
            L.append(f'    Gv "{gemini_plano._limpio(v["nombre"])}", {_n(v["valor"])}')
        except (KeyError, TypeError, ValueError):
            pass
    L += ["End Sub", "",
          "Sub main()",
          "    Dim sk As SldWorks.Feature, f As SldWorks.Feature, pts() As Double, np As Integer",
          "    Set swApp = Application.SldWorks",
          "    Set mUtil = swApp.GetMathUtility",
          "    Set Part = swApp.NewDocument(swApp.GetUserPreferenceStringValue(swDefaultTemplatePart), 0, 0, 0)",
          '    If Part Is Nothing Then MsgBox "No se pudo crear la pieza.": Exit Sub',
          "    Dim oldIn As Boolean",
          "    oldIn = swApp.GetUserPreferenceToggle(swInputDimValOnCreate)",
          "    swApp.SetUserPreferenceToggle swInputDimValOnCreate, False",
          "    Part.SketchManager.AddToDB = True",
          "    Part.SketchManager.DisplayWhenAdded = False",
          "    Set eqMgr = Part.GetEquationMgr",
          "    FindBase",
          "    Globals"]
    for i, op in enumerate(ops, 1):
        tipo = op.get("op")
        nm = _nombre(op, i)
        try:
            if tipo == "aviso":
                L.append(f'    gLog = gLog & "Equidistancia sin referencia: {nm}" & vbCrLf')
                continue
            if tipo in ("saliente", "corte"):
                hol = float(op.get("_holgura", 0))
                cro, e, s0, s1 = _croquis(op, i, hol)
                L += ["", f"    ' --- {tipo}: {nm}"] + cro
                if tipo == "corte":
                    # si el perfil coincide con aristas existentes el corte falla: se repite 0,01 mm mayor
                    cro2 = _croquis(op, i, hol + 0.01)[0]
                    L.append(f'    Set f = OpAx(sk, True, {e}, {_n(s0)}, {_n(s1)}, "")')
                    L.append("    If f Is Nothing Then")
                    L += ["    " + x for x in cro2[:-1]] + [f'        Set sk = EndSk("Sk_{nm}_b")']
                    L.append("    End If")
                    L.append("    If f Is Nothing Then Set f = OpAx(sk, True, "
                             f'{e}, {_n(s0)}, {_n(s1)}, "{nm}") Else f.Name = "{nm}"')
                else:
                    L.append(f'    Set f = OpAx(sk, False, {e}, {_n(s0)}, {_n(s1)}, "{nm}")')
            elif tipo == "redondeo":
                eje = (op.get("eje") or "z").lower()
                pts = op.get("puntos") or []
                if eje not in EJES or not pts:
                    L.append(f'    gLog = gLog & "Redondeo sin datos: {nm}" & vbCrLf')
                    continue
                L += ["", f"    ' --- redondeo R{_n(op['r'])}: {nm}", f"    ReDim pts(2, {len(pts) - 1}): np = 0"]
                for p in pts:   # puntos en los otros dos ejes: z -> [x,y]; y -> [x,z]; x -> [y,z]
                    q = {"z": (p[0], p[1], 0), "y": (p[0], 0, p[1]), "x": (0, p[0], p[1])}[eje]
                    L.append(f"    AddPt pts, np, {_n(q[0])}, {_n(q[1])}, {_n(q[2])}")
                L.append(f'    Set f = FilletEdges(pts, np, {EJES[eje] + 1}, {_n(op["r"])}, "{nm}")')
        except (KeyError, TypeError, ValueError, IndexError) as ex:
            L.append(f"    ' operacion {i} ignorada (datos incompletos: {ex})")
    L += ["",
          "    Part.ClearSelection2 True",
          "    Part.ForceRebuild3 False",
          '    Part.ShowNamedView2 "*Isometric", 7',
          "    Part.ViewZoomtofit2",
          "    swApp.SetUserPreferenceToggle swInputDimValOnCreate, oldIn",
          "    Part.SketchManager.DisplayWhenAdded = True",
          '    If gLog <> "" Then Part.Extension.CustomPropertyManager("").Add3 "AvisosMacro", 30, Left(gLog, 250), 2',
          "End Sub"]
    return "\r\n".join(L) + "\r\n"


def comprobar():
    """Resumen de la pieza activa: solidos, volumen, operaciones fallidas, avisos."""
    import sw as swmod
    import tareas
    s = tareas._sw()
    d = tareas.val(s, "ActiveDoc")
    if d is None:
        return "No se ha creado ninguna pieza."
    cuerpos = d.GetBodies2(0, True) or []
    vol = d.Extension.CreateMassProperty.Volume * 1e6 if cuerpos else 0.0
    ops = [(tareas.val(f, "Name"), t) for f, t in swmod.iter_features(d)]
    hechas = [n for n, t in ops if t not in ("RefPlane", "OriginProfileFeature", "ProfileFeature")
              and not n.startswith(("Sk_", "Croquis"))]
    sueltos = [n for n, t in ops if t == "ProfileFeature" and n.startswith("Sk_")]
    try:
        avisos = d.Extension.CustomPropertyManager("").Get("AvisosMacro") or ""
    except Exception:
        avisos = ""
    txt = f"Pieza: {len(cuerpos)} sólido(s), {vol:.1f} cm³. Operaciones: {', '.join(hechas) or 'ninguna'}."
    if avisos:
        txt += "\nAvisos de la macro: " + str(avisos).replace("\r\n", "; ")
    return txt


def crear(ruta, ejecutar=True, misma_receta=False, rondas=1, original=None):
    """Todo el proceso. rondas: veces que Gemini revisa el resultado y corrige la receta.
    original: .SLDPRT para comparar volumen y tamaño (opcional). Devuelve la ruta del .swp."""
    base = os.path.splitext(ruta)[0]
    ref = medir_original(original) if original else None
    swp = None
    for ronda in range(1, max(rondas, 1) + 1):
        if ronda > 1:
            cerrar_activa()   # no mezclar piezas: la version anterior se cierra sin guardar
            misma_receta = True
            print(f"\n=== Ronda {ronda}: repito con la receta corregida ===")
        swp = _crear_una(ruta, ejecutar, misma_receta)
        if not ejecutar:
            return swp
        extra, igual = "", None
        if ref:
            n, v, tam = medidas(__import__("sw").connect().ActiveDoc)
            print(f"    Comparación con el original: {v:.1f} cm³ (original {ref[1]:.1f}), tamaño {tam} (original {ref[2]})")
            dv = (v - ref[1]) / ref[1] * 100
            igual = abs(dv) < 2 and all(abs(a - b) < 1 for a, b in zip(tam, ref[2]))
            if igual:
                print("    Coincide con el original (volumen y tamaño).")
                break
            extra = (f"La pieza buena mide {ref[1]:.1f} cm3 y {ref[2]} mm; la que ha salido {v:.1f} cm3 ({dv:+.1f} %) "
                     f"y {tam} mm. NO coincide aunque el contorno se parezca: busca qué elemento está mal colocado "
                     f"o mal girado (ángulos de ranuras, desde dónde parte cada cota) y corrígelo.")
        if ronda == max(rondas, 1):
            break
        print("    Gemini revisa el resultado…")
        ok, dif, nueva = revisar(ruta, json.load(open(base + "_receta.json", encoding="utf-8")), capturas(base), extra)
        for x in dif:
            print("     - " + x)
        if ok and igual is None:
            print("    Gemini: la pieza coincide con el plano.")
            break
        with open(base + "_receta.json", "w", encoding="utf-8") as f:
            json.dump(nueva, f, indent=1, ensure_ascii=False)
    print("Revisa la pieza y guárdala. La macro queda junto al plano para repetirla.")
    return swp


def _crear_una(ruta, ejecutar=True, misma_receta=False):
    import swp_escribir
    base = os.path.splitext(ruta)[0]
    if misma_receta and os.path.exists(base + "_receta.json"):
        with open(base + "_receta.json", encoding="utf-8") as f:
            rec = json.load(f)
        print("1/3 Usando la receta ya leída: " + os.path.basename(base) + "_receta.json")
    else:
        print(f"1/3 Gemini está leyendo {os.path.basename(ruta)}…")
        rec = receta(ruta)
    with open(base + "_receta.json", "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, ensure_ascii=False)
    ops = rec.get("operaciones") or []
    print(f"    {rec.get('pieza', '')}: {len(ops)} operaciones ({', '.join(_nombre(o, i) for i, o in enumerate(ops, 1))})")
    if rec.get("notas"):
        print("    Notas: " + rec["notas"])
    print("2/3 Escribiendo la macro…")
    vba = a_vba(rec, os.path.basename(base))
    with open(base + "_macro.bas", "w", encoding="cp1252", errors="replace") as f:
        f.write(vba)
    swp, n = base + "_macro.swp", 1
    while True:   # SolidWorks deja bloqueada la macro ya ejecutada: entonces se usa un nombre nuevo
        try:
            if os.path.exists(swp):
                os.remove(swp)
            break
        except PermissionError:
            n += 1
            swp = f"{base}_macro_{n}.swp"
    swp_escribir.escribir_swp(vba, swp)
    print("    " + swp)
    if ejecutar:
        import tareas
        print("3/3 SolidWorks está creando la pieza (puede tardar un minuto)…")
        tareas.ejecutar_macro(swp)
        print(comprobar())
        comparar_con_pdf(ruta)
    return swp


def comparar_con_pdf(ruta):
    """Si el plano trae las medidas reales incrustadas, dice si la pieza creada COINCIDE (el «OK» de la macro solo
    significa que se ejecuto sin errores)."""
    if not ruta.lower().endswith(".pdf"):
        return None
    import planos_gemini
    import tareas
    reales = planos_gemini.leer_medidas_pdf(ruta)   # (no llamarla 'medidas': taparia la funcion medidas())
    if not reales:
        print("    (El plano no trae medidas reales: no se puede comprobar si la pieza coincide.)")
        return None
    m = reales[0]
    d = tareas.val(tareas._sw(), "ActiveDoc")
    if d is None:
        return None
    n, v, tam = medidas(d)
    dv = (v - m["volumen"]) / m["volumen"] * 100 if m["volumen"] else 100
    dt = max(abs(a - b) / max(b, 1e-6) * 100 for a, b in zip(sorted(tam), sorted(m["tamano_xyz"])))
    ok = n == m["solidos"] and abs(dv) < 1 and dt < 1
    print(f"    {'✔ COINCIDE' if ok else '✖ NO COINCIDE'} con la pieza real {m['pieza']}: volumen {v:.1f} cm³ "
          f"({dv:+.1f} %), tamaño {sorted(tam)} frente a {sorted(m['tamano_xyz'])} mm, sólidos {n}/{m['solidos']}.")
    return ok




def medidas(d):
    """(solidos, volumen cm3, tamaño x,y,z mm) de una pieza abierta."""
    cuerpos = d.GetBodies2(0, True) or []
    vol = d.Extension.CreateMassProperty.Volume * 1e6 if cuerpos else 0.0
    caja = d.GetPartBox(True) if cuerpos else [0] * 6
    return len(cuerpos), vol, [round((caja[k + 3] - caja[k]) * 1000, 1) for k in range(3)]


def medir_original(ruta):
    """Abre la pieza original en solo lectura, la mide y la cierra sin guardar."""
    import sw as swmod
    import tareas
    s = tareas._sw()
    err, warn = tareas._byref(), tareas._byref()
    d = s.OpenDoc6(ruta, 1, 1 | 2, "", err, warn)   # pieza, silencioso + solo lectura
    if d is None:
        return None
    try:
        ops = [tareas.val(f, "Name") for f, t in swmod.iter_features(d)
               if t not in ("RefPlane", "OriginProfileFeature", "ProfileFeature", "MaterialFolder")]
        return medidas(d) + (ops,)
    finally:
        s.CloseDoc(tareas.val(d, "GetTitle"))

if __name__ == "__main__":
    a = sys.argv
    crear(a[1], ejecutar="--solo-macro" not in a, misma_receta="--misma-receta" in a,
          rondas=int(a[a.index("--rondas") + 1]) if "--rondas" in a else 1,
          original=a[a.index("--original") + 1] if "--original" in a else None)
