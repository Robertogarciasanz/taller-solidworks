"""Prueba los lectores de recetas con los archivos de ejemplo.

Uso:  py probar_recetas.py [--sin-freecad]

1. Genera la receta de cada STL / PDF y la guarda en freecad\\recetas_prueba\\.
2. Valida su estructura (receta_comun.validar).
3. STL: compara el volumen de la receta (shapely: area x altura de salientes menos cortes, con los
   redondeos estimados en el croquis) con el del STL; error admitido < 2 %.
4. Si existe fc_constructor.py, construye cada receta con freecadcmd y compara volumen y caja.
"""
import os
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
try:
    sys.stdout.reconfigure(errors="replace")
except AttributeError:
    pass

import receta_comun as rc
import receta_pdf
import receta_stl

D = r"C:\Users\xaxaj\OneDrive\Escritorio\diseños 3d"
ARCHIVOS = [
    os.path.join(D, "caja66.STL"),
    os.path.join(D, "brazo_engranaje", "Brazo_engranaje.STL"),
    os.path.join(D, "chapa", "Caja_asas.STL"),
    os.path.join(D, "brazo_engranaje", "planos", "Brazo_engranaje.pdf"),
    os.path.join(D, "caja23.PDF"),
    os.path.join(D, "chapa", "planos", "Tapa_caja.pdf"),
]
SALIDA = os.path.join(AQUI, "recetas_prueba")
# referencias de los PDF: medidas principales del plano (ancho, alto, profundidad; None = no acotada) y, si
# existe, el STL de la misma pieza para comparar el volumen (ida y vuelta)
REF_PDF = {
    "Brazo_engranaje.pdf": dict(medidas=(192.0, 103.0, 20.0), stl=ARCHIVOS[1],
                                texto="148 + R22 + R22 = 192; alto del STL 103; espesor 20 (alma 10)"),
    "caja23.PDF": dict(medidas=(120.0, None, 40.0), stl=ARCHIVOS[0], vol_solo_info=True,
                       texto="120 x 80 (+ orejetas) x 40; caja66.STL es otra version de la misma caja"),
    "Tapa_caja.pdf": dict(medidas=(None, None, None), texto="chapa 1,5 con faldon 15; el plano no trae cotas"),
}
ERR_VOL = 0.02
TOL_CAJA = 0.5          # mm


def probar(ruta, con_freecad):
    fila = dict(archivo=os.path.basename(ruta), ok=True, notas=[])
    t0 = time.time()
    es_stl = ruta.lower().endswith(".stl")
    if es_stl:
        receta, info = receta_stl.receta_desde_stl(ruta)
    else:
        receta, info = receta_pdf.receta_desde_pdf(ruta)
    base = os.path.splitext(os.path.basename(ruta))[0] + ("_stl" if es_stl else "_pdf")
    destino = os.path.join(SALIDA, base + ".receta.json")
    rc.guardar(receta, destino)
    errores = rc.validar(receta)
    fila["ops"] = rc.resumen(receta)
    vol = rc.volumen(receta)
    fila["vol_receta"] = vol
    print("\n== %s  (%.1f s)" % (fila["archivo"], time.time() - t0))
    print("   receta: %s" % destino)
    print("   %s" % fila["ops"])
    print("   variables: %s" % receta["variables"])
    if errores:
        fila["ok"] = False
        for e in errores:
            print("   ERROR de estructura: " + e)
    else:
        print("   estructura correcta")
    if es_stl:
        fila["err_vol"] = abs(vol - info["vol_stl"]) / info["vol_stl"]
        bien = fila["err_vol"] < ERR_VOL
        fila["ok"] &= bien
        print("   volumen STL %.1f mm3, receta %.1f mm3 (sin redondeos %.1f): error %.2f %% %s"
              % (info["vol_stl"], vol, info["vol_sin_redondeos"], fila["err_vol"] * 100, "OK" if bien else "> 2 %"))
        fila["caja_ref"] = info["caja_stl"]
    else:
        print("   exterior %.2f x %.2f mm, %d agujero(s), espesor %g mm (%s), escala: %s"
              % (info["ancho"], info["alto"], info["agujeros"], info["espesor"], info["espesor_de"], info["motivo_escala"]))
        print("   volumen de la receta %.1f mm3" % vol)
        c = rc.caja(receta)
        fila["caja_ref"] = c
        for n in info.get("notas", []):
            print("   nota: %s" % n)
        print("   metodo: %s" % info.get("metodo", "-"))
        for cc, m in info["descartados"][:5]:
            print("   agujero descartado: %s" % m)
    if not con_freecad:
        fila["freecad"] = "no probado"
        return fila
    if not os.path.isfile(rc.CONSTRUCTOR):
        fila["freecad"] = "fc_constructor.py no existe todavia"
        print("   FreeCAD: " + fila["freecad"])
        return fila
    t0 = time.time()
    fcstd = os.path.join(SALIDA, base + ".FCStd")
    res = rc.construir(destino, fcstd, log=lambda l: None)
    print("   FreeCAD (%.1f s): %s" % (time.time() - t0, rc.texto_resultado(res)))
    if not res.get("ok"):
        fila["freecad"] = "FALLO"
        fila["ok"] = False
        return fila
    if not es_stl:
        return comparar_pdf(fila, res, info)
    ref_vol = info["vol_stl"] if es_stl else vol
    ev = abs((res.get("volumen") or 0) - ref_vol) / ref_vol
    caja = res.get("caja") or []
    cr = fila["caja_ref"]
    dc = max(abs(caja[i] - cr[0][i]) for i in range(3)) if len(caja) == 6 else None
    if dc is not None:
        dc = max(dc, max(abs(caja[3 + i] - cr[1][i]) for i in range(3)))
    bien = ev < ERR_VOL and dc is not None and dc < TOL_CAJA and res.get("valido")
    fila["freecad"] = "volumen %+.2f %% respecto al %s, caja +-%.2f mm, %s" % (
        ((res.get("volumen") or 0) - ref_vol) / ref_vol * 100, "STL" if es_stl else "de la receta",
        dc if dc is not None else float("nan"), "OK" if bien else "REVISAR")
    fila["ok"] &= bool(bien)
    print("   comparacion: " + fila["freecad"])
    return fila


