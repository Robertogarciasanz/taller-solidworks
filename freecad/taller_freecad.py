"""Taller FreeCAD: STL o plano PDF -> receta de pieza -> pieza de FreeCAD (.FCStd), en una sola ventana.

Mismo aspecto que taller_solidworks.py, pero sin COM ni SolidWorks: cada pieza se describe con una
receta (<nombre>.receta.json, ver RECETA.md) que construye fc_constructor.py dentro de freecadcmd.

Uso:  py taller_freecad.py   (o "Taller FreeCAD.bat")
"""
import io
import json
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

import customtkinter as ctk

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import receta_comun as rc          # pone el directorio padre (app de SolidWorks) en sys.path

# Reutiliza el asistente de roles del PDF y la tabla de cotas de la app de SolidWorks (sin modificarla).
import taller_solidworks as tsw
from taller_solidworks import ACENTO, ACENTO_H, BARRA, FONDO, GRIS, PANEL, ROJO, VERDE

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")
AMARILLO = "#d29922"
GRIS_BOTON, GRIS_BOTON_H = "#30363d", "#3d444d"


def _botones(w):
    """Todos los CTkButton dentro de un widget (para cambiar los textos de las ventanas reutilizadas)."""
    for h in w.winfo_children():
        if isinstance(h, ctk.CTkButton):
            yield h
        yield from _botones(h)


def _casillas(w):
    for h in w.winfo_children():
        if isinstance(h, ctk.CTkCheckBox):
            yield h
        yield from _casillas(h)


class _StdoutPorHilo(io.TextIOBase):
    """sys.stdout que manda lo que imprime cada hilo de tarea a su propia salida (redirect_stdout cambia
    sys.stdout para todo el proceso y, con dos tareas a la vez, una se quedaba con la salida de la otra)."""

    def __init__(self, original):
        self.original = original
        self.local = threading.local()

    def _destino(self):
        return getattr(self.local, "salida", None) or self.original

    def write(self, txt):
        return self._destino().write(txt)

    def flush(self):
        d = self._destino()
        if hasattr(d, "flush"):
            d.flush()


_STDOUT = _StdoutPorHilo(sys.stdout)
sys.stdout = _STDOUT


