r"""Plano A4 (con isometrica y cotas exactas del modelo) de la pieza abierta en SolidWorks.

Gemini decide QUE se acota (mira el plano original si lo hay y la lista de cotas de la pieza) y el titulo,
material y nota de parametros; SolidWorks dibuja el plano con lib/swplanos.py (cotas parametricas, sin repetir,
sin solapes, isometrica sombreada, cajetin del usuario) y lo exporta a PDF.

Uso:  py planos_gemini.py <carpeta_destino> [plano_original.pdf]
"""
import json
import os
import sys

import gemini_plano

LIB = r"C:/Users/xaxaj/.claude/skills/solidworks-control/lib"

PROMPT = """Eres delineante. Hay que hacer el plano A4 de fabricación de esta pieza de SolidWorks.
Te paso la lista de COTAS que tiene el modelo (nombre@operación, valor en mm o radianes si es ángulo){orig}.
Elige las operaciones cuyas cotas deben salir en el plano para fabricar la pieza: TODAS las medidas necesarias
(el plano original, si lo hay, dice cuántas son: no te quedes corto), ninguna repetida y sin cotas auxiliares
(desfases de 1 mm de los cortes, profundidades de corte pasante). Incluye los redondeos que el original acota.
Material: el del original o el de la pieza; si no hay ninguno, deja "".
Devuelve SOLO JSON:
{{"titulo": str, "material": str, "operaciones": [nombres de operación tal cual], "parametros": [str],
  "faltan": [str]}}
- parametros: 1-3 líneas cortas para la nota del plano. SOLO valores que estén en la lista de cotas o escritos
  en el plano original (nada supuesto: si dudas, no lo pongas).
- faltan: medidas del plano original que no están en la lista de cotas (para avisar)."""


COLOCAR = """Eres delineante. Te paso la IMAGEN de un plano A4 vertical (210 x 297 mm) y la lista de sus COTAS con su
posición actual del texto en mm (x desde la izquierda, y desde ABAJO). Problemas detectados: {problemas}
Mueve SOLO las cotas que estén mal colocadas: textos que se pisan, textos cruzados por líneas, textos pegados al
marco o metidos en otra vista. Reglas: cada texto cerca de su elemento, fuera de la pieza, sin cruzar otras cotas,
dentro de x 30-196 e y 75-280, y sin entrar en las otras vistas ni en la isométrica.
Devuelve SOLO JSON: {{"mover": [{{"id": n, "x": mm, "y": mm, "motivo": str}}]}}"""


