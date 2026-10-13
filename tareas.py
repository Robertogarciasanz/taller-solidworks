"""Tareas automaticas de SolidWorks para la app: lo que antes se hacia a mano, con un boton.

Cada funcion imprime lo que hace (la app lo muestra en el registro) y no pide nada: las rutas
las elige la app con ventanas de Windows y llegan como argumentos.
"""
import math
import os
import shutil
import struct
import zipfile

import pythoncom
import win32com.client as w
import win32com.client.dynamic as dyn


def val(obj, name, *args):
    """Lee una propiedad o llama a un metodo COM, sea cual sea el enlace (tardio o con makepy)."""
    attr = getattr(obj, name)
    if args:
        return attr(*args)
    if callable(attr) and not isinstance(attr, dyn.CDispatch):
        return attr()
    return attr


def _sw():
    # Enlace tardio puro: GetActiveObject devuelve una clase de makepy (si existe en la cache) y esa
    # no acepta los VARIANT por referencia ("int() argument must be ... not 'VARIANT'").
    return dyn.Dispatch("SldWorks.Application")


def _docs(sw):
    d = val(sw, "GetFirstDocument")
    while d is not None:
        yield d
        d = val(d, "GetNext")


def _byref():
    return w.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)


# ------------------------------------------------------------------ estado y guardado
def estado():
    sw = _sw()
    n = 0
    for d in _docs(sw):
        n += 1
        sucio = bool(val(d, "GetSaveFlag"))
        print(("  SIN GUARDAR  " if sucio else "  guardado     ") + str(val(d, "GetTitle")))
    print(f"{n} documentos abiertos.")


def guardar_todo():
    sw = _sw()
    hechos = fallos = 0
    for d in _docs(sw):
        if val(d, "GetSaveFlag"):
            if not val(d, "GetPathName"):
                print("  sin ruta (nunca guardado), se omite:", val(d, "GetTitle"))
                continue
            e, wr = _byref(), _byref()
            ok = d.Save3(1, e, wr)
            if ok:
                hechos += 1
            else:
                fallos += 1
                print("  no se pudo guardar:", val(d, "GetTitle"), "(error", e.value, ")")
    print(f"Guardados {hechos} documentos" + (f"; {fallos} con fallo." if fallos else "."))


def traer_al_frente():
    import sw as swmod
    swmod.cmd_front()


# ------------------------------------------------------------------ copias
def respaldo(carpetas, zip_destino):
    """Zip con las carpetas dadas (sin los temporales ~$ de SolidWorks)."""
    n = 0
    with zipfile.ZipFile(zip_destino, "w", zipfile.ZIP_DEFLATED) as z:
        for ruta in carpetas:
            base = os.path.basename(os.path.normpath(ruta))
            for raiz, _, archivos in os.walk(ruta):
                for f in archivos:
                    p = os.path.join(raiz, f)
                    if f.startswith("~$") or os.path.abspath(p) == os.path.abspath(zip_destino):
                        continue
                    z.write(p, os.path.join(base, os.path.relpath(p, ruta)))
                    n += 1
    with zipfile.ZipFile(zip_destino) as z:
        ok = z.testzip() is None
    print(f"Copia de seguridad: {zip_destino}\n  {n} archivos, {os.path.getsize(zip_destino) / 1e6:.1f} MB, zip {'valido' if ok else 'CON ERRORES'}.")


def conjunto_a_carpeta(destino):
    """Guarda el conjunto activo y lo copia, con todas sus piezas, a una carpeta nueva.
    El conjunto nuevo apunta a las piezas de esa carpeta (las originales no se tocan)."""
    sw = _sw()
    d = val(sw, "ActiveDoc")
    if d is None or val(d, "GetType") != 2:
        print("Abre un ensamblaje en SolidWorks y vuelve a pulsar.")
        return
    nombre = os.path.splitext(os.path.basename(val(d, "GetPathName")))[0]
    e, wr = _byref(), _byref()
    print("Guardando el conjunto original:", d.Save3(1, e, wr))
    origen = val(d, "GetPathName")
    os.makedirs(destino, exist_ok=True)
    nuevo = os.path.join(destino, nombre + "_completo.SLDASM")
    shutil.copy2(origen, nuevo)
    refs = {}
    for c in d.GetComponents(False):
        p = val(c, "GetPathName")
        if p and p not in refs:
            refs[p] = os.path.join(destino, os.path.basename(p))
    for viejo, copia in refs.items():
        shutil.copy2(viejo, copia)
    ok = 0
    for viejo, copia in refs.items():
        if sw.ReplaceReferencedDocument(nuevo, viejo, copia):
            ok += 1
        else:
            print("  no se pudo redirigir:", os.path.basename(viejo))
    print(f"{len(refs)} piezas copiadas, {ok} referencias redirigidas.\n  Conjunto nuevo: {nuevo}")


