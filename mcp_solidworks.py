r"""Servidor MCP de SolidWorks 2020 (Taller SolidWorks).

Da a Claude Code (o a cualquier cliente MCP: Gemini CLI, Antigravity...) herramientas para manejar el SolidWorks
abierto por COM: estado, ejecutar macros, plano PDF -> pieza (con Gemini), medir, capturas, planos A4 en PDF.

Registro en Claude Code (una vez):
    claude mcp add solidworks --scope user -- py "C:\SOLIDWORKS Data\taller-solidworks\mcp_solidworks.py"
"""
import contextlib
import io
import os
import sys
import tempfile
import traceback

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

from mcp.server.mcpserver import Image, MCPServer  # noqa: E402

mcp = MCPServer(
    "solidworks",
    instructions=(
        "Maneja el SolidWorks 2020 abierto en el PC del usuario. Reglas del usuario: una pieza cada vez "
        "(cerrar la anterior antes de probar otra), redondeos siempre al final, no guardar las piezas "
        "descartadas, y preguntarle tras cada modelo para que lo revise. Comprueba siempre con 'medir' "
        "(1 sólido, volumen y tamaño) y con 'captura' antes de dar algo por bueno."),
)


def _ejecutar(fn, *args, **kw):
    """Ejecuta fn con COM inicializado y devuelve (resultado, texto impreso). La salida estandar es del
    protocolo MCP: todo lo que imprimen los modulos del Taller se recoge aqui."""
    import pythoncom
    pythoncom.CoInitialize()
    buf = io.StringIO()
    res = None
    try:
        with contextlib.redirect_stdout(buf):
            res = fn(*args, **kw)
    except SystemExit as e:
        buf.write(f"\nPARADO: {e.code}")
    except Exception as e:
        buf.write(f"\nERROR: {type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")
    return res, buf.getvalue().strip()


def _sw():
    import tareas
    return tareas._sw()


def _docs():
    import sw
    import tareas
    s = _sw()
    return [(tareas.val(d, "GetTitle"), tareas.val(d, "GetPathName") or "", d) for d in list(sw.docs(s))]


@mcp.tool()
def estado() -> str:
    """Documentos abiertos en SolidWorks (título, ruta o 'sin guardar') y cuál es el activo."""
    def f():
        import tareas
        s = _sw()
        act = tareas.val(s, "ActiveDoc")
        t_act = tareas.val(act, "GetTitle") if act is not None else None
        lineas = [f"{'* ' if t == t_act else '  '}{t}  |  {p or '(sin guardar)'}" for t, p, _ in _docs()]
        return "\n".join(lineas) or "SolidWorks no tiene documentos abiertos."
    r, txt = _ejecutar(f)
    return (r or "") + ("\n" + txt if txt else "")


@mcp.tool()
def medir() -> str:
    """Pieza activa: número de sólidos, volumen (cm³), tamaño X×Y×Z (mm), operaciones y avisos de la macro."""
    def f():
        import plano_a_macro
        import tareas
        d = tareas.val(_sw(), "ActiveDoc")
        if d is None:
            return "No hay documento activo."
        n, v, tam = plano_a_macro.medidas(d)
        return f"{n} sólido(s), {v:.2f} cm³, tamaño {tam} mm\n" + plano_a_macro.comprobar()
    r, txt = _ejecutar(f)
    return (r or "") + ("\n" + txt if txt else "")


@mcp.tool()
def captura(vista: str = "iso") -> Image:
    """Imagen de la pieza activa. vista: iso, frente, planta o lateral."""
    vistas = {"iso": ("*Isometric", 7), "frente": ("*Front", 1), "planta": ("*Top", 5), "lateral": ("*Right", 4)}
    nombre, cod = vistas.get(vista.lower(), vistas["iso"])
    ruta = os.path.join(tempfile.gettempdir(), f"sw_captura_{vista}.png")

    def f():
        import tareas
        from PIL import Image as PImage
        d = tareas.val(_sw(), "ActiveDoc")
        if d is None:
            raise SystemExit("No hay documento activo.")
        d.ShowNamedView2(nombre, cod)
        d.ViewZoomtofit2()
        bmp = ruta[:-4] + ".bmp"
        d.SaveBMP(bmp, 1000, 700)
        PImage.open(bmp).save(ruta)
        os.remove(bmp)
    _, txt = _ejecutar(f)
    if not os.path.exists(ruta) or txt.startswith(("PARADO", "ERROR")):
        raise RuntimeError(txt or "No se pudo hacer la captura.")
    return Image(path=ruta)


