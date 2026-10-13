"""Lee las cotas escritas en un plano PDF (con texto) y las convierte en codigo VBA para SolidWorks.

Mejoras sobre la primera version: ignora el marco y el cajetin, entiende Ø / R / M / grados / tolerancias /
multiplicador «4x», agrupa las repetidas, las clasifica y les pone un nombre con sentido (ancho, alto, espesor,
diametro, radio...) cruzandolas con la geometria del propio plano.
"""
import re

import pymupdf as fitz

MARGEN = 38          # puntos PDF: el marco de la hoja lleva letras y numeros (A-F, 1-4) que no son cotas
PALABRAS_CAJETIN = ("DIBUJ", "VERIF", "APROB", "FABR", "CALID", "MATERIAL", "ESCALA", "PESO", "HOJA", "TÍTULO",
                    "TITULO", "REVISI", "TOLERANCIAS", "LINEAL", "ANGULAR", "ACABADO", "NOMBRE", "FIRMA", "FECHA",
                    "DIBUJO", "REBARBAR", "ROMPER", "ARISTAS", "COTAS", "EXPRESAN", "CONTRARIO")

PATRON = re.compile(
    r"^\s*(?:(?P<n>\d{1,2})\s*[x×X]\s*)?"                      # 4x
    r"(?P<pre>[ØøΦ⌀]|R|M|DIA\.?)?\s*"                         # Ø / R / M
    r"(?P<val>\d{1,4}(?:[.,]\d{1,3})?)"                        # 25,00
    r"\s*(?P<gr>°)?"
    r"(?:\s*(?P<tol>±\s*\d+(?:[.,]\d+)?|[+-]\d+(?:[.,]\d+)?\s*/\s*[+-]\d+(?:[.,]\d+)?))?\s*$")


def _num(s):
    return float(s.replace(",", "."))


def _lineas(pagina):
    """Lineas de texto con su caja: [(x0, y0, x1, y1, texto)]."""
    out = []
    for b in pagina.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            t = "".join(s["text"] for s in l["spans"]).strip()
            if t:
                x0, y0, x1, y1 = l["bbox"]
                out.append((x0, y0, x1, y1, t))
    return out


def _caja_cajetin(lineas):
    xs0, ys0, xs1, ys1 = [], [], [], []
    for x0, y0, x1, y1, t in lineas:
        if any(p in t.upper() for p in PALABRAS_CAJETIN):
            xs0.append(x0); ys0.append(y0); xs1.append(x1); ys1.append(y1)
    if len(xs0) < 3:
        return None
    return (min(xs0) - 6, min(ys0) - 6, max(xs1) + 6, max(ys1) + 6)


def leer_cotas(ruta, pagina=0, geometria=None, escala_mm_pt=None, espesor=None):
    """-> (cotas, aviso). Cota = dict(nombre, valor, tipo, tol, n, texto, donde, usar).
    geometria = resultado de pdfgeo.leer_geometria (para reconocer ancho/alto/diametros)."""
    doc = fitz.open(ruta)
    pg = doc[pagina]
    W, H = pg.rect.width, pg.rect.height
    lineas = _lineas(pg)
    if sum(len(t) for *_, t in lineas) < 20:
        return [], "El PDF no tiene texto (es una imagen o un escaneo). Haría falta OCR; no está incluido."
    caja = _caja_cajetin(lineas)
    bruto = []
    for x0, y0, x1, y1, t in lineas:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if cx < MARGEN or cx > W - MARGEN or cy < MARGEN or cy > H - MARGEN:
            continue                                    # marco de la hoja
        if caja and caja[0] <= cx <= caja[2] and caja[1] <= cy <= caja[3]:
            continue                                    # cajetin
        m = PATRON.match(t.replace(" ", " "))
        if not m:
            continue
        v = _num(m.group("val"))
        if v <= 0:
            continue
        pre = (m.group("pre") or "").upper()
        if m.group("gr"):
            tipo = "angulo"
        elif pre in ("Ø", "Φ", "⌀") or pre.startswith("DIA"):
            tipo = "diametro"
        elif pre == "R":
            tipo = "radio"
        elif pre == "M":
            tipo = "rosca"
        else:
            tipo = "lineal"
        bruto.append(dict(valor=v, tipo=tipo, tol=(m.group("tol") or "").replace(" ", ""),
                          n=int(m.group("n") or 1), texto=t, pos=(cx, cy)))
    # agrupa las repetidas (mismo valor y tipo): R4,00 x4 -> una sola con n=4
    grupos = {}
    for c in bruto:
        k = (c["tipo"], round(c["valor"], 3), c["tol"])
        if k in grupos:
            grupos[k]["n"] += c["n"] if c["n"] > 1 else 1
        else:
            grupos[k] = dict(c)
    cotas = sorted(grupos.values(), key=lambda c: (c["tipo"], -c["valor"]))
    _nombrar(cotas, geometria, escala_mm_pt, espesor)
    aviso = "" if cotas else "Hay texto, pero no he reconocido ninguna cota (¿plano sin números?)."
    return cotas, aviso