class TallerFreeCAD(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Taller FreeCAD")
        self.geometry("1180x690+40+30")
        self.minsize(940, 580)
        self.configure(fg_color=FONDO)
        self.en_curso = {}
        self.receta_actual = None        # ruta del .receta.json que se ve en el panel
        self.ultimo_fcstd = None
        self.ultima_carpeta = None
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._lateral()
        self._principal()
        self._estado_barra()
        self._pintar_estado()

    # ------------------------------------------------------------ interfaz
    def _boton_lateral(self, padre, texto, cmd):
        b = ctk.CTkButton(padre, text=texto, command=cmd, anchor="w", height=34, corner_radius=8,
                          fg_color="transparent", hover_color="#262d36", text_color="#e6edf3",
                          font=ctk.CTkFont(size=13))
        b.pack(fill="x", padx=10, pady=1)
        return b

    def _seccion(self, padre, titulo):
        ctk.CTkLabel(padre, text=titulo.upper(), text_color=GRIS, anchor="w",
                     font=ctk.CTkFont(size=11, weight="bold")).pack(fill="x", padx=18, pady=(16, 4))

    def _lateral(self):
        lat = ctk.CTkScrollableFrame(self, width=250, corner_radius=0, fg_color=PANEL)
        lat.grid(row=0, column=0, sticky="nsw")
        ctk.CTkLabel(lat, text="Taller FreeCAD", font=ctk.CTkFont(size=22, weight="bold"),
                     anchor="w").pack(fill="x", padx=18, pady=(16, 0))
        ctk.CTkLabel(lat, text="recetas de pieza y copias", text_color=GRIS, anchor="w").pack(fill="x", padx=18)

        self._seccion(lat, "Mallas y planos")
        self._boton_lateral(lat, "🔍  STL → pieza FreeCAD…", self.t_stl)
        self._boton_lateral(lat, "📐  Plano PDF → pieza (automático)…", self.t_pdf_auto)
        self._boton_lateral(lat, "🧭  Plano PDF → pieza (asistente)…", self.t_pdf)
        self._boton_lateral(lat, "🔢  Cotas del PDF → variables…", self.t_cotas)

        self._seccion(lat, "Recetas y piezas")
        self._boton_lateral(lat, "📄  Abrir receta…", self.abrir_receta)
        self._boton_lateral(lat, "🧱  Construir receta en FreeCAD", self.construir_actual)
        self._boton_lateral(lat, "🪟  Abrir en FreeCAD…", self.abrir_en_freecad)

        self._seccion(lat, "Copias")
        self._boton_lateral(lat, "🗜️  Copia de seguridad (zip)…", self.t_respaldo)

    def _principal(self):
        cen = ctk.CTkFrame(self, fg_color="transparent")
        cen.grid(row=0, column=1, sticky="nsew", padx=14, pady=(14, 6))
        cen.grid_columnconfigure(0, weight=1)
        cen.grid_rowconfigure(0, weight=3)
        cen.grid_rowconfigure(1, weight=2)

        der = ctk.CTkFrame(cen, corner_radius=12, fg_color=PANEL)
        der.grid(row=0, column=0, sticky="nsew")
        der.grid_columnconfigure(0, weight=1)
        der.grid_rowconfigure(2, weight=1)
        cab = ctk.CTkFrame(der, fg_color="transparent")
        cab.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        self.titulo = ctk.CTkLabel(cab, text="Receta", font=ctk.CTkFont(size=15, weight="bold"), anchor="w")
        self.titulo.pack(side="left")
        self.resumen = ctk.CTkLabel(cab, text="", text_color=GRIS, anchor="e")
        self.resumen.pack(side="right")
        fila = ctk.CTkFrame(der, fg_color="transparent")
        fila.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 4))
        for txt, cmd, color, hov in (("🧱 Construir en FreeCAD", self.construir_actual, ACENTO, ACENTO_H),
                                     ("🪟 Abrir en FreeCAD", self.abrir_en_freecad, GRIS_BOTON, GRIS_BOTON_H),
                                     ("💾 Guardar receta", self.guardar_receta, GRIS_BOTON, GRIS_BOTON_H),
                                     ("✔ Comprobar", self.comprobar_receta, GRIS_BOTON, GRIS_BOTON_H),
                                     ("👁 Recargar", self.recargar_receta, GRIS_BOTON, GRIS_BOTON_H)):
            b = ctk.CTkButton(fila, text=txt, command=cmd, width=10, height=30, fg_color=color, hover_color=hov,
                              font=ctk.CTkFont(size=12), corner_radius=6)
            b.pack(side="left", padx=(0, 5))
            if color == ACENTO:
                self.btn_construir = b
        self.codigo = ctk.CTkTextbox(der, font=("Consolas", 12), fg_color=BARRA, wrap="none", undo=True,
                                     corner_radius=8, border_width=0)
        self.codigo.grid(row=2, column=0, sticky="nsew", padx=12, pady=(4, 12))
        self.codigo.insert("1.0", "Elige «STL → pieza FreeCAD…» o «Plano PDF → pieza FreeCAD…».\n\n"
                                  "La receta (<nombre>.receta.json) se guarda junto al archivo de origen y la pieza\n"
                                  "(<nombre>.FCStd) también. Puedes editar la receta aquí, guardarla y construirla.")

        reg = ctk.CTkFrame(cen, corner_radius=12, fg_color=PANEL)
        reg.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        reg.grid_columnconfigure(0, weight=1)
        reg.grid_rowconfigure(1, weight=1)
        cab2 = ctk.CTkFrame(reg, fg_color="transparent")
        cab2.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        ctk.CTkLabel(cab2, text="Registro", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkButton(cab2, text="Limpiar", width=70, height=24, fg_color=GRIS_BOTON, hover_color=GRIS_BOTON_H,
                      command=lambda: self.log.delete("1.0", "end")).pack(side="right")
        self.log = ctk.CTkTextbox(reg, font=("Consolas", 12), fg_color=BARRA, corner_radius=8, height=150)
        self.log.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 12))
        self.log.tag_config("tarea", foreground="#58a6ff")
        self.log.tag_config("error", foreground=ROJO)
        self.log.tag_config("ok", foreground=VERDE)

    def _estado_barra(self):
        barra = ctk.CTkFrame(self, height=30, corner_radius=0, fg_color=BARRA)
        barra.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.punto = ctk.CTkLabel(barra, text="●", text_color=GRIS, width=20)
        self.punto.pack(side="left", padx=(14, 4), pady=4)
        self.estado_txt = ctk.CTkLabel(barra, text="", text_color=GRIS, anchor="w")
        self.estado_txt.pack(side="left")

    def _pintar_estado(self):
        if self.en_curso:
            self.punto.configure(text_color=AMARILLO)
            self.estado_txt.configure(text="⏳ en curso: " + ", ".join(self.en_curso), text_color=AMARILLO)
            return
        falta = []
        if not os.path.isfile(rc.FREECADCMD):
            falta.append("no encuentro freecadcmd.exe en " + rc.FREECAD_BIN)
        if not os.path.isfile(rc.CONSTRUCTOR):
            falta.append("falta fc_constructor.py")
        if falta:
            self.punto.configure(text_color=ROJO)
            self.estado_txt.configure(text="; ".join(falta), text_color=GRIS)
        else:
            self.punto.configure(text_color=VERDE)
            self.estado_txt.configure(text="FreeCAD 1.1 listo (freecadcmd + fc_constructor.py)", text_color="#c9d1d9")

    # ------------------------------------------------------------ registro y tareas
    def report_callback_exception(self, exc, valor, tb):
        import traceback
        self.escribe(f"✖ error interno: {valor}", "error")
        self.escribe("".join(traceback.format_exception(exc, valor, tb))[-600:], "error")

    def escribe(self, txt, tag=None):
        self.log.insert("end", txt + "\n", tag)
        self.log.see("end")

    def registro(self, txt, tag=None):
        """escribe() que se puede llamar desde cualquier hilo."""
        self.after(0, self.escribe, txt, tag)

    def tarea(self, nombre, fn, *args):
        """Ejecuta fn(*args) en un hilo; lo que imprima sale en el registro."""
        if nombre in self.en_curso:
            self.escribe(f"⚠ «{nombre}» ya se está ejecutando: espera a que termine.", "error")
            return
        self.en_curso[nombre] = True
        self.escribe(f"▶ {nombre}  (en curso…)", "tarea")
        self._pintar_estado()
        self.btn_construir.configure(state="disabled")
        app = self

        class Salida(io.TextIOBase):
            def __init__(self):
                self.resto = ""

            def write(self, txt):
                self.resto += txt
                while "\n" in self.resto:
                    linea, self.resto = self.resto.split("\n", 1)
                    app.registro(linea)
                return len(txt)

            def flush(self):
                pass

        def run():
            t0 = time.time()
            salida = Salida()
            tag, msg = "ok", ""
            try:
                _STDOUT.local.salida = salida
                try:
                    r = fn(*args)
                finally:
                    _STDOUT.local.salida = None
                if r is False:
                    tag, msg = "error", "terminó con errores (mira arriba)"
            except Exception as e:
                import traceback
                tag, msg = "error", f"{type(e).__name__}: {e}"
                app.registro(traceback.format_exc()[-800:], "error")
            if salida.resto.strip():
                app.registro(salida.resto)
            texto = (f"✔ {nombre} terminada ({time.time() - t0:.1f} s)" if tag == "ok" else f"✖ {nombre}: {msg}")
            app.after(0, app._fin, nombre, texto, tag)
        threading.Thread(target=run, daemon=True).start()

    def _fin(self, nombre, texto, tag):
        self.en_curso.pop(nombre, None)
        self.escribe(texto, tag)
        if not self.en_curso:
            self.btn_construir.configure(state="normal")
        self._pintar_estado()

    # ------------------------------------------------------------ panel de la receta
    def mostrar_receta(self, ruta):
        """Carga el .receta.json en el panel (llamar desde el hilo de la interfaz)."""
        self.receta_actual = ruta
        try:
            with open(ruta, encoding="utf-8") as f:
                txt = f.read()
            receta = json.loads(txt)
            self.resumen.configure(text=rc.resumen(receta))
        except (OSError, ValueError, KeyError, IndexError) as e:
            txt = f"Error leyendo la receta: {e}"
            self.resumen.configure(text="")
        self.codigo.delete("1.0", "end")
        self.codigo.insert("1.0", txt)
        nombre = os.path.basename(ruta)
        self.titulo.configure(text=nombre if len(nombre) < 40 else nombre[:37] + "…")

    def _receta_del_panel(self):
        try:
            return json.loads(self.codigo.get("1.0", "end-1c"))
        except ValueError as e:
            messagebox.showwarning("Receta", f"El texto no es un JSON válido:\n{e}", parent=self)
            return None

    def abrir_receta(self):
        p = filedialog.askopenfilename(title="Receta de pieza", filetypes=[("Receta", "*.receta.json *.json")],
                                       initialdir=self.ultima_carpeta)
        if p:
            p = os.path.normpath(p)
            self.ultima_carpeta = os.path.dirname(p)
            self.mostrar_receta(p)
            self.comprobar_receta()

    def recargar_receta(self):
        if self.receta_actual:
            self.mostrar_receta(self.receta_actual)
            self.escribe("Receta recargada desde el archivo.", "ok")

    def comprobar_receta(self):
        receta = self._receta_del_panel()
        if receta is None:
            return None
        errores = rc.validar(receta)
        if errores:
            self.escribe(f"✖ La receta tiene {len(errores)} error(es):", "error")
            for e in errores[:12]:
                self.escribe("   · " + e, "error")
            return None
        try:
            vol = rc.volumen(receta)
            self.escribe(f"✔ Receta correcta: {rc.resumen(receta)}; volumen estimado {vol:.1f} mm³.", "ok")
        except Exception as e:
            self.escribe(f"✔ Receta correcta ({rc.resumen(receta)}); volumen no calculado: {e}", "ok")
        return receta

    def guardar_receta(self):
        receta = self._receta_del_panel()
        if receta is None:
            return
        p = self.receta_actual
        if not p:
            p = filedialog.asksaveasfilename(title="Guardar receta", defaultextension=".receta.json",
                                             filetypes=[("Receta", "*.receta.json")], initialdir=self.ultima_carpeta)
            if not p:
                return
            p = os.path.normpath(p)
        rc.guardar(receta, p)
        self.mostrar_receta(p)
        self.escribe("Receta guardada: " + p, "ok")

    # ------------------------------------------------------------ construir y abrir
    def construir_actual(self):
        if not self.receta_actual:
            messagebox.showinfo("Taller FreeCAD", "Abre o genera primero una receta.", parent=self)
            return
        receta = self.comprobar_receta()
        if receta is None:
            return
        guardada = None
        try:
            with open(self.receta_actual, encoding="utf-8") as f:
                guardada = json.load(f)
        except (OSError, ValueError):
            pass
        if guardada != receta:
            if not messagebox.askyesno("Taller FreeCAD", "La receta del panel tiene cambios sin guardar.\n"
                                       "¿Guardarlos y construir?", parent=self):
                return
            rc.guardar(receta, self.receta_actual)
        ruta = self.receta_actual
        salida = self._salida_de(ruta)
        self.tarea("construir " + os.path.basename(salida), self._construir, ruta, salida, None)

    @staticmethod
    def _salida_de(ruta_receta):
        base = ruta_receta[:-len(".receta.json")] if ruta_receta.lower().endswith(".receta.json") \
            else os.path.splitext(ruta_receta)[0]
        return base + ".FCStd"

    def _construir(self, ruta, salida, referencia):
        """En un hilo: lanza el constructor y escribe el RESULTADO. referencia = dict(volumen, caja) o None."""
        print(f"FreeCAD: construyendo {os.path.basename(salida)}…")
        res = rc.construir(ruta, salida, log=print)
        print("RESULTADO " + json.dumps(res, ensure_ascii=False))
        tag = "ok" if res.get("ok") and res.get("valido") else "error"
        self.registro(("✔ " if tag == "ok" else "✖ ") + rc.texto_resultado(res), tag)
        if res.get("ok"):
            self.ultimo_fcstd = salida
            print("  pieza: " + salida)
            if referencia and res.get("volumen"):
                ev = (res["volumen"] - referencia["volumen"]) / referencia["volumen"] * 100
                txt = f"  volumen {ev:+.2f} % respecto al {referencia['que']}"
                c, cr = res.get("caja") or [], referencia.get("caja")
                if len(c) == 6 and cr:
                    dc = max(max(abs(c[i] - cr[0][i]), abs(c[3 + i] - cr[1][i])) for i in range(3))
                    txt += f", caja ±{dc:.2f} mm"
                self.registro(txt, "ok" if abs(ev) < 2 else "error")
        return bool(res.get("ok"))

    def abrir_en_freecad(self):
        p = self.ultimo_fcstd if self.ultimo_fcstd and os.path.isfile(self.ultimo_fcstd) else None
        if not p and self.receta_actual and os.path.isfile(self._salida_de(self.receta_actual)):
            p = self._salida_de(self.receta_actual)
        if not p:
            p = filedialog.askopenfilename(title="Pieza de FreeCAD", filetypes=[("FreeCAD", "*.FCStd")],
                                           initialdir=self.ultima_carpeta)
            if not p:
                return
            p = os.path.normpath(p)
        if not os.path.isfile(rc.FREECAD_GUI):
            self.escribe("No encuentro freecad.exe en " + rc.FREECAD_BIN, "error")
            return
        import subprocess
        try:
            subprocess.Popen([rc.FREECAD_GUI, p], close_fds=True)
            self.escribe(f"Abriendo en FreeCAD: {p}", "ok")
        except OSError as e:
            self.escribe(f"No se pudo lanzar FreeCAD: {e}", "error")

    # ------------------------------------------------------------ STL
    def t_stl(self):
        p = filedialog.askopenfilename(title="STL a convertir en pieza FreeCAD", filetypes=[("STL", "*.stl")],
                                       initialdir=self.ultima_carpeta)
        if not p:
            return
        p = os.path.normpath(p)
        self.ultima_carpeta = os.path.dirname(p)
        self.tarea("STL → pieza " + os.path.basename(p), self._stl, p)

    def _stl(self, p):
        import receta_stl
        print(f"Analizando {os.path.basename(p)} (elige eje, salientes y cortes; puede tardar unos segundos)…")
        receta, info = receta_stl.receta_desde_stl(p)
        ruta = rc.ruta_receta(p)
        rc.guardar(receta, ruta)
        self.after(0, self.mostrar_receta, ruta)
        print(f"Eje {info['eje']} → plano {info['plano']}: {rc.resumen(receta)}")
        print(f"Volumen STL {info['vol_stl']:.1f} mm³, receta {info['vol_receta']:.1f} mm³ "
              f"(error {info['err_vol'] * 100:.2f} %)")
        print("Receta: " + ruta)
        errores = rc.validar(receta)
        if errores:
            for e in errores:
                self.registro("   · " + e, "error")
            return False
        ref = dict(volumen=info["vol_stl"], caja=info["caja_stl"], que="STL")
        return self._construir(ruta, self._salida_de(ruta), ref)

    # ------------------------------------------------------------ PDF
    def t_pdf(self):
        p = filedialog.askopenfilename(title="Plano en PDF (vectorial)", filetypes=[("PDF", "*.pdf")],
                                       initialdir=self.ultima_carpeta)
        if not p:
            return
        p = os.path.normpath(p)
        self.ultima_carpeta = os.path.dirname(p)
        try:
            AsistentePlanoFC(self, p)
        except Exception as e:
            self.escribe(f"No se pudo leer el PDF: {e}", "error")

    def t_pdf_auto(self):
        p = filedialog.askopenfilename(title="Plano en PDF (vectorial)", filetypes=[("PDF", "*.pdf")],
                                       initialdir=self.ultima_carpeta)
        if not p:
            return
        p = os.path.normpath(p)
        self.ultima_carpeta = os.path.dirname(p)
        self.tarea("PDF → pieza " + os.path.basename(p), self._pdf_auto, p)

    def _pdf_auto(self, p):
        """En un hilo: lee las vistas del plano (receta_pdf.receta_desde_pdf), guarda la receta y la construye."""
        import receta_pdf
        print(f"Leyendo las vistas de {os.path.basename(p)}…")
        receta, info = receta_pdf.receta_desde_pdf(p)
        ruta = rc.ruta_receta(p)
        rc.guardar(receta, ruta)
        self.after(0, self.mostrar_receta, ruta)
        print(f"Método {info.get('metodo', '-')}: exterior {info['ancho']:.2f} × {info['alto']:.2f} mm, "
              f"{info['agujeros']} agujero(s), profundidad {info['espesor']:.2f} mm ({info['espesor_de']}); "
              f"escala {info['motivo_escala']}")
        print(rc.resumen(receta) + f"; variables {receta['variables']}")
        for n in info.get("notas", []):
            print("  nota: " + n)
        print("Receta: " + ruta)
        errores = rc.validar(receta)
        if errores:
            for e in errores:
                self.registro("   · " + e, "error")
            return False
        ref = dict(volumen=rc.volumen(receta), caja=rc.caja(receta), que="volumen de la receta")
        return self._construir(ruta, self._salida_de(ruta), ref)

    def t_cotas(self):
        p = filedialog.askopenfilename(title="Plano en PDF (con texto)", filetypes=[("PDF", "*.pdf")],
                                       initialdir=self.ultima_carpeta)
        if not p:
            return
        p = os.path.normpath(p)
        self.ultima_carpeta = os.path.dirname(p)
        try:
            import pdfcotas
            import pdfgeo
            try:
                g = pdfgeo.leer_geometria(p)
                caj = pdfgeo.datos_cajetin(p)
                esc, _ = pdfgeo.sugerir_escala(g["contornos"][0], pdfgeo.textos_numericos(p), caj["escala"])
                cotas, aviso = pdfcotas.leer_cotas(p, 0, g, esc, caj["espesor"])
            except Exception:
                cotas, aviso = pdfcotas.leer_cotas(p)
        except Exception as e:
            self.escribe(f"No se pudo leer el PDF: {e}", "error")
            return
        if aviso:
            self.escribe(aviso, "error")
        if cotas:
            self.escribe(f"{len(cotas)} cotas leídas de {os.path.basename(p)}: revísalas y pásalas a variables.", "ok")
            TablaCotasFC(self, cotas, p)

    # ------------------------------------------------------------ copias
    def t_respaldo(self):
        carpetas = []
        while True:
            c = filedialog.askdirectory(title="Carpeta a incluir (Cancelar cuando no haya más)")
            if not c:
                break
            carpetas.append(os.path.normpath(c))
        if not carpetas:
            return
        z = filedialog.asksaveasfilename(title="Guardar la copia como", defaultextension=".zip",
                                         initialfile="copia_seguridad.zip", filetypes=[("Zip", "*.zip")])
        if z:
            import tareas
            self.tarea("copia de seguridad", tareas.respaldo, carpetas, os.path.normpath(z))