@mcp.tool()
def abrir(ruta: str) -> str:
    """Abre una pieza, ensamblaje o dibujo CON ventana y lo deja activo. (Abierto por la API sin hacerlo visible,
    SolidWorks lo cerraría solo al cerrar el dibujo que lo usa.)"""
    def f():
        import tareas
        r = os.path.normpath(ruta)
        tipo = {".sldprt": 1, ".sldasm": 2, ".slddrw": 3}.get(os.path.splitext(r)[1].lower())
        if tipo is None:
            raise SystemExit("Solo .SLDPRT, .SLDASM o .SLDDRW")
        s = _sw()
        d = s.OpenDoc6(r, tipo, 1, "", tareas._byref(), tareas._byref())
        if d is None:
            raise SystemExit("No se pudo abrir " + r)
        d.Visible = True
        s.ActivateDoc3(tareas.val(d, "GetTitle"), False, 0, tareas._byref())
        return "Abierto: " + tareas.val(d, "GetTitle")
    r, txt = _ejecutar(f)
    return (r or "") + ("\n" + txt if txt else "")


@mcp.tool()
def ejecutar_macro(ruta: str) -> str:
    """Ejecuta Sub main de una macro .swp (o .bas, que se convierte) en el SolidWorks abierto y mide el resultado."""
    def f():
        import plano_a_macro
        import tareas
        tareas.ejecutar_macro(ruta)
        print(plano_a_macro.comprobar())
    _, txt = _ejecutar(f)
    return txt


@mcp.tool()
def plano_a_pieza(plano: str, rondas: int = 1, original: str = "", misma_receta: bool = False) -> str:
    """Plano PDF o foto acotada -> Gemini lee las cotas -> macro VBA -> SolidWorks crea la pieza y se comprueba.
    rondas > 1: Gemini revisa capturas y corrige. original: .SLDPRT de referencia para comparar volumen y tamaño.
    misma_receta: reutiliza <plano>_receta.json sin volver a llamar a Gemini (para corregir la receta a mano).
    Deja junto al plano <plano>_receta.json, _macro.bas y _macro.swp."""
    def f():
        import plano_a_macro
        plano_a_macro.crear(plano, rondas=rondas, original=original or None, misma_receta=misma_receta)
    _, txt = _ejecutar(f)
    return txt


@mcp.tool()
def generar_plano(carpeta: str, plano_original: str = "") -> str:
    """Plano A4 de la pieza activa: la guarda en carpeta, Gemini elige qué cotas mostrar (imitando plano_original
    si se da) y SolidWorks dibuja alzado, vistas e isométrica con cotas exactas del modelo -> carpeta/planos/*.pdf."""
    def f():
        import planos_gemini
        return planos_gemini.hacer_plano(carpeta, plano_original or None)
    r, txt = _ejecutar(f)
    return txt + (f"\nPDF: {r}" if r else "")


@mcp.tool()
def cerrar_sin_guardar(titulo: str = "") -> str:
    """Cierra SIN guardar una pieza que nunca se ha guardado (por defecto la activa). No cierra documentos que ya
    tienen archivo, para no perder trabajo del usuario."""
    def f():
        for t, p, _ in _docs():
            if (titulo and t != titulo) or p:
                continue
            if not titulo:
                import tareas
                act = tareas.val(_sw(), "ActiveDoc")
                if act is None or tareas.val(act, "GetTitle") != t:
                    continue
            _sw().CloseDoc(t)
            return f"Cerrado sin guardar: {t}"
        return "No hay ninguna pieza sin guardar con ese nombre (las guardadas no se cierran desde aquí)."
    r, txt = _ejecutar(f)
    return (r or "") + ("\n" + txt if txt else "")


@mcp.tool()
def traer_al_frente() -> str:
    """Pone la ventana de SolidWorks delante."""
    def f():
        import sw
        sw.cmd_front()
    _, txt = _ejecutar(f)
    return txt


if __name__ == "__main__":
    mcp.run("stdio")