def _nombrar(cotas, geo, esc, espesor):
    """Pone nombre con sentido cruzando cada cota con la geometria del plano."""
    ancho = alto = None
    circulos = []
    if geo and esc and geo.get("contornos"):
        ext = geo["contornos"][0]
        x0, y0, x1, y1 = ext["bbox"]
        ancho, alto = (x1 - x0) * esc, (y1 - y0) * esc
        circulos = [2 * c["r"] * esc for c in geo["contornos"][1:] if c["tipo"] == "circulo"]
    usados = {}

    def unico(base):
        usados[base] = usados.get(base, 0) + 1
        return base if usados[base] == 1 else f"{base}_{usados[base]}"

    for c in cotas:
        v, t = c["valor"], c["tipo"]
        c["usar"] = True
        c["donde"] = ""
        tol = max(0.02 * v, 0.15)
        if espesor and t == "lineal" and abs(v - espesor) < 0.01:
            c["nombre"], c["donde"] = unico("espesor"), "espesor de la chapa (cajetín)"
        elif ancho and t == "lineal" and abs(v - ancho) < tol:
            c["nombre"], c["donde"] = unico("ancho_exterior"), "ancho del contorno exterior"
        elif alto and t == "lineal" and abs(v - alto) < tol:
            c["nombre"], c["donde"] = unico("alto_exterior"), "alto del contorno exterior"
        elif t == "diametro":
            c["nombre"] = f"diametro_{v:g}"
            if any(abs(v - d) < tol for d in circulos):
                c["donde"] = "coincide con un agujero circular del dibujo"
        elif t == "radio":
            c["nombre"] = f"radio_{v:g}"
        elif t == "rosca":
            c["nombre"] = f"rosca_M{v:g}"
        elif t == "angulo":
            c["nombre"] = f"angulo_{v:g}"
        else:
            c["nombre"] = f"cota_{v:g}"
        c["nombre"] = re.sub(r"[^0-9A-Za-z_]", "_", c["nombre"])
    vistos = {}
    for c in cotas:     # nombres unicos (p. ej. diametro_8 repetido con tolerancias distintas)
        vistos[c["nombre"]] = vistos.get(c["nombre"], 0) + 1
        if vistos[c["nombre"]] > 1:
            c["nombre"] += f"_{vistos[c['nombre']]}"


def proponer(ruta):
    """Compatibilidad con la version anterior."""
    return leer_cotas(ruta)


# ---------------------------------------------------------------- codigo VBA
def a_vba(cotas, nombre_modulo="Cotas_del_plano", modo="variables"):
    """Modulo VBA con las cotas. modo: 'constantes' (solo Const) o 'variables' (ademas crea las variables
    globales de SolidWorks en Herramientas > Ecuaciones, que es lo que hacen tus macros de pieza)."""
    L = ["' ====================================================================",
         f"' {nombre_modulo}: cotas leidas de un plano PDF (Taller SolidWorks)",
         "' REVISA los nombres y valores antes de usarlos. Unidades: milimetros.",
         "' ===================================================================="]
    L.append("Option Explicit")
    L.append("")
    L.append("' --- Cotas (mm) ---")
    for c in cotas:
        extra = []
        if c["tipo"] != "lineal":
            extra.append(c["tipo"])
        if c["n"] > 1:
            extra.append(f"x{c['n']}")
        if c["tol"]:
            extra.append("tol " + c["tol"])
        if c.get("donde"):
            extra.append(c["donde"])
        comentario = f"  ' {c['texto']}" + (f"  ({', '.join(extra)})" if extra else "")
        L.append(f"Const {c['nombre'].upper()} As Double = {c['valor']:g}{comentario}")
    if modo == "variables":
        L.append("")
        L.append("Sub main()")
        L.append("    Dim swApp As SldWorks.SldWorks")
        L.append("    Dim Part As SldWorks.ModelDoc2")
        L.append("    Set swApp = Application.SldWorks")
        L.append("    Set Part = swApp.ActiveDoc")
        L.append("    If Part Is Nothing Then MsgBox \"Abre una pieza primero.\": Exit Sub")
        L.append("    Dim eq As SldWorks.EquationMgr")
        L.append("    Set eq = Part.GetEquationMgr")
        L.append("")
        for c in cotas:
            L.append(f"    PonVariable eq, \"{c['nombre']}\", {c['nombre'].upper()}")
        L.append("")
        L.append("    Part.ForceRebuild3 False")
        L.append("    MsgBox \"Variables creadas en Herramientas > Ecuaciones.\", vbInformation, \"" + nombre_modulo + "\"")
        L.append("End Sub")
        L.append("")
        L.append("' Crea la variable global o, si ya existe, le cambia el valor")
        L.append("Private Sub PonVariable(eq As SldWorks.EquationMgr, nombre As String, valor As Double)")
        L.append("    Dim i As Long")
        L.append("    Dim texto As String")
        L.append("    texto = \"\"\"\" & nombre & \"\"\" = \" & Replace(CStr(valor), \",\", \".\")")
        L.append("    For i = 0 To eq.GetCount - 1")
        L.append("        If InStr(eq.Equation(i), \"\"\"\" & nombre & \"\"\"\") = 1 Then")
        L.append("            eq.Equation(i) = texto")
        L.append("            Exit Sub")
        L.append("        End If")
        L.append("    Next i")
        L.append("    eq.Add2 -1, texto, False")
        L.append("End Sub")
    return "\r\n".join(L) + "\r\n"