class AsistentePlanoFC(tsw.AsistentePlano):
    """El asistente de roles de la app de SolidWorks, pero el paso 2 genera una receta y la construye en FreeCAD."""

    def __init__(self, app, pdf):
        super().__init__(app, pdf)
        self.title("Plano PDF → pieza FreeCAD: " + os.path.basename(pdf))
        textos = {"⚙  Generar código VBA": "📄  Generar receta",
                  "🧱 Crear la pieza ahora en SolidWorks": "🧱 Crear la pieza en FreeCAD"}
        for b in _botones(self):
            t = b.cget("text")
            if t in textos:
                b.configure(text=textos[t])
        for c in _casillas(self):
            if "constantes" in c.cget("text"):
                c.configure(text="Ancho y alto exteriores como variables (si hay cotas)")
                self.var_cotas.set(True)
        for w in self.winfo_children():
            if isinstance(w, ctk.CTkLabel) and w.cget("text").startswith("Paso 2"):
                w.configure(text="Paso 2 · Receta y pieza FreeCAD")

    def _receta(self):
        import receta_pdf
        ext = [c for c, r in zip(self.cont, self.roles) if r == "exterior"]
        if len(ext) != 1:
            messagebox.showwarning("Plano PDF", "Debe haber exactamente UN contorno con rol «exterior».", parent=self)
            return None
        ag = [c for c, r in zip(self.cont, self.roles) if r == "agujero"]
        e = self.escala_mm()
        cotas = receta_pdf.cotas_con_nombre(self.pdf, self.g, e, self.caj.get("espesor")) if self.var_cotas.get() else []
        nombre = os.path.splitext(os.path.basename(self.pdf))[0]
        receta, info = receta_pdf.receta_desde_contornos(nombre, "PDF " + os.path.basename(self.pdf), ext[0], ag, e,
                                                         self.espesor(), cotas, "indicado en el asistente")
        if info["descartados"]:
            self.app.escribe(f"⚠ {len(info['descartados'])} «agujeros» descartados para que la extrusión salga:", "error")
            for c, motivo in info["descartados"][:6]:
                x0, y0, x1, y1 = c["bbox"]
                self.app.escribe(f"   · {c['tipo']} de {(x1 - x0) * e:.1f} × {(y1 - y0) * e:.1f} mm: {motivo}", "error")
        errores = rc.validar(receta)
        if errores:
            for x in errores[:8]:
                self.app.escribe("   · " + x, "error")
            messagebox.showwarning("Plano PDF", "La receta no es válida (mira el registro).", parent=self)
            return None
        ruta = rc.ruta_receta(self.pdf)
        rc.guardar(receta, ruta)
        self.app.mostrar_receta(ruta)
        self.app.escribe(f"Receta desde {os.path.basename(self.pdf)}: exterior {info['ancho']:.2f} × {info['alto']:.2f} mm, "
                         f"{info['agujeros']} agujero(s), espesor {info['espesor']:g} mm; variables {receta['variables']}. "
                         f"Guardada en {ruta}", "ok")
        return ruta, receta

    def genera(self):
        if self._receta():
            self.destroy()

    def crea(self):
        r = self._receta()
        if not r:
            return
        ruta, receta = r
        ref = dict(volumen=rc.volumen(receta), caja=rc.caja(receta), que="volumen de la receta")
        self.app.tarea("PDF → pieza " + os.path.basename(self.pdf), self.app._construir, ruta,
                       TallerFreeCAD._salida_de(ruta), ref)
        self.destroy()

    def ver_cotas(self):
        if self.cotas:
            TablaCotasFC(self.app, self.cotas, self.pdf)
        else:
            messagebox.showinfo("Plano PDF", "No hay cotas de texto en el PDF.", parent=self)


