r"""Prueba de ida y vuelta: pieza -> plano PDF (con medidas incrustadas) -> pieza otra vez, y comparar.

Uso:  py ida_y_vuelta.py <pieza.SLDPRT> <carpeta_de_trabajo> [receta.json]
Trabaja sobre una COPIA de la pieza en la carpeta de trabajo. APROBADA si volumen y tamaño difieren < 1 %.
"""
import json
import os
import shutil
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)


def prueba(pieza, carpeta, receta=None):
    import plano_a_macro
    import planos_gemini
    import tareas
    s = tareas._sw()
    carpeta = os.path.normpath(carpeta)
    os.makedirs(carpeta, exist_ok=True)
    nombre = os.path.splitext(os.path.basename(pieza))[0]
    copia = os.path.join(carpeta, nombre + ".SLDPRT")
    shutil.copy2(pieza, copia)
    if receta:   # hacer_plano la busca como <pieza>_receta.json junto a la pieza
        shutil.copy2(receta, os.path.join(carpeta, nombre + "_receta.json"))

    # 1) original
    d = s.OpenDoc6(copia, 1, 1, "", tareas._byref(), tareas._byref())
    d.Visible = True
    s.ActivateDoc3(tareas.val(d, "GetTitle"), False, 0, tareas._byref())
    n0, v0, t0 = plano_a_macro.medidas(tareas.val(s, "ActiveDoc"))
    print(f"ORIGINAL: {n0} sólido(s), {v0:.3f} cm³, {t0} mm")

    # 2) pieza -> PDF
    pdf = planos_gemini.hacer_plano(carpeta)
    med = planos_gemini.leer_medidas_pdf(pdf)
    print(f"PDF: {pdf}  (medidas incrustadas: {[m['pieza'] for m in med]}, "
          f"receta: {'sí' if any(m.get('receta') for m in med) else 'no'})")
    s.CloseDoc(nombre)

    # 3) PDF -> pieza
    plano_a_macro.crear(pdf)
    n1, v1, t1 = plano_a_macro.medidas(tareas.val(s, "ActiveDoc"))
    print(f"RECONSTRUIDA: {n1} sólido(s), {v1:.3f} cm³, {sorted(t1)} mm")

    # 4) comparar (el tamaño se compara ordenado: la reconstruccion puede ir en otros ejes)
    dv = abs(v1 - v0) / v0 * 100 if v0 else 100
    dt = max(abs(a - b) / max(b, 1e-6) * 100 for a, b in zip(sorted(t1), sorted(t0)))
    ok = n1 == n0 and dv < 1 and dt < 1
    print(f"RESULTADO: {'APROBADA' if ok else 'NO COINCIDE'}  (volumen {dv:.2f} %, tamaño {dt:.2f} %)")
    with open(os.path.join(carpeta, "resultado.json"), "w", encoding="utf-8") as f:
        json.dump({"pieza": nombre, "original": [n0, v0, t0], "reconstruida": [n1, v1, t1],
                   "dif_volumen_pct": dv, "dif_tamano_pct": dt, "aprobada": ok}, f, indent=1)
    return ok


if __name__ == "__main__":
    prueba(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