def _defectos(pdf):
    """Defectos del auditor de planos (lib/auditar_planos.py) de UNA hoja y su descripcion. El auditor revisa
    carpetas enteras: se copia la hoja sola a una carpeta temporal (antes se sumaban todas las hojas)."""
    import shutil
    import subprocess
    import tempfile
    if os.path.isdir(pdf):
        raise ValueError("_defectos necesita un PDF, no una carpeta")
    tmp = tempfile.mkdtemp(prefix="auditar_")
    shutil.copy2(pdf, tmp)
    python = "py" if getattr(sys, "frozen", False) else sys.executable   # dentro del exe, sys.executable es el Taller
    r = subprocess.run([python, os.path.join(LIB, "auditar_planos.py"), tmp],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    shutil.rmtree(tmp, ignore_errors=True)
    n = 0
    for linea in r.stdout.splitlines():
        if linea.startswith("TOTAL defectos:"):
            n = int(linea.split(":")[1])
    return n, r.stdout.strip()


def acercar_a_su_vista(drw, margen=0.015):
    """Regla fija: el texto de cada cota queda a menos de 'margen' (m) de SU vista. Si esta mas lejos (sus lineas
    cruzarian otras vistas) se trae al borde de su vista por el lado donde estaba."""
    n = 0
    v = drw.GetFirstView
    while v is not None:
        try:
            x0, y0, x1, y1 = v.GetOutline
        except Exception:
            v = v.GetNextView
            continue
        dd = v.GetFirstDisplayDimension5
        while dd is not None:
            a = dd.GetAnnotation
            x, y, z = a.GetPosition
            nx = min(max(x, x0 - margen), x1 + margen)
            ny = min(max(y, y0 - margen), y1 + margen)
            if abs(nx - x) > 1e-4 or abs(ny - y) > 1e-4:
                a.SetPosition2(nx, ny, z)
                n += 1
            dd = dd.GetNext5
        v = v.GetNextView
    if n:
        drw.ForceRebuild3(False)
    return n


def colocar_con_gemini(drw, pdf, rondas=2):
    """Gemini mira el plano y recoloca las cotas mal puestas. Solo se conserva si baja el numero de defectos."""
    import pymupdf
    from google.genai import types
    import plano_a_macro
    import tareas
    carpeta_pdf = os.path.dirname(pdf)
    n0, informe = _defectos(pdf)
    for ronda in range(rondas):
        if n0 == 0:
            break
        dims, k = [], 0
        v = drw.GetFirstView
        while v is not None:
            dd = v.GetFirstDisplayDimension5
            while dd is not None:
                a = dd.GetAnnotation
                pos = a.GetPosition
                dm = dd.GetDimension2(0)
                ang = "°" if dm.GetType == 2 else ""   # 2 = swDimensionParamTypeDoubleAngular
                valor = round(dm.SystemValue * (57.2958 if ang else 1000), 2)
                dims.append({"id": k, "valor": f"{valor}{ang}", "vista": v.Name,
                             "x": round(pos[0] * 1000, 1), "y": round(pos[1] * 1000, 1), "_a": a, "_p": pos})
                k += 1
                dd = dd.GetNext5
            v = v.GetNextView
        png = pdf[:-4] + "_revision.png"
        pymupdf.open(pdf)[0].get_pixmap(dpi=110).save(png)
        lista = [{x: d[x] for x in ("id", "valor", "vista", "x", "y")} for d in dims]
        txt = COLOCAR.replace("{problemas}", informe).replace("{{", "{").replace("}}", "}")
        r = plano_a_macro._generar(contents=[
            types.Part.from_bytes(data=open(png, "rb").read(), mime_type="image/png"),
            txt + "\n\nCOTAS:\n" + json.dumps(lista, ensure_ascii=False)],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1))
        movs = gemini_plano.a_json(r.text).get("mover") or []
        os.remove(png)
        hechos = []
        for m in movs:
            try:
                d = dims[int(m["id"])]
                x, y = float(m["x"]), float(m["y"])
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            if 30 <= x <= 196 and 75 <= y <= 280:
                d["_a"].SetPosition2(x / 1000, y / 1000, d["_p"][2])
                hechos.append((d, m.get("motivo", "")))
        if not hechos:
            break
        drw.ForceRebuild3(False)
        drw.SaveAs3(pdf, 0, 1)
        n1, informe1 = _defectos(pdf)
        print(f"   Gemini movió {len(hechos)} cotas: defectos {n0} -> {n1}")
        if n1 > n0:   # peor: se deshace
            for d, _ in hechos:
                d["_a"].SetPosition2(*d["_p"])
            drw.ForceRebuild3(False)
            drw.SaveAs3(pdf, 0, 1)
            print("   Empeoraba: deshecho.")
            break
        for d, motivo in hechos:
            print(f"     {d['valor']}: {motivo}")
        n0, informe = n1, informe1
    tareas.val(drw, "Save")
    return n0


PLANIFICAR = """Eres delineante. Te paso la IMAGEN de un plano A4 vertical (210 x 297 mm, coordenadas en mm con
y desde ABAJO), sus VISTAS (nombre y rectángulo) y sus COTAS (id, valor, vista, posición del texto).
Decide si hacen falta, para que el plano se lea bien:
- una VISTA DE DETALLE: cuando hay elementos pequeños (orejetas, chaflanes, radios pequeños) cuyas cotas quedan
  amontonadas o con líneas muy largas. Indica la vista madre, el círculo a ampliar (centro y radio en mm de hoja,
  dentro de esa vista), dónde poner el detalle (un hueco libre, dentro de x 35-190, y 80-275, sin pisar otras
  vistas), la escala (2 o 5 veces la de la vista madre) y qué cotas (ids) pasan al detalle.
- una SECCIÓN PARCIAL: cuando hay cavidades o profundidades interiores que no se ven (huecos, compartimentos).
  Indica la vista, el rectángulo a abrir (mm de hoja, dentro de la vista) y la profundidad del corte en mm de PIEZA.
Si no hacen falta, null. Devuelve SOLO JSON:
{{"detalle": null | {{"vista": str, "cx": mm, "cy": mm, "r": mm, "x": mm, "y": mm, "escala": 2, "cotas": [ids]}},
  "seccion_parcial": null | {{"vista": str, "x0": mm, "y0": mm, "x1": mm, "y1": mm, "profundidad": mm}},
  "motivo": str}}"""


