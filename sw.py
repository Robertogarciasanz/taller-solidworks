"""Control de SolidWorks por COM para Claude Code.

Uso:  py sw.py <comando> [argumentos]

  status                          Instancias, documentos abiertos y documento activo
  extract <macro.swp>             Muestra el codigo VBA de la .swp y avisa si main esta vacio
  run <macro.swp> [--module M] [--proc main] [--launch]
                                  Ejecuta la macro en el SolidWorks abierto
  features                        Arbol de operaciones del documento activo (con estado)
  selection                       Lo que el usuario tiene seleccionado ahora mismo
  suppress <op> [<op> ...]        Suprime operaciones por nombre
  unsuppress <op> [<op> ...]      Desactiva la supresion
  bodies                          Solidos, caja envolvente y volumen
  view [iso|front|top|right]      Cambia la vista y ajusta el zoom
  front                           Trae al frente la ventana de SolidWorks (sin abrir otra)

Requiere pywin32 y oletools (py -m pip install pywin32 oletools).
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pythoncom
import win32com.client as w

SKIP_TYPES = {"OriginProfileFeature", "RefPlane", "ProfileFeature", "MaterialFolder",
              "DetailCabinet", "HistoryFolder", "SensorFolder", "DocsFolder",
              "CommentsFolder", "FavoriteFolder", "SelectionSetFolder", "SurfaceBodyFolder",
              "SolidBodyFolder", "EnvFolder", "InkMarkupFolder", "EqnFolder"}


def val(obj, name, *args):
    """Lee una propiedad o llama a un metodo: el enlace tardio de pywin32 mezcla ambos."""
    attr = getattr(obj, name)
    if args:
        return attr(*args)
    # un objeto COM devuelto como propiedad tambien es "callable": no llamarlo
    if callable(attr) and not isinstance(attr, w.CDispatch):
        return attr()
    return attr


def sw_instances():
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq sldworks.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if "sldworks" in l.lower()]


def connect(launch=False):
    try:
        return w.GetActiveObject("SldWorks.Application")
    except pythoncom.com_error:
        if sw_instances():
            # abierto por COM (Dispatch): no esta en la tabla de objetos activos, pero Dispatch
            # se engancha a esa misma instancia
            try:
                return w.Dispatch("SldWorks.Application")
            except pythoncom.com_error:
                sys.exit("SolidWorks esta arrancando o no responde por COM. Espera y repite.")
        if not launch:
            sys.exit("SolidWorks no esta abierto. Repite con --launch para abrirlo.")
        print("Abriendo SolidWorks (puede tardar 1-2 minutos)...")
        sw = w.Dispatch("SldWorks.Application")
        sw.Visible = True
        return sw


def active(sw):
    m = sw.ActiveDoc
    if m is None:
        sys.exit("No hay documento activo en SolidWorks.")
    return m


# ------------------------------------------------------------------ macros
def vba_modules(path):
    from oletools.olevba import VBA_Parser
    p = VBA_Parser(path)
    mods = []
    if p.detect_vba_macros():
        for _, _, name, code in p.extract_macros():
            mods.append((os.path.splitext(name)[0], code or ""))
    p.close()
    return mods


def main_body(code):
    """Lineas de codigo real dentro de Sub main (sin comentarios ni la linea Set swApp)."""
    lines, inside = [], False
    for raw in code.splitlines():
        l = raw.strip()
        if l.lower().startswith("sub main"):
            inside = True
            continue
        if inside and l.lower().startswith("end sub"):
            break
        if inside and l and not l.startswith("'") and "application.sldworks" not in l.lower():
            lines.append(l)
    return lines


def pick_module(mods, proc):
    cands = [(n, c) for n, c in mods
             if n != "ThisLibrary" and f"sub {proc.lower()}" in c.lower()]
    if not cands:
        return None, None
    cands.sort(key=lambda nc: len(main_body(nc[1])), reverse=True)
    return cands[0]


def cmd_extract(path):
    mods = vba_modules(path)
    if not mods:
        sys.exit("No se encontro codigo VBA en " + path)
    for name, code in mods:
        print(f"===== Modulo: {name} ({len(code.splitlines())} lineas) =====")
        print(code.strip() or "(vacio)")
        print()
    name, code = pick_module(mods, "main")
    if name is None:
        print("AVISO: ningun modulo tiene Sub main.")
    elif not main_body(code):
        print(f"AVISO: Sub main de '{name}' esta VACIO: la macro no hara nada.")
    else:
        print(f"OK: modulo de entrada '{name}', main con {len(main_body(code))} lineas.")


def cmd_run(path, module=None, proc="main", launch=False):
    path = os.path.abspath(path)
    if not os.path.exists(path):
        sys.exit("No existe: " + path)
    if path.lower().endswith(".bas"):
        sys.exit("Un .bas no se puede ejecutar directamente: hay que pegarlo en una macro .swp "
                 "(ver SKILL.md, apartado 'Archivos .bas').")
    if module is None:
        mods = vba_modules(path)
        module, code = pick_module(mods, proc)
        if module is None:
            sys.exit(f"Ningun modulo de {path} tiene Sub {proc}.")
        if not main_body(code):
            sys.exit(f"Sub {proc} de '{module}' esta vacio: la macro no haria nada. No se ejecuta.")
    sw = connect(launch)
    before = {val(d, "GetTitle") for d in docs(sw)}
    err = w.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    print(f"Ejecutando {os.path.basename(path)} -> {module}.{proc} ...", flush=True)
    ok = sw.RunMacro2(path, module, proc, 0, err)
    print("Resultado:", "OK" if ok else "FALLO", "| codigo de error:", err.value)
    new = [t for t in (val(d, "GetTitle") for d in docs(sw)) if t not in before]
    if new:
        print("Documentos nuevos:", ", ".join(new))
    if sw.ActiveDoc is not None:
        cmd_features(sw, brief=True)


# ------------------------------------------------------------------ modelo
def docs(sw):
    d = sw.GetFirstDocument
    while d is not None:
        yield d
        d = d.GetNext


def cmd_status():
    print("Procesos sldworks:", len(sw_instances()))
    sw = connect()
    print("Version:", val(sw, "RevisionNumber"))
    tipos = {1: "pieza", 2: "ensamblaje", 3: "plano"}
    for d in docs(sw):
        print(f"  - {val(d, 'GetTitle')} ({tipos.get(val(d, 'GetType'), '?')})  {val(d, 'GetPathName') or '(sin guardar)'}")
    m = sw.ActiveDoc
    print("Activo:", val(m, "GetTitle") if m else None)


def iter_features(m):
    f = m.FirstFeature
    while f is not None:
        t = val(f, "GetTypeName2")
        if t not in SKIP_TYPES and not t.endswith("Folder"):
            yield f, t
        f = f.GetNextFeature


def cmd_features(sw=None, brief=False):
    sw = sw or connect()
    m = active(sw)
    print("Documento:", val(m, "GetTitle"))
    for f, t in iter_features(m):
        estado = "SUPRIMIDA" if val(f, "IsSuppressed") else ""
        print(f"  {val(f, 'Name'):<30} [{t}] {estado}")
    cmd_bodies(sw)


def cmd_bodies(sw=None):
    sw = sw or connect()
    m = active(sw)
    if val(m, "GetType") != 1:
        return
    b = m.GetBodies2(0, True)
    n = len(b) if b else 0
    print("Solidos:", n, "" if n == 1 else "<-- REVISAR")
    for i, body in enumerate(b or []):
        bx = val(body, "GetBodyBox")
        vol = val(body, "GetMassProperties", 1)[3] * 1e6
        dims = [round((bx[k + 3] - bx[k]) * 1000, 2) for k in range(3)]
        print(f"  solido {i + 1}: {dims[0]} x {dims[1]} x {dims[2]} mm, volumen {vol:.2f} cm3")


SEL_TYPES = {1: "arista", 2: "cara", 3: "vertice", 4: "plano", 22: "operacion",
             9: "croquis", 11: "segmento croquis", 14: "cota", 20: "componente"}


def cmd_selection():
    sw = connect()
    m = active(sw)
    sm = m.SelectionManager
    n = sm.GetSelectedObjectCount2(-1)
    if not n:
        print("No hay nada seleccionado en SolidWorks.")
        return
    for i in range(1, n + 1):
        t = sm.GetSelectedObjectType3(i, -1)
        o = sm.GetSelectedObject6(i, -1)
        feat = ""
        for getter in ("GetFeature", "Name"):
            try:
                r = val(o, getter)
                feat = r if isinstance(r, str) else val(r, "Name")
                if feat:
                    break
            except Exception:
                pass
        p = sm.GetSelectionPoint2(i, -1)
        pt = [round(v * 1000, 2) for v in p] if p else None
        print(f"{i}: {SEL_TYPES.get(t, 'tipo ' + str(t))}  operacion='{feat}'  punto(mm)={pt}")


def set_suppress(names, suppress):
    sw = connect()
    m = active(sw)
    for nm in names:
        f = m.FeatureByName(nm)
        if f is None:
            print(f"  {nm}: no existe")
            continue
        m.ClearSelection2(True)
        f.Select2(False, 0)
        val(m, "EditSuppress2" if suppress else "EditUnsuppress2")
        m.ClearSelection2(True)
        print(f"  {nm}: {'suprimida' if val(m.FeatureByName(nm), 'IsSuppressed') else 'activa'}")
    m.ForceRebuild3(False)
    cmd_bodies(sw)


def cmd_front():
    """Trae al frente la ventana de SolidWorks ya abierta (sin lanzar otra instancia)."""
    import win32gui, win32con, win32process, subprocess
    pids = {int(l.split('","')[1]) for l in sw_instances()}
    found = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and "SOLIDWORKS" in win32gui.GetWindowText(h):
            if win32process.GetWindowThreadProcessId(h)[1] in pids:
                found.append(h)
    win32gui.EnumWindows(cb, None)
    if not found:
        sys.exit("No hay ventana de SolidWorks visible.")
    win32gui.ShowWindow(found[0], win32con.SW_MAXIMIZE)
    try:
        win32gui.SetForegroundWindow(found[0])
    except Exception:
        pass
    print("Ventana al frente:", win32gui.GetWindowText(found[0]))


def cmd_view(name="iso"):
    sw = connect()
    m = active(sw)
    views = {"iso": "*Isometric", "front": "*Front", "top": "*Top", "right": "*Right"}
    m.ShowNamedView2(views.get(name, name), -1)
    m.ViewZoomtofit2()


# ------------------------------------------------------------------ cli
def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    opts = {}
    pos = []
    i = 0
    while i < len(rest):
        if rest[i].startswith("--"):
            key = rest[i][2:]
            if key == "launch":
                opts[key] = True
            else:
                opts[key] = rest[i + 1]
                i += 1
        else:
            pos.append(rest[i])
        i += 1
    if cmd == "status":
        cmd_status()
    elif cmd == "extract":
        cmd_extract(pos[0])
    elif cmd == "run":
        cmd_run(pos[0], opts.get("module"), opts.get("proc", "main"), opts.get("launch", False))
    elif cmd == "features":
        cmd_features()
    elif cmd == "bodies":
        cmd_bodies()
    elif cmd == "selection":
        cmd_selection()
    elif cmd == "suppress":
        set_suppress(pos, True)
    elif cmd == "unsuppress":
        set_suppress(pos, False)
    elif cmd == "front":
        cmd_front()
    elif cmd == "view":
        cmd_view(pos[0] if pos else "iso")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