def limpiar_temporales(carpeta):
    """Borra los archivos ~$ (bloqueos de SolidWorks) que no estan en uso."""
    n = 0
    for raiz, _, archivos in os.walk(carpeta):
        for f in archivos:
            if f.startswith("~$"):
                try:
                    os.remove(os.path.join(raiz, f))
                    n += 1
                except OSError:
                    print("  en uso, se queda:", f)
    print(f"{n} temporales ~$ borrados en {carpeta}.")


# ------------------------------------------------------------------ STL
def stl_a_solido(ruta):
    """Abre un STL como cuerpo solido (LoadFile4; OpenDoc6 falla con error 2097152)."""
    sw = _sw()
    ant_t = sw.GetUserPreferenceIntegerValue(208)
    ant_u = sw.GetUserPreferenceIntegerValue(210)
    sw.SetUserPreferenceIntegerValue(208, 2)   # solido
    sw.SetUserPreferenceIntegerValue(210, 0)   # mm
    try:
        e = _byref()
        nada = w.VARIANT(pythoncom.VT_DISPATCH, None)
        doc = sw.LoadFile4(ruta, "", nada, e)
    finally:
        sw.SetUserPreferenceIntegerValue(208, ant_t)
        sw.SetUserPreferenceIntegerValue(210, ant_u)
    if doc is None:
        print(f"No se pudo importar el STL (error {e.value}).")
        return
    cuerpos = doc.GetBodies2(0, False) or []
    caras = sum(val(b, "GetFaceCount") for b in cuerpos)
    vol = doc.Extension.CreateMassProperty.Volume * 1e6
    print(f"STL convertido a solido: {os.path.basename(ruta)}\n  solidos {len(cuerpos)}, caras {caras}, volumen {vol:.2f} cm3")
    print("  (queda abierto y sin guardar: guardalo tu si lo quieres)")


def _leer_stl(ruta):
    b = open(ruta, "rb").read()
    n = struct.unpack("<I", b[80:84])[0]
    if 84 + 50 * n == len(b):
        tri = []
        for i in range(n):
            v = struct.unpack_from("<9f", b, 84 + 50 * i + 12)
            tri.append(((v[0], v[1], v[2]), (v[3], v[4], v[5]), (v[6], v[7], v[8])))
        return tri
    tri, cur = [], []                     # STL ASCII
    for linea in b.decode("latin-1").splitlines():
        t = linea.split()
        if len(t) == 4 and t[0] == "vertex":
            cur.append(tuple(map(float, t[1:])))
            if len(cur) == 3:
                tri.append(tuple(cur)); cur = []
    return tri


def analizar_stl(ruta):
    """Dimensiones, volumen y cuerpos separados de un STL (sin abrir SolidWorks)."""
    tri = _leer_stl(ruta)
    pts = [p for t in tri for p in t]
    mn = [min(p[i] for p in pts) for i in range(3)]
    mx = [max(p[i] for p in pts) for i in range(3)]

    def vol(ts):
        s = 0.0
        for a, b, c in ts:
            s += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0]))
        return abs(s / 6)

    # cuerpos separados (union por vertices compartidos)
    idx = {}
    par = []

    def vid(p):
        k = (round(p[0], 3), round(p[1], 3), round(p[2], 3))
        if k not in idx:
            idx[k] = len(par); par.append(len(par))
        return idx[k]

    def f(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x

    ids = []
    for t in tri:
        a, b, c = (vid(p) for p in t)
        ids.append(a)
        for o in (b, c):
            ra, ro = f(a), f(o)
            if ra != ro:
                par[ro] = ra
    grupos = {}
    for t, i in zip(tri, ids):
        grupos.setdefault(f(i), []).append(t)
    print(f"{os.path.basename(ruta)}: {len(tri)} triangulos")
    print("  caja: %.2f x %.2f x %.2f mm   (min %s)" % (mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2], [round(v, 2) for v in mn]))
    print(f"  volumen total: {vol(tri) / 1000:.2f} cm3, cuerpos separados: {len(grupos)}")
    for i, ts in enumerate(sorted(grupos.values(), key=lambda g: -vol(g))[:12], 1):
        p = [q for t in ts for q in t]
        d = [max(q[k] for q in p) - min(q[k] for q in p) for k in range(3)]
        print(f"   {i:2d}. {vol(ts) / 1000:8.2f} cm3  caja {d[0]:.1f} x {d[1]:.1f} x {d[2]:.1f}")
    if len(grupos) > 12:
        print(f"   ... y {len(grupos) - 12} cuerpos mas")