def _sel_data(drw):
    return drw.SelectionManager.CreateSelectData


def vistas_y_cotas(drw):
    vistas, dims, k = [], [], 0
    v = drw.GetFirstView
    while v is not None:
        try:
            x0, y0, x1, y1 = v.GetOutline
            vistas.append({"vista": v.Name, "x0": round(x0 * 1000), "y0": round(y0 * 1000),
                           "x1": round(x1 * 1000), "y1": round(y1 * 1000)})
        except Exception:
            pass
        dd = v.GetFirstDisplayDimension5
        while dd is not None:
            try:   # algunas cotas del dibujo no devuelven su dimension por COM: se saltan
                a = dd.GetAnnotation
                pos = a.GetPosition
                dm = dd.GetDimension2(0)
                dims.append({"id": k, "valor": round(dm.SystemValue * 1000, 2), "vista": v.Name,
                             "x": round(pos[0] * 1000, 1), "y": round(pos[1] * 1000, 1), "_dd": dd, "_v": v})
                k += 1
            except Exception:
                pass
            dd = dd.GetNext5
        v = v.GetNextView
    return vistas, dims


def vista_detalle(drw, plan, dims):
    """Detalle de la zona plan[cx,cy,r] de la vista plan[vista], colocado en plan[x,y]; pasa alli las cotas."""
    drw.ActivateView(plan["vista"])
    drw.ClearSelection2(True)
    c = drw.SketchManager.CreateCircleByRadius(plan["cx"] / 1000, plan["cy"] / 1000, 0, plan["r"] / 1000)
    if c is None:
        return None
    drw.ClearSelection2(True)
    c.Select4(False, _sel_data(drw))
    madre = drw.ActiveDrawingView
    a, b = madre.ScaleRatio[0], madre.ScaleRatio[1]
    esc = float(plan.get("escala") or 2)
    det = drw.CreateDetailViewAt4(plan["x"] / 1000, plan["y"] / 1000, 0, 0, a * esc, b, "A", 1,
                                  True, False, False, 5)
    if det is None:
        return None
    # las cotas elegidas salen de la vista madre y se vuelven a insertar solo en el detalle
    elegidas = {d["valor"] for d in dims if d["id"] in set(plan.get("cotas") or [])}
    for d in dims:
        if d["id"] in set(plan.get("cotas") or []):
            drw.ClearSelection2(True)
            d["_dd"].GetAnnotation.Select3(False, _sel_data(drw))
            drw.EditDelete()
    drw.ClearSelection2(True)
    import pythoncom
    from win32com.client import VARIANT
    drw.Extension.SelectByID2(det.Name, "DRAWINGVIEW", 0, 0, 0, False, 0, VARIANT(pythoncom.VT_DISPATCH, None), 0)
    drw.InsertModelAnnotations3(0, 32768, False, False, False, False)
    # en el detalle solo se quedan las cotas elegidas
    dd = det.GetFirstDisplayDimension5
    borrar = []
    while dd is not None:
        if round(dd.GetDimension2(0).SystemValue * 1000, 2) not in elegidas:
            borrar.append(dd)
        dd = dd.GetNext5
    for dd in borrar:
        drw.ClearSelection2(True)
        dd.GetAnnotation.Select3(False, _sel_data(drw))
        drw.EditDelete()
    drw.ClearSelection2(True)
    drw.ForceRebuild3(False)
    return det


def seccion_parcial(drw, plan):
    """Corte parcial (globo) en la vista: rectangulo en mm de hoja y profundidad en mm de pieza. Siempre al final."""
    drw.ActivateView(plan["vista"])
    drw.ClearSelection2(True)
    drw.SketchManager.CreateCornerRectangle(plan["x0"] / 1000, plan["y0"] / 1000, 0,
                                            plan["x1"] / 1000, plan["y1"] / 1000, 0)
    f = drw.CreateBreakOutSection(float(plan["profundidad"]) / 1000)
    drw.ClearSelection2(True)
    drw.ForceRebuild3(False)
    return f