def comparar_pdf(fila, res, info):
    """PDF: medidas de la caja de FreeCAD frente a las cotas principales del plano (+-TOL_CAJA) y volumen
    frente al STL de la misma pieza si lo hay."""
    ref = REF_PDF.get(fila["archivo"], {})
    c = res.get("caja") or [0] * 6
    med = [c[3] - c[0], c[4] - c[1], c[5] - c[2]]
    fila["medidas"] = med
    fila["vol_fc"] = res.get("volumen") or 0
    malas = [(m, r) for m, r in zip(med, ref.get("medidas", (None,) * 3)) if r is not None and abs(m - r) > TOL_CAJA]
    bien = bool(res.get("valido")) and not malas and any(r is not None for r in ref.get("medidas", ()))
    txt = "caja %.2f x %.2f x %.2f mm" % tuple(med)
    if ref.get("stl") and os.path.isfile(ref["stl"]):
        import tareas
        from stl_a_macro import volumen as volumen_stl
        v = volumen_stl(tareas._leer_stl(ref["stl"]))
        fila["vol_ref"] = v
        e = (fila["vol_fc"] - v) / v
        fila["err_vol"] = abs(e)
        txt += ", volumen %+.2f %% respecto a %s" % (e * 100, os.path.basename(ref["stl"]))
        if not ref.get("vol_solo_info"):
            bien &= abs(e) < ERR_VOL
    txt += "; plano: %s" % ref.get("texto", "sin referencia")
    if malas:
        txt += "; NO coincide: " + ", ".join("%.2f (cota %.2f)" % mr for mr in malas)
    if not any(r is not None for r in ref.get("medidas", ())):
        fila["freecad"] = txt + " LIMITACION (sin cotas con que comparar)"
        print("   comparacion: " + fila["freecad"])
        return fila
    fila["freecad"] = txt + (" OK" if bien else " REVISAR")
    fila["ok"] &= bien
    print("   comparacion: " + fila["freecad"])
    return fila


def main():
    con_freecad = "--sin-freecad" not in sys.argv
    os.makedirs(SALIDA, exist_ok=True)
    filas = []
    for ruta in ARCHIVOS:
        if not os.path.isfile(ruta):
            print("\n== %s: NO EXISTE" % ruta)
            filas.append(dict(archivo=os.path.basename(ruta), ok=False, ops="(no existe)", freecad="-"))
            continue
        try:
            filas.append(probar(ruta, con_freecad))
        except Exception as e:
            import traceback
            traceback.print_exc()
            filas.append(dict(archivo=os.path.basename(ruta), ok=False, ops="EXCEPCION: %s" % e, freecad="-"))
    print("\n" + "=" * 100)
    print("RESUMEN")
    for f in filas:
        ev = (" | error volumen %.2f %%" % (f["err_vol"] * 100)) if "err_vol" in f else ""
        print(" %s %-26s %s%s | FreeCAD: %s" % ("OK " if f["ok"] else "MAL", f["archivo"], f["ops"], ev, f.get("freecad", "-")))
    return 0 if all(f["ok"] for f in filas) else 1


if __name__ == "__main__":
    sys.exit(main())
