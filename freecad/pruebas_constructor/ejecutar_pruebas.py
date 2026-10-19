# -*- coding: utf-8 -*-
"""Pruebas de fc_constructor.py. Ejecutar con el Python del sistema:  py ejecutar_pruebas.py
Lanza freecadcmd con cada receta y compara volumen y caja con valores calculados a mano."""
import json, math, os, subprocess, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
CONSTRUCTOR = os.path.join(os.path.dirname(AQUI), "fc_constructor.py")
FREECADCMD = r"C:\Users\xaxaj\AppData\Local\Programs\FreeCAD 1.1\bin\freecadcmd.exe"
SALIDA = os.path.join(AQUI, "salida")
PI = math.pi

# ---- valores calculados a mano
# Placa 100x60x10 - agujero r8 - ranura (30 entre centros, ancho 10) pasante
V_PLACA = 100 * 60 * 10 - PI * 8 ** 2 * 10 - (30 * 10 + PI * 5 ** 2) * 10   # 54203.98


def v_caja(alto):
    # caja 80x50xalto - vaciado 70x40x(alto-5) - agujero r10 en fondo de 5 - 4 redondeos r3 verticales
    perdida_redondeo = (3 ** 2 - PI * 3 ** 2 / 4) * alto * 4
    return 80 * 50 * alto - 70 * 40 * (alto - 5) - PI * 10 ** 2 * 5 - perdida_redondeo


PRUEBAS = [
    ("prueba1_placa_alzado", V_PLACA, [0, 0, 0, 100, 60, 10]),
    # Planta: croquis x->+X, y->-Z, crece hacia +Y
    ("prueba2_placa_planta", V_PLACA, [0, 0, -60, 100, 10, 0]),
    # Lateral: croquis x->-Z, y->+Y, crece hacia +X (desde 5 hasta 15)
    ("prueba2_placa_lateral", V_PLACA, [5, 0, -100, 15, 60, 0]),
    # Alzado con desde=10 hasta=0 (material hacia -Z)
    ("prueba2_placa_alzado_invertido", V_PLACA, [0, 0, 0, 100, 60, 10]),
    ("prueba3_caja", v_caja(30), [0, 0, 0, 80, 50, 30]),
]


def lanzar(script, entorno):
    env = dict(os.environ)
    env.update(entorno)
    p = subprocess.run([FREECADCMD, script], env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    for linea in (p.stdout or "").splitlines():
        if linea.startswith("RESULTADO "):
            return json.loads(linea[len("RESULTADO "):])
    return {"ok": False, "errores": ["sin línea RESULTADO", p.stdout[-2000:], p.stderr[-2000:]]}


def comprobar(nombre, res, v_esp, caja_esp, tol_v=0.05, tol_c=1e-3):
    fallos = []
    if not res.get("ok"):
        fallos.append("ok=false")
    if not res.get("valido"):
        fallos.append("sólido no válido")
    if res.get("errores"):
        fallos.append("errores: %s" % res["errores"])
    v = res.get("volumen", 0)
    if abs(v - v_esp) > tol_v:
        fallos.append("volumen %.4f, esperado %.4f" % (v, v_esp))
    caja = res.get("caja") or []
    if len(caja) != 6 or any(abs(a - b) > tol_c for a, b in zip(caja, caja_esp)):
        fallos.append("caja %s, esperada %s" % (caja, caja_esp))
    estado = "OK   " if not fallos else "FALLO"
    print("%s %-32s volumen %12.4f (esperado %12.4f)  caja %s" % (estado, nombre, v, v_esp, caja))
    for f in fallos:
        print("        - " + f)
    return not fallos


def main():
    os.makedirs(SALIDA, exist_ok=True)
    total = ok = 0
    for nombre, v_esp, caja_esp in PRUEBAS:
        receta = os.path.join(AQUI, nombre + ".receta.json")
        fcstd = os.path.join(SALIDA, nombre + ".FCStd")
        if os.path.exists(fcstd):
            os.remove(fcstd)
        res = lanzar(CONSTRUCTOR, {"FC_RECETA": receta, "FC_SALIDA": fcstd})
        total += 1
        bien = comprobar(nombre, res, v_esp, caja_esp)
        if bien and not os.path.isfile(fcstd):
            print("        - no se guardó %s" % fcstd)
            bien = False
        ok += bien

    # Prueba 3b: cambiar 'alto' en la hoja y recomputar -> la pieza debe regenerarse
    fcstd = os.path.join(SALIDA, "prueba3_caja.FCStd")
    for alto in (40, 20):
        res = lanzar(os.path.join(AQUI, "cambiar_variable.py"),
                     {"FC_ARCHIVO": fcstd, "FC_VAR": "alto", "FC_VALOR": str(alto)})
        total += 1
        ok += comprobar("prueba3_caja alto=%d" % alto, res, v_caja(alto), [0, 0, 0, 80, 50, alto])

    # Prueba de error: receta inexistente -> ok=false sin colgarse
    res = lanzar(CONSTRUCTOR, {"FC_RECETA": os.path.join(AQUI, "no_existe.json"), "FC_SALIDA": ""})
    total += 1
    bien = (res.get("ok") is False and res.get("errores"))
    print("%s %-32s ok=%s errores=%s" % ("OK   " if bien else "FALLO", "receta_inexistente",
                                          res.get("ok"), (res.get("errores") or [""])[0]))
    ok += bool(bien)

    print("\n%d/%d pruebas correctas" % (ok, total))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