def detalle_y_seccion(drw, pdf, pedir="", permitir=("detalle", "seccion")):
    """Gemini decide si el plano necesita vista de detalle y/o seccion parcial, y se hacen.
    pedir: indicacion del usuario (p.ej. 'detalle de la orejeta y seccion del compartimento')."""
    import pymupdf
    from google.genai import types
    import plano_a_macro
    vistas, dims = vistas_y_cotas(drw)
    png = pdf[:-4] + "_revision.png"
    pymupdf.open(pdf)[0].get_pixmap(dpi=110).save(png)
    lista = [{x: d[x] for x in ("id", "valor", "vista", "x", "y")} for d in dims]
    txt = PLANIFICAR.replace("{{", "{").replace("}}", "}")
    if pedir:
        txt += "\nEL USUARIO PIDE: " + pedir + " (hazlo aunque te parezca opcional)."
    r = plano_a_macro._generar(contents=[
        types.Part.from_bytes(data=open(png, "rb").read(), mime_type="image/png"),
        txt + "\n\nVISTAS:\n" + json.dumps(vistas, ensure_ascii=False) +
        "\n\nCOTAS:\n" + json.dumps(lista, ensure_ascii=False)],
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1))
    os.remove(png)
    plan = gemini_plano.a_json(r.text)
    print("   Gemini: " + str(plan.get("motivo", "")))
    hecho = False
    if "detalle" not in permitir:
        plan["detalle"] = None
    if "seccion" not in permitir:
        plan["seccion_parcial"] = None
    if plan.get("detalle"):
        det = vista_detalle(drw, plan["detalle"], dims)
        print("   Vista de detalle: " + ("hecha" if det is not None else "no se pudo crear"))
        hecho |= det is not None
        if det is not None:   # se guarda ya: la seccion parcial puede tumbar a SolidWorks
            drw.SaveAs3(pdf[:-4] + ".SLDDRW", 0, 1)
            drw.SaveAs3(pdf, 0, 1)
    if plan.get("seccion_parcial"):   # al final: si se hace antes, SolidWorks se cae al recolocar cotas
        try:
            f = seccion_parcial(drw, plan["seccion_parcial"])
        except Exception as e:
            f = None
            print(f"   Sección parcial: error de SolidWorks ({e})")
        print("   Sección parcial: " + ("hecha" if f is not None else "no se pudo crear"))
        hecho |= f is not None
    if hecho:
        drw.SaveAs3(pdf[:-4] + ".SLDDRW", 0, 1)
        drw.SaveAs3(pdf, 0, 1)
    return hecho


def _revisar_hoja(s, pdf):
    """Cotas cerca de su vista y, si hay defectos, Gemini las recoloca. Devuelve los defectos finales."""
    import tareas
    drw = s.OpenDoc6(pdf[:-4] + ".SLDDRW", 3, 1, "", tareas._byref(), tareas._byref())
    if drw is None:
        return None
    try:
        if acercar_a_su_vista(drw):
            drw.SaveAs3(pdf[:-4] + ".SLDDRW", 0, 1)
            drw.SaveAs3(pdf, 0, 1)
        return colocar_con_gemini(drw, pdf)
    finally:
        s.CloseDoc(tareas.val(drw, "GetTitle"))


def exportar_medidas_hoja(s, carpeta_piezas, pdf, piezas):
    """Incrusta en el PDF de una hoja las medidas de cada una de sus piezas (abiertas visibles y cerradas)."""
    import tareas
    for nm in piezas:
        ruta = os.path.join(carpeta_piezas, nm + ".SLDPRT")
        d = s.OpenDoc6(ruta, 1, 1, "", tareas._byref(), tareas._byref())
        if d is None:
            print(f"   {nm}: no se pudo abrir para exportar medidas")
            continue
        try:
            d.Visible = True
            medidas_json(d, pdf)
        except Exception as e:
            print(f"   {nm}: medidas no exportadas ({e})")
        finally:
            s.CloseDoc(tareas.val(d, "GetTitle"))
    print(f"   {os.path.basename(pdf)}: medidas de {', '.join(piezas)} incrustadas")