class TablaCotasFC(tsw.TablaCotas):
    """La tabla de cotas de la app de SolidWorks; las elegidas pasan a variables de una receta."""

    def __init__(self, app, cotas, pdf):
        super().__init__(app, cotas, pdf)
        textos = {"⚙  Pasar al editor: variables de SolidWorks": "⚙  Añadir a la receta abierta",
                  "Solo constantes": "Añadir a otra receta…"}
        for b in _botones(self):
            t = b.cget("text")
            if t in textos:
                b.configure(text=textos[t])

    def al_editor(self, modo):
        sel = self.elegidas()
        if sel is None:
            return
        ruta = self.app.receta_actual if modo == "variables" else None
        if not ruta:
            ruta = filedialog.askopenfilename(title="Receta a la que añadir las variables", parent=self,
                                              filetypes=[("Receta", "*.receta.json")],
                                              initialdir=os.path.dirname(self.pdf))
            if not ruta:
                return
        try:
            with open(ruta, encoding="utf-8") as f:
                receta = json.load(f)
        except (OSError, ValueError) as e:
            messagebox.showwarning("Cotas", f"No se pudo leer la receta: {e}", parent=self)
            return
        var = receta.setdefault("variables", {})
        cambios = []
        for c in sel:
            n, v = c["nombre"], float(c["valor"])
            if var.get(n) != v:
                cambios.append(f"{n} = {v:g}" + (f" (antes {var[n]:g})" if n in var else ""))
            var[n] = v
            for op in receta.get("operaciones", []):           # parametros enlazados: que sigan coincidiendo
                for par, nv in (op.get("cotas") or {}).items():
                    if nv == n:
                        op[par] = v
        rc.guardar(receta, ruta)
        self.app.mostrar_receta(ruta)
        self.app.escribe(f"{len(sel)} variables en {os.path.basename(ruta)}: " + ("; ".join(cambios) or "sin cambios")
                         + ". Las que no están enlazadas a una operación solo quedan en la hoja «Variables».", "ok")
        self.destroy()


if __name__ == "__main__":
    app = TallerFreeCAD()
    if "--prueba" in sys.argv:                   # arranque de prueba: se cierra sola a los 3 s
        app.after(3000, app.destroy)
    app.mainloop()