# ------------------------------------------------------------------ macros y conexion
def _sw_abierto():
    import subprocess
    salida = subprocess.run(["tasklist", "/FI", "IMAGENAME eq sldworks.exe", "/NH"], capture_output=True,
                            text=True, creationflags=0x08000000).stdout.lower()
    return "sldworks" in salida


def convertir_a_swp(ruta_bas):
    """Crea un .swp que SolidWorks ejecuta a partir de un .bas (junto al original)."""
    import swp_escribir
    destino = swp_escribir.bas_a_swp(ruta_bas)
    print(f"Creado: {destino}")
    print("  Ya se puede ejecutar desde SolidWorks (Herramientas > Macro > Ejecutar) o desde aqui.")


def stl_a_macro(ruta_stl):
    """Analiza un STL y escribe una macro .swp (y .bas) que lo reconstruye en SolidWorks."""
    import stl_vba
    stl_vba.stl_a_swp(ruta_stl)


def ejecutar_macro(ruta, abrir_si_cerrado=False):
    """Ejecuta Sub main de un .swp en el SolidWorks abierto (el modulo se detecta solo)."""
    import sw as swmod
    if ruta.lower().endswith((".bas", ".vba", ".txt")):
        import tempfile
        import time
        import swp_escribir
        carpeta = os.path.join(tempfile.gettempdir(), "TallerSW")
        os.makedirs(carpeta, exist_ok=True)
        nuevo = os.path.join(carpeta, "%s_%d.swp" % (os.path.splitext(os.path.basename(ruta))[0], int(time.time())))
        swp_escribir.bas_a_swp(ruta, nuevo)
        print(f"Convertido a .swp temporal: {os.path.basename(nuevo)}")
        ruta = nuevo
    if not ruta.lower().endswith(".swp"):
        print("Formato no soportado: usa .swp o .bas.")
        return
    mods = swmod.vba_modules(ruta)
    modulo, codigo = swmod.pick_module(mods, "main")
    if modulo is None:
        print("Ningun modulo de la macro tiene Sub main.")
        return
    if not swmod.main_body(codigo):
        print(f"Sub main de '{modulo}' esta vacio: no se ejecuta.")
        return
    if not _sw_abierto():
        if not abrir_si_cerrado:
            print("SolidWorks esta cerrado. Marca «Abrir SolidWorks si está cerrado» o abrelo tu.")
            return
        print("Abriendo SolidWorks (puede tardar 1-2 minutos)...")
    sw = _sw()
    err = _byref()
    print(f"Ejecutando {os.path.basename(ruta)} -> {modulo}.main ...")
    ok = sw.RunMacro2(ruta, modulo, "main", 0, err)
    print("Resultado:", "OK" if ok else "FALLO", "| codigo de error:", err.value)


def conexion():
    """(conectado, texto) para la barra de estado."""
    try:
        import subprocess
        salida = subprocess.run(["tasklist", "/FI", "IMAGENAME eq sldworks.exe", "/NH"], capture_output=True, text=True,
                                creationflags=0x08000000).stdout.lower()
        if "sldworks" not in salida:
            return False, "SolidWorks cerrado"
        sw = _sw()
    except Exception:
        return False, "SolidWorks no responde"
    try:
        n = sum(1 for _ in _docs(sw))
        activo = val(sw, "ActiveDoc")
        nombre = val(activo, "GetTitle") if activo is not None else "ninguno"
        return True, f"SolidWorks conectado  |  {n} documentos  |  activo: {nombre}"
    except Exception:
        return True, "SolidWorks conectado"