def planos_carpeta(carpeta, prefijo="", tam_sencilla=80.0, ops_sencilla=8):
    """Planos A4 de todas las piezas de una carpeta, trabajando sobre una COPIA (<carpeta>_planos_<fecha>).
    Piezas sencillas (<= tam_sencilla mm y <= ops_sencilla operaciones) de dos en dos; las demas, una por hoja.
    Devuelve la carpeta con los PDF."""
    import datetime
    import glob
    import shutil
    import sw as swmod
    import tareas
    sys.path.insert(0, LIB)
    carpeta = os.path.normpath(carpeta)
    piezas = sorted(glob.glob(os.path.join(carpeta, "*.SLDPRT")))
    piezas = [p for p in piezas if not os.path.basename(p).lower().startswith(("pieza", "~$"))]
    if not piezas:
        raise SystemExit("No hay piezas .SLDPRT en " + carpeta)
    copia = f"{carpeta}_planos_{datetime.date.today():%Y-%m-%d}"
    k = 2
    while os.path.exists(copia):
        copia = f"{carpeta}_planos_{datetime.date.today():%Y-%m-%d}_{k}"
        k += 1
    os.makedirs(copia)
    for p in piezas:
        shutil.copy2(p, copia)
    print(f"Copia de trabajo (tus piezas no se tocan): {copia}")
    s = tareas._sw()
    sencillas, complejas = [], []
    for p in sorted(glob.glob(os.path.join(copia, "*.SLDPRT"))):
        nm = os.path.splitext(os.path.basename(p))[0]
        d = s.OpenDoc6(p, 1, 1, "", tareas._byref(), tareas._byref())
        if d is None:
            print(f"   {nm}: no se pudo abrir")
            continue
        caja = d.GetPartBox(True)
        tam = max(abs(caja[3] - caja[0]), abs(caja[4] - caja[1]), abs(caja[5] - caja[2])) * 1000
        nops = sum(1 for _, t in swmod.iter_features(d) if t not in (
            "RefPlane", "OriginProfileFeature", "ProfileFeature", "MaterialFolder", "HistoryFolder",
            "SensorFolder", "DocsFolder", "DetailCabinet", "SurfaceBodyFolder", "SolidBodyFolder",
            "EqnFolder", "InkMarkupFolder", "CommentsFolder", "FavoriteFolder", "SelectionSetFolder",
            "CommentsFolder", "BlockFolder", "LiveSectionFolder", "MateReferenceGroupFolder"))
        s.CloseDoc(tareas.val(d, "GetTitle"))
        (sencillas if tam <= tam_sencilla and nops <= ops_sencilla else complejas).append((tam, nm))
        print(f"   {nm}: {tam:.0f} mm, {nops} operaciones -> {'sencilla' if (tam, nm) in sencillas else 'una hoja'}")
    hojas = [(nm, nm.replace("_", " ")[:22], [nm]) for _, nm in complejas]
    sencillas.sort()
    grupo = 3 if len(sencillas) % 3 != 1 else 2   # 3 por hoja; si sobrara una sola, de 2 en 2
    for i in range(0, len(sencillas), grupo):
        par = [nm for _, nm in sencillas[i:i + grupo]]
        hojas.append(("_y_".join(par), " y ".join(n.replace("_", " ") for n in par)[:22], par))
    from swplanos import Proyecto, generar_planos
    prefijo = prefijo or os.path.basename(carpeta)[:3].upper()
    generar_planos(Proyecto(copia, hojas=hojas, prefijo=prefijo), solo=[])
    salida = os.path.join(copia, "planos")
    for fname, _, piezas_hoja in hojas:
        pdf = os.path.join(salida, fname + ".pdf")
        if os.path.exists(pdf):
            print(f"{fname}: defectos finales {_revisar_hoja(s, pdf)}")
            exportar_medidas_hoja(s, copia, pdf, piezas_hoja)
        else:
            print(f"{fname}: SIN PDF")
    for d in list(swmod.docs(s)):   # una sola ventana
        if (tareas.val(d, "GetPathName") or "").lower().startswith(copia.lower()):
            s.CloseDoc(tareas.val(d, "GetTitle"))
    print(f"Planos en: {salida}")
    return salida


def medidas_json(d, pdf, receta=None):
    """Datos para que OTRO PROGRAMA pueda reconstruir la pieza: tamaño, volumen, todas las cotas del modelo y,
    si existe, la receta. Se guardan junto al PDF (<plano>_medidas.json) e INCRUSTADOS en el propio PDF."""
    import datetime
    import pymupdf
    import tareas
    cuerpos = d.GetBodies2(0, True) or []
    caja = d.GetPartBox(True) if cuerpos else [0] * 6
    try:
        material = d.GetMaterialPropertyName2("", "")[1] if hasattr(d, "GetMaterialPropertyName2") else ""
    except Exception:
        material = ""
    datos = {
        "formato": "taller-solidworks/medidas v1",
        "pieza": os.path.splitext(tareas.val(d, "GetTitle"))[0],
        "archivo": tareas.val(d, "GetPathName"),
        "fecha": datetime.date.today().isoformat(),
        "unidades": {"longitud": "mm", "angulo": "grados", "volumen": "cm3"},
        "material": material,
        "solidos": len(cuerpos),
        "volumen": round(d.Extension.CreateMassProperty.Volume * 1e6, 3) if cuerpos else 0,
        "tamano_xyz": [round(abs(caja[k + 3] - caja[k]) * 1000, 2) for k in range(3)],
        "caja_min_xyz": [round(caja[k] * 1000, 2) for k in range(3)],
        "cotas": [],
        "receta": receta,
        "como_reconstruir": ("Si hay 'receta', ejecutarla con plano_a_macro.py (mismo formato que <plano>_receta.json). "
                             "Si no, cada cota es nombre@operacion del modelo de SolidWorks con su valor."),
    }
    for c in cotas_de_pieza(d):
        datos["cotas"].append(c)
    nombre = f"medidas_{datos['pieza']}.json"   # una por pieza (hojas con 2-3 piezas)
    ruta = os.path.join(os.path.dirname(pdf), f"{datos['pieza']}_medidas.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=1, ensure_ascii=False)
    doc = pymupdf.open(pdf)
    if nombre in doc.embfile_names():
        doc.embfile_del(nombre)
    doc.embfile_add(nombre, json.dumps(datos, ensure_ascii=False).encode("utf-8"),
                    filename=nombre, desc="Medidas para reconstruir la pieza " + datos["pieza"])
    doc.save(pdf + ".tmp", garbage=1)
    doc.close()
    os.replace(pdf + ".tmp", pdf)
    return ruta


def leer_medidas_pdf(pdf):
    """Lista de medidas incrustadas por medidas_json (una por pieza); vacia si el PDF no las trae."""
    import pymupdf
    res = []
    doc = pymupdf.open(pdf)
    try:
        for n in doc.embfile_names():
            if n.startswith("medidas"):
                res.append(json.loads(doc.embfile_get(n).decode("utf-8")))
    finally:
        doc.close()
    return res


def cotas_de_pieza(d):
    import sw as swmod
    res = []
    for f, t in swmod.iter_features(d):
        dd = f.GetFirstDisplayDimension
        while dd is not None:
            try:
                dm = dd.GetDimension2(0)
                angulo = dm.GetType == 2   # swDimensionParamTypeDoubleAngular
                valor = round(dm.SystemValue * (57.29578 if angulo else 1000), 3)
                try:
                    cota, op = dm.FullName.split("@")[:2]
                except AttributeError:   # algunas cotas no exponen FullName por enlace tardio
                    cota, op = dm.Name, f.Name
                res.append({"cota": cota, "operacion": op, "valor": valor,
                            "tipo": "angulo" if angulo else "longitud"})
            except Exception:
                pass
            dd = f.GetNextDisplayDimension(dd)
    return res


def elegir(cotas, original=None):
    from google.genai import types
    import plano_a_macro
    partes = []
    if original:
        partes.append(types.Part.from_bytes(data=open(original, "rb").read(), mime_type="application/pdf"))
    txt = PROMPT.replace("{orig}", " y el PLANO ORIGINAL para que lo imites" if original else "")
    txt = txt.replace("{{", "{").replace("}}", "}")
    partes.append(txt + "\n\nCOTAS:\n" + json.dumps(cotas, ensure_ascii=False))
    r = plano_a_macro._generar(contents=partes, config=types.GenerateContentConfig(
        response_mime_type="application/json", temperature=0.1))
    return gemini_plano.a_json(r.text)


def hacer_plano(carpeta, original=None, prefijo="PL"):
    """Guarda la pieza activa en carpeta, pide a Gemini las cotas y genera <carpeta>/planos/<pieza>.pdf."""
    import tareas
    sys.path.insert(0, LIB)
    carpeta = os.path.normpath(carpeta)   # SolidWorks no acepta rutas con "/" al crear vistas
    original = os.path.normpath(original) if original else None
    s = tareas._sw()
    d = tareas.val(s, "ActiveDoc")
    if d is None:
        raise SystemExit("No hay ninguna pieza abierta.")
    if not (d.GetBodies2(0, True) or []):
        # la activa esta vacia (p.ej. Pieza1 tras cerrar un dibujo): si solo hay una pieza con solido, esa
        import sw as swmod
        con_solido = [x for x in list(swmod.docs(s)) if x.GetType == 1 and (x.GetBodies2(0, True) or [])]
        if len(con_solido) != 1:
            raise SystemExit(f"La pieza activa ({tareas.val(d, 'GetTitle')}) está vacía: activa la pieza del plano.")
        s.ActivateDoc3(tareas.val(con_solido[0], "GetTitle"), False, 0, tareas._byref())
        d = tareas.val(s, "ActiveDoc")   # la referencia anterior deja de valer al activar
    # Una pieza abierta por la API (OpenDoc6) queda invisible y SolidWorks la cierra junto con el dibujo
    # que la usa: se hace visible para que siga abierta al terminar.
    d.Visible = True
    nombre = os.path.splitext(tareas.val(d, "GetTitle"))[0]
    if nombre.lower().startswith("pieza") and original:
        nombre = os.path.splitext(os.path.basename(original))[0]
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, nombre + ".SLDPRT")
    if (tareas.val(d, "GetPathName") or "").lower() != ruta.lower():
        if d.SaveAs3(ruta, 0, 1) != 0:
            raise SystemExit("No se pudo guardar la pieza en " + ruta)
    print(f"Pieza guardada: {ruta}")
    cotas = cotas_de_pieza(d)
    print(f"Gemini elige las cotas del plano ({len(cotas)} cotas en el modelo)…")
    sel = elegir(cotas, original)
    ops = [o for o in sel.get("operaciones") or [] if any(c["operacion"] == o for c in cotas)]
    print("   Operaciones acotadas: " + ", ".join(ops))
    for f in sel.get("faltan") or []:
        print("   Falta en el modelo: " + f)
    from swplanos import Proyecto, generar_planos
    generar_planos(Proyecto(carpeta, prefijo=prefijo,
                            hojas=[(nombre, sel.get("titulo") or nombre, [nombre])],
                            info={nombre: (sel.get("titulo") or nombre, sel.get("material") or "",
                                           sel.get("parametros") or [])},
                            cotas={nombre: ops} if ops else {}), solo=[nombre])
    pdf = os.path.join(carpeta, "planos", nombre + ".pdf")
    drw = None
    for doc in list(__import__("sw").docs(s)):
        if (tareas.val(doc, "GetPathName") or "").lower().endswith(".slddrw"):
            drw = doc
    if drw is None and os.path.exists(pdf[:-4] + ".SLDDRW"):
        drw = s.OpenDoc6(pdf[:-4] + ".SLDDRW", 3, 1, "", tareas._byref(), tareas._byref())
    if drw is not None and os.path.exists(pdf):
        n = acercar_a_su_vista(drw)
        if n:
            drw.SaveAs3(pdf, 0, 1)
            print(f"   {n} cotas acercadas a su vista (sus líneas cruzaban otras vistas)")
        print("Gemini revisa la colocación de las cotas…")
        print(f"   Defectos finales: {colocar_con_gemini(drw, pdf)}")
        print("Gemini decide si hace falta vista de detalle o sección parcial…")
        try:
            detalle_y_seccion(drw, pdf)
        except Exception as e:
            print(f"   Detalle/sección no aplicados: {e}")
    # una sola ventana: se cierra el dibujo y se vuelve a la pieza
    for doc in list(__import__("sw").docs(s)):
        if (tareas.val(doc, "GetPathName") or "").lower().endswith(".slddrw"):
            s.CloseDoc(tareas.val(doc, "GetTitle"))
    s.ActivateDoc3(nombre, False, 0, tareas._byref())   # se deja activa la pieza, no la Pieza1 vacia
    if os.path.exists(pdf):   # medidas para que otro programa pueda reconstruir la pieza
        receta = None
        for cand in ([original[:-4] + "_receta.json"] if original else []) + [ruta[:-7] + "_receta.json"]:
            if os.path.exists(cand):
                receta = json.load(open(cand, encoding="utf-8"))
        print("Medidas incrustadas en el PDF: " + medidas_json(tareas.val(s, "ActiveDoc"), pdf, receta))
    print("Plano: " + pdf if os.path.exists(pdf) else "No se ha creado el PDF.")
    return pdf


if __name__ == "__main__":
    hacer_plano(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
