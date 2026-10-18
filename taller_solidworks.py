"""Taller SolidWorks: macros VBA, tareas automaticas y herramientas en una sola ventana.

Uso:  pythonw taller_solidworks.pyw   (o el acceso directo "Taller SolidWorks")
"""
import contextlib
import io
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# El .exe sin consola no tiene stdout/stderr: sin esto, oletools y print() fallan con "flush".
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

import customtkinter as ctk

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
DATOS = os.path.join(os.environ.get("APPDATA", AQUI), "TallerSolidWorks")
os.makedirs(DATOS, exist_ok=True)
LISTA = os.path.join(DATOS, "macros.json")
VBA_POR_DEFECTO = r"C:\SOLIDWORKS Data\FreeCAD_Macros\VBA"
TIPOS = [("Macros VBA", "*.swp *.bas *.vba *.txt *.cls *.frm"), ("Todos", "*.*")]

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

FONDO, PANEL, BARRA = "#14171c", "#1c2128", "#0f1216"
ACENTO, ACENTO_H = "#2f81f7", "#1f6feb"
VERDE, ROJO, GRIS = "#3fb950", "#f85149", "#8b949e"


def leer_codigo(path):
    """Texto VBA de un archivo (en .swp extrae los modulos)."""
    if path.lower().endswith(".swp"):
        import sw
        mods = sw.vba_modules(path)
        if not mods:
            return "(no se encontro codigo VBA)"
        mods = [(n, c) for n, c in mods if n != "ThisLibrary"] or mods
        return "\n\n".join(f"' ===== Modulo: {n} =====\n{c.strip()}" for n, c in mods)
    for enc in ("utf-8-sig", "cp1252"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return ""


class Taller(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Taller SolidWorks")
        self.geometry("1260x690+40+30")
        self.minsize(980, 600)
        self.configure(fg_color=FONDO)
        self.archivos = []
        self.en_curso = {}
        self.al_terminar = {}
        self.ultimo_stl = None
        self.actual = None
        self.botones_lista = []
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._lateral()
        self._principal()
        self._estado_barra()
        self._cargar()
        self.after(300, self._refrescar_estado)

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
        ctk.CTkLabel(lat, text="Taller SolidWorks", font=ctk.CTkFont(size=22, weight="bold"),
                     anchor="w").pack(fill="x", padx=18, pady=(16, 0))
        ctk.CTkLabel(lat, text="macros, copias y conversiones", text_color=GRIS, anchor="w").pack(fill="x", padx=18)

        self._seccion(lat, "Gemini")
        self._boton_lateral(lat, "📄→🧱  Plano PDF → pieza…", self.g_pdf_a_pieza)
        self._boton_lateral(lat, "🧱→📄  Pieza activa → plano PDF…", self.g_pieza_a_plano)
        self._boton_lateral(lat, "📚  Planos de una carpeta…", self.g_planos_carpeta)
        self._boton_lateral(lat, "🤖  Leer cotas con Gemini…", self.plano_gemini)

        self._seccion(lat, "Documentos")
        self._boton_lateral(lat, "📋  Estado de documentos", lambda: self.tarea("estado"))
        self._boton_lateral(lat, "💾  Guardar todo", lambda: self.tarea("guardar_todo"))
        self._boton_lateral(lat, "🪟  SolidWorks al frente", lambda: self.tarea("traer_al_frente"))

        self._seccion(lat, "Copias")
        self._boton_lateral(lat, "🗜️  Copia de seguridad (zip)…", self.t_respaldo)
        self._boton_lateral(lat, "📦  Conjunto activo → carpeta nueva…", self.t_conjunto)
        self._boton_lateral(lat, "🧹  Limpiar temporales ~$…", self.t_limpiar)

        self._seccion(lat, "Mallas")
        self._boton_lateral(lat, "🔍  STL → macro .swp…", self.t_analizar)

        self._seccion(lat, "Macros")
        self._boton_lateral(lat, "➕  Añadir macros…", self.anadir)
        self._boton_lateral(lat, "📝  Nuevo .bas…", self.nuevo)
        self._boton_lateral(lat, "⚙️  Convertir .bas a .swp", self.a_swp)

    def _principal(self):
        cen = ctk.CTkFrame(self, fg_color="transparent")
        cen.grid(row=0, column=1, sticky="nsew", padx=14, pady=(14, 6))
        cen.grid_columnconfigure(1, weight=1)
        cen.grid_rowconfigure(0, weight=3)
        cen.grid_rowconfigure(1, weight=1)

        izq = ctk.CTkFrame(cen, corner_radius=12, fg_color=PANEL, width=260)
        izq.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        izq.grid_propagate(False)
        ctk.CTkLabel(izq, text="Mis macros", font=ctk.CTkFont(size=15, weight="bold"),
                     anchor="w").pack(fill="x", padx=14, pady=(12, 4))
        self.lista = ctk.CTkScrollableFrame(izq, fg_color="transparent")
        self.lista.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        self.lbl_vacio = ctk.CTkLabel(self.lista, text="Sin macros todavía.\nUsa «Añadir macros…»",
                                      text_color=GRIS)
        ctk.CTkButton(izq, text="Quitar de la lista", height=28, fg_color="#30363d", hover_color="#3d444d",
                      command=self.quitar).pack(fill="x", padx=12, pady=(0, 12))

        der = ctk.CTkFrame(cen, corner_radius=12, fg_color=PANEL)
        der.grid(row=0, column=1, sticky="nsew")
        der.grid_columnconfigure(0, weight=1)
        der.grid_rowconfigure(2, weight=1)
        cab = ctk.CTkFrame(der, fg_color="transparent")
        cab.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        self.titulo = ctk.CTkLabel(cab, text="Editor VBA", font=ctk.CTkFont(size=15, weight="bold"), anchor="w")
        self.titulo.pack(side="left")
        self.abrir_sw = ctk.CTkCheckBox(cab, text="Abrir SolidWorks si está cerrado", text_color=GRIS)
        self.abrir_sw.pack(side="right")
        fila = ctk.CTkFrame(der, fg_color="transparent")
        fila.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 4))
        for txt, cmd, color, hov in (("▶ Ejecutar en SolidWorks", self.ejecutar, ACENTO, ACENTO_H),
                                     ("📤 Enviar a SolidWorks", self.enviar, "#30363d", "#3d444d"),
                                     ("💾 Guardar", self.guardar, "#30363d", "#3d444d"),
                                     ("Guardar como…", self.guardar_como, "#30363d", "#3d444d"),
                                     ("📋 Copiar", self.copiar, "#30363d", "#3d444d"),
                                     ("👁 Ver código", self.recargar, "#30363d", "#3d444d")):
            b = ctk.CTkButton(fila, text=txt, command=cmd, width=10, height=30, fg_color=color, hover_color=hov,
                              font=ctk.CTkFont(size=12), corner_radius=6)
            b.pack(side="left", padx=(0, 5))
            if color == ACENTO:
                self.btn_ejecutar = b
        self.codigo = ctk.CTkTextbox(der, font=("Consolas", 13), fg_color=BARRA, wrap="none", undo=True,
                                     corner_radius=8, border_width=0)
        self.codigo.grid(row=2, column=0, sticky="nsew", padx=12, pady=(4, 12))

        reg = ctk.CTkFrame(cen, corner_radius=12, fg_color=PANEL)
        reg.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        reg.grid_columnconfigure(0, weight=1)
        reg.grid_rowconfigure(1, weight=1)
        cab2 = ctk.CTkFrame(reg, fg_color="transparent")
        cab2.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        ctk.CTkLabel(cab2, text="Registro", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkButton(cab2, text="Limpiar", width=70, height=24, fg_color="#30363d", hover_color="#3d444d",
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
        self.estado_txt = ctk.CTkLabel(barra, text="comprobando SolidWorks…", text_color=GRIS, anchor="w")
        self.estado_txt.pack(side="left")

    def _refrescar_estado(self):
        if self.en_curso:   # SolidWorks esta ocupado con una tarea: no le hacemos preguntas
            self.punto.configure(text_color="#d29922")
            self.estado_txt.configure(text="⏳ en curso: " + ", ".join(self.en_curso) +
                                      "  (SolidWorks ocupado, espera a que termine)", text_color="#d29922")
            self.after(1500, self._refrescar_estado)
            return

        def trabajo():
            try:
                import pythoncom
                pythoncom.CoInitialize()
                import tareas
                ok, txt = tareas.conexion()
            except Exception as e:
                ok, txt = False, f"sin conexión ({e})"
            self.after(0, lambda: self._pintar_estado(ok, txt))
        threading.Thread(target=trabajo, daemon=True).start()
        self.after(5000, self._refrescar_estado)

    def _pintar_estado(self, ok, txt):
        self.punto.configure(text_color=VERDE if ok else ROJO)
        self.estado_txt.configure(text=txt, text_color="#c9d1d9" if ok else GRIS)

    # ------------------------------------------------------------ lista de macros
    def _cargar(self):
        try:
            with open(LISTA, encoding="utf-8") as f:
                for p in json.load(f):
                    if os.path.exists(p):
                        self._add(p, guardar=False)
        except (OSError, ValueError):
            pass
        if not self.archivos and os.path.isdir(VBA_POR_DEFECTO):
            for n in sorted(os.listdir(VBA_POR_DEFECTO)):
                if n.lower().endswith(".swp"):
                    self._add(os.path.join(VBA_POR_DEFECTO, n), guardar=False)
            self._guardar_lista()
        self._pintar_lista()

    def _guardar_lista(self):
        with open(LISTA, "w", encoding="utf-8") as f:
            json.dump(self.archivos, f, indent=1)

    def _add(self, p, guardar=True):
        p = os.path.abspath(p)
        if p not in self.archivos:
            self.archivos.append(p)
            if guardar:
                self._guardar_lista()

    def _pintar_lista(self):
        for b in self.botones_lista:
            b.destroy()
        self.botones_lista = []
        self.lbl_vacio.pack_forget()
        if not self.archivos:
            self.lbl_vacio.pack(pady=30)
        for p in self.archivos:
            ext = os.path.splitext(p)[1].lower()
            icono = "⚙️" if ext == ".swp" else "📄"
            b = ctk.CTkButton(self.lista, text=f"{icono}  {os.path.basename(p)}", anchor="w", height=34,
                              corner_radius=8, fg_color="#262d36" if p == self.actual else "transparent",
                              hover_color="#30363d", text_color="#e6edf3",
                              command=lambda p=p: self.ver(p))
            b.pack(fill="x", padx=4, pady=1)
            self.botones_lista.append(b)

    def anadir(self):
        for p in filedialog.askopenfilenames(title="Elige macros VBA", filetypes=TIPOS):
            self._add(p)
        self._pintar_lista()

    def quitar(self):
        if self.actual in self.archivos:
            self.archivos.remove(self.actual)
            self._guardar_lista()
            self.actual = None
            self.codigo.delete("1.0", "end")
            self.titulo.configure(text="Editor VBA")
            self._pintar_lista()

    # ------------------------------------------------------------ editor
    def report_callback_exception(self, exc, valor, tb):
        """Cualquier error interno de un boton sale en el registro (antes se perdia sin avisar)."""
        import traceback
        self.escribe(f"✖ error interno: {valor}", "error")
        self.escribe("".join(traceback.format_exception(exc, valor, tb))[-600:], "error")

    def ver(self, p):
        p = os.path.abspath(p)
        self.actual = p
        try:
            txt = leer_codigo(p)
        except Exception as e:
            txt = f"Error leyendo el archivo: {e}"
        self.codigo.delete("1.0", "end")
        self.codigo.insert("1.0", txt)
        self.titulo.configure(text=os.path.basename(p) if len(os.path.basename(p)) < 24 else os.path.basename(p)[:21] + "…")
        self._pintar_lista()

    def _necesita(self):
        if not self.actual:
            messagebox.showinfo("Taller SolidWorks", "Elige primero una macro de la lista.")
            return None
        return self.actual

    PLANTILLA = ("Dim swApp As SldWorks.SldWorks\n\nSub main()\n"
                 "    Set swApp = Application.SldWorks\n    ' tu codigo aqui\nEnd Sub\n")

    def nuevo(self):
        p = filedialog.asksaveasfilename(title="Nueva macro", defaultextension=".bas",
                                         filetypes=[("Modulo VBA", "*.bas")])
        if p:
            with open(p, "w", encoding="cp1252", newline="\r\n") as f:
                f.write(self.PLANTILLA)
            self._add(p)
            self.ver(p)

    def _escribir(self, p):
        with open(p, "w", encoding="cp1252", errors="replace", newline="\r\n") as f:
            f.write(self.codigo.get("1.0", "end-1c"))
        self.escribe("Guardado: " + p, "ok")

    def guardar(self):
        p = self._necesita()
        if not p:
            return
        if p.lower().endswith(".swp"):
            return self.guardar_como()
        self._escribir(p)

    def guardar_como(self):
        p = filedialog.asksaveasfilename(defaultextension=".bas",
                                         filetypes=[("Modulo VBA", "*.bas"), ("Texto", "*.txt")])
        if p:
            self._escribir(p)
            self._add(p)
            self.ver(p)

    def copiar(self):
        txt = self.codigo.get("1.0", "end").strip()
        if txt:
            self.clipboard_clear()
            self.clipboard_append(txt)
            self.escribe("Código copiado al portapapeles. En SolidWorks: Herramientas > Macro > Nueva… y pegar.", "ok")

    def ejecutar(self):
        p = self._necesita()
        if p:
            self.tarea("ejecutar_macro", p, bool(self.abrir_sw.get()))

    def recargar(self):
        p = self._necesita()
        if p:
            self.ver(p)
            self.escribe(f"Código recargado desde el archivo: {os.path.basename(p)}", "ok")

    def enviar(self):
        p = self._necesita()
        if p and not p.lower().endswith(".swp"):
            self.a_swp()
        else:
            self.copiar()

    # ------------------------------------------------------------ tareas
    def escribe(self, txt, tag=None):
        self.log.insert("end", txt + "\n", tag)
        self.log.see("end")

    def _hilo(self, nombre, fn, *a):
        app = self

        class Salida(io.TextIOBase):
            """Cada linea que imprime la tarea sale en el registro al momento."""
            def __init__(self):
                self.resto = ""

            def write(self, txt):
                self.resto += txt
                while "\n" in self.resto:
                    linea, self.resto = self.resto.split("\n", 1)
                    app.after(0, lambda l=linea: app.escribe(l))
                return len(txt)

            def flush(self):
                pass

        def run():
            import time
            t0 = time.time()
            salida = Salida()
            tag, ok = "ok", True
            msg = ""
            try:
                import pythoncom
                pythoncom.CoInitialize()
                with contextlib.redirect_stdout(salida):
                    fn(*a)
            except SystemExit as e:
                tag, ok, msg = "error", False, str(e.code or "terminó con error")
            except Exception as e:
                tag, ok, msg = "error", False, str(e)
            if salida.resto.strip():
                app.after(0, lambda l=salida.resto: app.escribe(l))
            seg = time.time() - t0
            texto = (f"✔ {nombre.replace('_', ' ')} terminada ({seg:.1f} s)" if ok
                     else f"✖ {nombre.replace('_', ' ')}: {msg}")
            app.after(0, lambda: app._fin(nombre, texto, tag))
        threading.Thread(target=run, daemon=True).start()

    def _fin(self, nombre, texto, tag):
        self.en_curso.pop(nombre, None)
        self.escribe(texto, tag)
        self._boton_ejecutar_estado()
        siguiente = self.al_terminar.pop(nombre, None)
        if siguiente and tag == "ok":
            siguiente()

    def _boton_ejecutar_estado(self):
        ocupado = "ejecutar_macro" in self.en_curso
        self.btn_ejecutar.configure(text="⏳  Ejecutando…" if ocupado else "▶ Ejecutar en SolidWorks",
                                    state="disabled" if ocupado else "normal")

    def tarea(self, nombre, *args):
        import tareas
        if nombre in self.en_curso:
            self.escribe(f"⚠ «{nombre.replace('_', ' ')}» ya se está ejecutando: espera a que termine "
                         "(si pulsas otra vez se lanzaría dos veces).", "error")
            return
        self.en_curso[nombre] = True
        etiqueta = os.path.basename(args[0]) if args and isinstance(args[0], str) else ""
        self.escribe(f"▶ {nombre.replace('_', ' ')} {etiqueta}".rstrip() + "  (en curso…)", "tarea")
        self._boton_ejecutar_estado()
        self.punto.configure(text_color="#d29922")
        self.estado_txt.configure(text="⏳ en curso: " + ", ".join(self.en_curso), text_color="#d29922")
        if nombre == "ejecutar_macro":
            self.after(6000, lambda: self.en_curso.get(nombre) and self.escribe(
                "⚠ La macro sigue en marcha: puede estar esperando un aviso o una respuesta dentro de SolidWorks "
                "(mira su ventana o la barra de tareas).", "error"))
        self._hilo(nombre, getattr(tareas, nombre), *args)

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
            self.tarea("respaldo", carpetas, os.path.normpath(z))

    def t_conjunto(self):
        c = filedialog.askdirectory(title="Carpeta NUEVA donde guardar el conjunto con todas sus piezas")
        if c:
            self.tarea("conjunto_a_carpeta", os.path.normpath(c))

    def t_analizar(self):
        p = filedialog.askopenfilename(title="STL a convertir en macro", filetypes=[("STL", "*.stl")],
                                       initialdir=os.path.dirname(self.ultimo_stl) if self.ultimo_stl else None)
        if p:
            self.ultimo_stl = os.path.normpath(p)
            salida = os.path.splitext(self.ultimo_stl)[0] + "_macro.swp"
            self.al_terminar["stl_a_macro"] = lambda: (self._add(salida), self.ver(salida))
            self.tarea("stl_a_macro", self.ultimo_stl)

    def a_swp(self):
        p = self._necesita()
        if not p:
            return
        if p.lower().endswith(".swp"):
            self.escribe("Esa macro ya es .swp.", "ok")
            return
        destino = os.path.splitext(p)[0] + ".swp"
        self.al_terminar["convertir_a_swp"] = lambda: (self._add(destino), self.ver(destino))
        self.tarea("convertir_a_swp", p)

    def t_limpiar(self):
        import tareas
        conectado, _ = tareas.conexion()
        if not conectado:
            print("SolidWorks no conectado. Abre un proyecto primero.")
            return
        try:
            sw = tareas._sw()
            doc = tareas.val(sw, "ActiveDoc")
            if doc is None:
                print("Ningún documento abierto. Abre un proyecto primero.")
                return
            ruta = tareas.val(doc, "GetPathName")
            carpeta = os.path.dirname(ruta)
            self.tarea("limpiar_temporales", os.path.normpath(carpeta))
        except Exception as e:
            print(f"Error: {e}")

    def t_generar_planos(self):
        ensamblaje = filedialog.askopenfilename(
            title="Selecciona el ensamblaje (.SLDASM)",
            filetypes=[("Ensamblaje SolidWorks", "*.sldasm"), ("Todos", "*.*")],
            initialdir=os.path.expanduser("~/OneDrive/Escritorio/diseños 3d/Bicicleta_final")
        )
        if not ensamblaje:
            return
        carpeta = filedialog.askdirectory(title="Carpeta donde guardar los planos PDF")
        if carpeta:
            self.tarea("generar_planos_bicicleta", os.path.normpath(ensamblaje), os.path.normpath(carpeta))

    # ------------------------------------------------------------ plano PDF -> VBA
    def tarea_funcion(self, nombre, fn, *args):
        """Como tarea(), pero con una funcion propia (no de tareas.py)."""
        if nombre in self.en_curso:
            self.escribe(f"⚠ «{nombre}» ya se está ejecutando.", "error")
            return
        self.en_curso[nombre] = True
        self.punto.configure(text_color="#d29922")
        self.estado_txt.configure(text="⏳ en curso: " + ", ".join(self.en_curso), text_color="#d29922")
        self._hilo(nombre, fn, *args)

    def plano_pdf(self):
        p = filedialog.askopenfilename(title="Plano en PDF (vectorial)", filetypes=[("PDF", "*.pdf")])
        if not p:
            return
        try:
            AsistentePlano(self, os.path.normpath(p))
        except Exception as e:
            self.escribe(f"No se pudo leer el PDF: {e}", "error")

    def cotas_pdf(self):
        p = filedialog.askopenfilename(title="Plano en PDF (con texto)", filetypes=[("PDF", "*.pdf")])
        if not p:
            return
        p = os.path.normpath(p)
        try:
            import pdfcotas
            import pdfgeo
            try:   # la geometria sirve para reconocer ancho, alto y diametros; si falla se sigue sin ella
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
            self.escribe(f"{len(cotas)} cotas leídas de {os.path.basename(p)}: revísalas y pásalas al editor.", "ok")
            TablaCotas(self, cotas, p)

    # ------------------------------------------------------------ Gemini: PDF -> pieza -> plano
    def g_pdf_a_pieza(self):
        p = filedialog.askopenfilename(title="Plano (PDF o foto acotada) para modelar en SolidWorks", filetypes=[
            ("Planos e imágenes", "*.pdf *.png *.jpg *.jpeg *.webp"), ("Todos", "*.*")])
        if not p:
            return
        p = os.path.normpath(p)

        def hacer():
            import plano_a_macro
            plano_a_macro.crear(p)
        self.escribe(f"▶ Plano → pieza: {os.path.basename(p)}  (Gemini lee el plano y SolidWorks modela; "
                     "deja junto al plano la receta y la macro)", "tarea")
        self.tarea_funcion("plano_a_pieza", hacer)

    def g_pieza_a_plano(self):
        import tareas
        conectado, _ = tareas.conexion()
        if not conectado:
            self.escribe("SolidWorks no está abierto: abre la pieza primero.", "error")
            return
        c = filedialog.askdirectory(title="Carpeta donde guardar la pieza y su plano (se crea /planos dentro)")
        if not c:
            return
        orig = filedialog.askopenfilename(title="Plano original para imitar (opcional: Cancelar si no hay)",
                                          filetypes=[("PDF", "*.pdf")])

        def hacer():
            import planos_gemini
            planos_gemini.hacer_plano(os.path.normpath(c), os.path.normpath(orig) if orig else None)
        self.escribe("▶ Pieza activa → plano A4 (Gemini elige y coloca las cotas)", "tarea")
        self.tarea_funcion("pieza_a_plano", hacer)

    def g_planos_carpeta(self):
        c = filedialog.askdirectory(title="Carpeta con las piezas (.SLDPRT): se trabaja sobre una copia")
        if not c:
            return

        def hacer():
            import planos_gemini
            planos_gemini.planos_carpeta(os.path.normpath(c))
        self.escribe(f"▶ Planos de {os.path.basename(c)}: sencillas de dos en dos, complejas una por hoja "
                     "(puede tardar varios minutos)", "tarea")
        self.tarea_funcion("planos_carpeta", hacer)

    def plano_gemini(self):
        p = filedialog.askopenfilename(title="Plano o foto acotada para Gemini", filetypes=[
            ("Planos e imágenes", "*.pdf *.png *.jpg *.jpeg *.webp"), ("Todos", "*.*")])
        if not p:
            return
        p = os.path.normpath(p)
        res = {}

        def leer():
            import gemini_plano
            print(f"Enviando {os.path.basename(p)} a Gemini ({gemini_plano.MODELO})…")
            res["cotas"], res["datos"] = gemini_plano.leer_plano(p)

        def mostrar():
            datos, cotas = res["datos"], res["cotas"]
            info = [datos.get("pieza"), datos.get("material"),
                    f"espesor {datos['espesor_mm']:g} mm" if datos.get("espesor_mm") else None]
            self.escribe(" · ".join(str(x) for x in info if x), "ok")
            for o in datos.get("operaciones_sugeridas") or []:
                self.escribe("   • " + o)
            if cotas:
                self.escribe(f"{len(cotas)} cotas leídas por Gemini: revísalas y pásalas al editor "
                             f"(JSON guardado como {os.path.splitext(os.path.basename(p))[0]}_gemini.json).", "ok")
                TablaCotas(self, cotas, p)
            else:
                self.escribe("Gemini no ha encontrado cotas en ese plano.", "error")

        self.escribe(f"▶ Leer plano con Gemini {os.path.basename(p)}  (en curso…)", "tarea")
        self.al_terminar["leer_plano_gemini"] = mostrar
        self.tarea_funcion("leer_plano_gemini", leer)


class AsistentePlano(ctk.CTkToplevel):
    """Plano PDF -> codigo VBA, en dos pasos: 1) leer datos del PDF  2) generar el codigo."""

    ROLES = ("exterior", "agujero", "ignorar")

    def __init__(self, app, pdf):
        super().__init__(app)
        import pdfgeo
        self.app, self.pdf = app, pdf
        self.title("Plano PDF → código VBA: " + os.path.basename(pdf))
        self.geometry("1020x640+90+50")
        self.configure(fg_color=FONDO)
        self.after(150, self.lift)
        self.g = pdfgeo.leer_geometria(pdf)
        self.cont = self.g["contornos"]
        self.nums = pdfgeo.textos_numericos(pdf)
        self.roles = []
        self.cotas = []
        try:
            import pdfcotas
            self.cotas, _ = pdfcotas.proponer(pdf)
        except Exception:
            pass
        if not self.cont:
            ctk.CTkLabel(self, text="No he encontrado contornos cerrados en el PDF.\n\n"
                         "Este paso solo funciona con planos VECTORIALES (exportados de CAD o de SolidWorks),\n"
                         "no con fotos ni escaneos.", justify="left", text_color=GRIS).pack(padx=30, pady=40)
            ctk.CTkButton(self, text="Cerrar", command=self.destroy).pack()
            return
        # Exterior sugerido: el mayor contorno que NO sea un circulo (una vista circular suele ser un detalle);
        # si el circulo es mucho mayor que cualquier otro contorno, la pieza es redonda y se queda el circulo.
        mayor = self.cont[0]["area"]
        ie = next((i for i, c in enumerate(self.cont) if c["tipo"] != "circulo" and c["area"] >= 0.25 * mayor), 0)
        if ie:
            self.cont.insert(0, self.cont.pop(ie))
        ext = self.cont[0]
        self.caj = pdfgeo.datos_cajetin(pdf)
        self.escala, self.motivo = pdfgeo.sugerir_escala(ext, self.nums, self.caj["escala"])
        ex0, ey0, ex1, ey1 = ext["bbox"]
        self.ancho_pt = ex1 - ex0
        for i, c in enumerate(self.cont):
            x0, y0, x1, y1 = c["bbox"]
            dentro = x0 >= ex0 - 1 and y0 >= ey0 - 1 and x1 <= ex1 + 1 and y1 <= ey1 + 1
            peq = (x1 - x0) * self.escala < 1 and (y1 - y0) * self.escala < 1
            # puntas de flecha de las cotas: triangulos o cuñas pequeñas, no son agujeros
            flecha = (c["tipo"] == "contorno" and len(c["items"]) <= 4 and all(it[0] == "l" for it in c["items"])
                      and max(x1 - x0, y1 - y0) * self.escala < 15)
            self.roles.append("exterior" if i == 0 else ("agujero" if dentro and not peq and not flecha else "ignorar"))
        self._ui()
        self.dibuja()

    def _ui(self):
        ctk.CTkLabel(self, text="Paso 1 · Datos leídos del PDF", font=ctk.CTkFont(size=17, weight="bold"),
                     anchor="w").pack(fill="x", padx=18, pady=(14, 0))
        ctk.CTkLabel(self, text=f"{len(self.cont)} contornos cerrados · {len(self.cotas)} cotas de texto · "
                     "marca cuál es el contorno exterior y cuáles son agujeros (doble clic en «Rol»).",
                     text_color=GRIS, anchor="w").pack(fill="x", padx=18)
        cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        cuerpo.pack(fill="both", expand=True, padx=14, pady=8)
        cuerpo.grid_columnconfigure(0, weight=3)
        cuerpo.grid_columnconfigure(1, weight=2)
        cuerpo.grid_rowconfigure(0, weight=1)
        self.lienzo = tk.Canvas(cuerpo, bg=BARRA, highlightthickness=0)
        self.lienzo.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.lienzo.bind("<Configure>", lambda e: self.dibuja())
        der = ctk.CTkFrame(cuerpo, fg_color=PANEL, corner_radius=10)
        der.grid(row=0, column=1, sticky="nsew")
        estilo = ttk.Style(self)
        estilo.theme_use("clam")
        estilo.configure("Plano.Treeview", background=BARRA, fieldbackground=BARRA, foreground="#e6edf3",
                         rowheight=26, borderwidth=0, font=("Segoe UI", 10))
        estilo.configure("Plano.Treeview.Heading", background=PANEL, foreground="#e6edf3", relief="flat",
                         font=("Segoe UI", 10, "bold"))
        estilo.map("Plano.Treeview", background=[("selected", ACENTO)])
        self.tv = ttk.Treeview(der, columns=("rol", "tipo", "med"), show="headings", height=8,
                               selectmode="browse", style="Plano.Treeview")
        for c, t, w_ in (("rol", "Rol", 80), ("tipo", "Tipo", 80), ("med", "Medida (mm)", 140)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w_, anchor="w")
        self.tv.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        self.tv.bind("<Double-Button-1>", self.cambia_rol)
        self.tv.bind("<<TreeviewSelect>>", lambda e: self.dibuja())

        cam = ctk.CTkFrame(der, fg_color="transparent")
        cam.pack(fill="x", padx=10)
        cam.grid_columnconfigure(1, weight=1)
        ex0, ey0, ex1, ey1 = self.cont[0]["bbox"]
        ctk.CTkLabel(cam, text="Ancho real del exterior (mm)", anchor="w").grid(row=0, column=0, sticky="w", pady=2)
        self.e_ancho = ctk.CTkEntry(cam, width=90)
        self.e_ancho.grid(row=0, column=1, sticky="e")
        self.e_ancho.insert(0, f"{self.ancho_pt * self.escala:.2f}")
        self.e_ancho.bind("<KeyRelease>", lambda e: self.refresca_info())
        ctk.CTkLabel(cam, text="Espesor de la pieza (mm)", anchor="w").grid(row=1, column=0, sticky="w", pady=2)
        self.e_esp = ctk.CTkEntry(cam, width=90)
        self.e_esp.grid(row=1, column=1, sticky="e")
        self.e_esp.insert(0, f"{self.caj['espesor']:g}" if self.caj.get("espesor") else "10")
        self.var_cotas = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(cam, text="Añadir las cotas del texto como constantes", variable=self.var_cotas,
                        text_color=GRIS).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 2))
        self.info = ctk.CTkLabel(der, text="", text_color=GRIS, justify="left", anchor="w", wraplength=330)
        self.info.pack(fill="x", padx=12, pady=(4, 8))

        ctk.CTkLabel(self, text="Paso 2 · Generar el código", font=ctk.CTkFont(size=17, weight="bold"),
                     anchor="w").pack(fill="x", padx=18, pady=(2, 0))
        fila = ctk.CTkFrame(self, fg_color="transparent")
        fila.pack(fill="x", padx=14, pady=10)
        ctk.CTkButton(fila, text="⚙  Generar código VBA", command=self.genera, fg_color=ACENTO,
                      hover_color=ACENTO_H).pack(side="left", padx=(0, 8))
        ctk.CTkButton(fila, text="🧱 Crear la pieza ahora en SolidWorks", command=self.crea,
                      fg_color="#30363d", hover_color="#3d444d").pack(side="left", padx=(0, 8))
        ctk.CTkButton(fila, text="📋 Cotas del texto…", command=self.ver_cotas, fg_color="#30363d",
                      hover_color="#3d444d").pack(side="left")
        ctk.CTkButton(fila, text="Cerrar", command=self.destroy, fg_color="#30363d",
                      hover_color="#3d444d").pack(side="right")
        self.refresca_tabla()
        self.refresca_info()

    # ---------------------------------------------------------------- lectura de los campos
    def escala_mm(self):
        try:
            return float(self.e_ancho.get().replace(",", ".")) / self.ancho_pt
        except (ValueError, ZeroDivisionError):
            return self.escala

    def espesor(self):
        try:
            return max(float(self.e_esp.get().replace(",", ".")), 0.01)
        except ValueError:
            return 10.0

    def refresca_info(self):
        if not hasattr(self, "info"):
            return
        e = self.escala_mm()
        ie = self.roles.index("exterior") if "exterior" in self.roles else 0
        x0, y0, x1, y1 = self.cont[ie]["bbox"]
        self.info.configure(text=f"Escala: {e:.4f} mm por punto del PDF ({self.motivo}).\n"
                            f"Exterior: {(x1 - x0) * e:.2f} × {(y1 - y0) * e:.2f} mm.")
        self.refresca_tabla()

    def refresca_tabla(self):
        e = self.escala_mm()
        sel = self.tv.selection()
        self.tv.delete(*self.tv.get_children())
        for i, c in enumerate(self.cont):
            x0, y0, x1, y1 = c["bbox"]
            med = (f"Ø {2 * c['r'] * e:.2f}" if c["tipo"] == "circulo"
                   else f"{(x1 - x0) * e:.1f} × {(y1 - y0) * e:.1f}")
            self.tv.insert("", "end", iid=str(i), values=(self.roles[i], c["tipo"], med))
        if sel and self.tv.exists(sel[0]):
            self.tv.selection_set(sel[0])

    def cambia_rol(self, ev):
        fila = self.tv.identify_row(ev.y)
        if fila:
            i = int(fila)
            self.roles[i] = self.ROLES[(self.ROLES.index(self.roles[i]) + 1) % 3]
            if self.roles[i] == "exterior":            # solo puede haber uno: los demas pasan a «ignorar»
                for j in range(len(self.roles)):
                    if j != i and self.roles[j] == "exterior":
                        self.roles[j] = "ignorar"
                x0, y0, x1, y1 = self.cont[i]["bbox"]
                self.ancho_pt = x1 - x0
                self.e_ancho.delete(0, "end")
                self.e_ancho.insert(0, f"{self.ancho_pt * self.escala:.2f}")
            self.refresca_info()
            self.dibuja()

    # ---------------------------------------------------------------- vista previa
    def dibuja(self):
        cv = self.lienzo
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 20 or not self.cont:
            return
        ex0, ey0, ex1, ey1 = self.cont[0]["bbox"]
        k = min((W - 40) / (ex1 - ex0), (H - 40) / (ey1 - ey0))
        ox, oy = (W - (ex1 - ex0) * k) / 2 - ex0 * k, (H - (ey1 - ey0) * k) / 2 - ey0 * k
        P = lambda p: (p[0] * k + ox, p[1] * k + oy)
        sel = self.tv.selection()
        marcado = int(sel[0]) if sel else -1
        colores = {"exterior": "#58a6ff", "agujero": "#f0883e", "ignorar": "#484f58"}
        for i, c in enumerate(self.cont):
            col = "#ffffff" if i == marcado else colores[self.roles[i]]
            ancho = 3 if i == marcado else 2
            if c["tipo"] == "circulo":
                x, y = P((c["cx"], c["cy"]))
                cv.create_oval(x - c["r"] * k, y - c["r"] * k, x + c["r"] * k, y + c["r"] * k, outline=col, width=ancho)
            else:
                for it in c["items"]:
                    if it[0] == "l":
                        a, b = P(it[1]), P(it[2])
                        cv.create_line(*a, *b, fill=col, width=ancho)
                    else:
                        a, m, b = P(it[1]), P(it[2]), P(it[3])
                        cv.create_line(*a, *m, *b, fill=col, width=ancho, smooth=True)
        cv.create_text(10, 10, anchor="nw", fill=GRIS, font=("Segoe UI", 9),
                       text="azul = exterior · naranja = agujero · gris = ignorado")

    # ---------------------------------------------------------------- paso 2
    def _prims(self):
        import pdf2vba
        e = self.escala_mm()
        ext = [c for c, r in zip(self.cont, self.roles) if r == "exterior"]
        if len(ext) != 1:
            messagebox.showwarning("Plano PDF", "Debe haber exactamente UN contorno con rol «exterior».", parent=self)
            return None
        x0, y0, x1, y1 = ext[0]["bbox"]
        origen = (x0, y1)
        ag = [c for c, r in zip(self.cont, self.roles) if r == "agujero"]
        ag, malos = pdf2vba.validar(ext[0], ag, e)
        if malos:
            self.app.escribe(f"⚠ {len(malos)} «agujeros» descartados para que SolidWorks pueda extruir:", "error")
            for c, motivo in malos[:6]:
                x0_, y0_, x1_, y1_ = c["bbox"]
                self.app.escribe(f"   · {c['tipo']} de {(x1_ - x0_) * e:.1f} × {(y1_ - y0_) * e:.1f} mm: {motivo}", "error")
        return (pdf2vba.primitivas(ext, e, origen), pdf2vba.primitivas(ag, e, origen))

    def genera(self):
        import pdf2vba
        pr = self._prims()
        if pr is None:
            return
        nombre = os.path.splitext(os.path.basename(self.pdf))[0].replace(" ", "_")
        cotas = self.cotas if self.var_cotas.get() else None
        for c in self.cotas:
            c.setdefault("nombre", "cota")
        codigo = pdf2vba.vba(pr[0], pr[1], self.espesor(), nombre, cotas,
                             notas=f"Escala usada: {self.escala_mm():.4f} mm por punto del PDF ({self.motivo}).")
        self.app.codigo.delete("1.0", "end")
        self.app.codigo.insert("1.0", codigo)
        self.app.titulo.configure(text=f"{nombre} (generado)")
        self.app.actual = None
        self.app._pintar_lista()
        self.app.escribe(f"Código VBA generado desde {os.path.basename(self.pdf)}: {len(pr[0])} elementos del contorno, "
                         f"{len(pr[1])} de agujeros, espesor {self.espesor():g} mm. "
                         "Usa «Enviar a SolidWorks» o «Guardar como…».", "ok")
        self.destroy()

    def crea(self):
        import pdf2vba
        pr = self._prims()
        if pr is None:
            return
        self.app.escribe("▶ creando la pieza en SolidWorks…", "tarea")
        esp = self.espesor()

        def hacer():
            part, n, ok = pdf2vba.crear_en_solidworks(pr[0], pr[1], esp)
            print(f"Pieza creada: {n} entidades de croquis, extrusión {'correcta' if ok else 'FALLIDA'} "
                  f"({part.GetTitle}). Queda abierta y sin guardar.")
        self.app.tarea_funcion("crear pieza desde PDF", hacer)

    def ver_cotas(self):
        if self.cotas:
            TablaCotas(self.app, self.cotas, self.pdf)
        else:
            messagebox.showinfo("Plano PDF", "No hay cotas de texto en el PDF.", parent=self)


class TablaCotas(ctk.CTkToplevel):
    """Cotas leidas del texto del PDF: se revisan, se renombran y se pasan al editor como codigo VBA."""

    def __init__(self, app, cotas, pdf):
        super().__init__(app)
        self.app, self.cotas, self.pdf = app, cotas, pdf
        for c in cotas:
            c.setdefault("usar", True)
            c.setdefault("donde", "")
        self.title("Cotas del PDF: " + os.path.basename(pdf))
        self.geometry("1040x560+70+60")
        self.configure(fg_color=FONDO)
        self.after(150, self.lift)
        ctk.CTkLabel(self, text=f"{len(cotas)} cotas leídas del texto de «{os.path.basename(pdf)}»",
                     font=ctk.CTkFont(size=16, weight="bold"), anchor="w").pack(fill="x", padx=16, pady=(14, 0))
        ctk.CTkLabel(self, text="Se han ignorado el marco, el cajetín y los números sueltos. Las repetidas salen "
                     "agrupadas (×N). Doble clic en Nombre o Valor para editar; doble clic en «Usar» para marcar.",
                     text_color=GRIS, anchor="w", wraplength=980, justify="left").pack(fill="x", padx=16)
        estilo = ttk.Style(self)
        estilo.theme_use("clam")
        estilo.configure("Cotas.Treeview", background=BARRA, fieldbackground=BARRA, foreground="#e6edf3",
                         rowheight=28, borderwidth=0, font=("Segoe UI", 10))
        estilo.configure("Cotas.Treeview.Heading", background=PANEL, foreground="#e6edf3", relief="flat",
                         font=("Segoe UI", 10, "bold"))
        estilo.map("Cotas.Treeview", background=[("selected", ACENTO)])
        cols = ("usar", "nombre", "valor", "tipo", "n", "tol", "texto", "donde")
        self.tv = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse", style="Cotas.Treeview")
        for c, t, ancho in (("usar", "Usar", 50), ("nombre", "Nombre (variable)", 170), ("valor", "Valor (mm)", 90),
                            ("tipo", "Tipo", 80), ("n", "Veces", 55), ("tol", "Tolerancia", 90),
                            ("texto", "Texto del plano", 110), ("donde", "Qué es", 330)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=ancho, anchor="w")
        self.tv.pack(fill="both", expand=True, padx=14, pady=(10, 6))
        self.tv.bind("<Double-Button-1>", self.editar)
        self.tv.bind("<space>", lambda e: self.alternar())
        fila = ctk.CTkFrame(self, fg_color="transparent")
        fila.pack(fill="x", padx=14, pady=(2, 12))
        ctk.CTkButton(fila, text="⚙  Pasar al editor: variables de SolidWorks", command=lambda: self.al_editor("variables"),
                      fg_color=ACENTO, hover_color=ACENTO_H).pack(side="left", padx=(0, 8))
        ctk.CTkButton(fila, text="Solo constantes", command=lambda: self.al_editor("constantes"),
                      fg_color="#30363d", hover_color="#3d444d").pack(side="left", padx=(0, 8))
        ctk.CTkButton(fila, text="Guardar JSON…", command=self.json, fg_color="#30363d",
                      hover_color="#3d444d").pack(side="left", padx=(0, 8))
        ctk.CTkButton(fila, text="Marcar todo", width=90, command=lambda: self.marcar(True), fg_color="#30363d",
                      hover_color="#3d444d").pack(side="left", padx=(0, 4))
        ctk.CTkButton(fila, text="Ninguna", width=80, command=lambda: self.marcar(False), fg_color="#30363d",
                      hover_color="#3d444d").pack(side="left")
        ctk.CTkButton(fila, text="Cerrar", command=self.destroy, fg_color="#30363d",
                      hover_color="#3d444d").pack(side="right")
        self.refrescar()

    def refrescar(self):
        self.tv.delete(*self.tv.get_children())
        for i, c in enumerate(self.cotas):
            self.tv.insert("", "end", iid=str(i), values=(
                "sí" if c["usar"] else "no", c["nombre"], f"{c['valor']:g}", c["tipo"],
                f"×{c['n']}" if c["n"] > 1 else "", c["tol"], c["texto"], c.get("donde", "")))

    def marcar(self, valor):
        for c in self.cotas:
            c["usar"] = valor
        self.refrescar()

    def alternar(self):
        for i in self.tv.selection():
            self.cotas[int(i)]["usar"] = not self.cotas[int(i)]["usar"]
        self.refrescar()

    def editar(self, ev):
        fila, col = self.tv.identify_row(ev.y), self.tv.identify_column(ev.x)
        if not fila:
            return
        if col == "#1":
            self.tv.selection_set(fila)
            return self.alternar()
        campo = {"#2": "nombre", "#3": "valor"}.get(col)
        if not campo:
            return
        x, y, w_, h = self.tv.bbox(fila, col)
        e = ttk.Entry(self.tv)
        e.place(x=x, y=y, width=w_, height=h)
        e.insert(0, str(self.cotas[int(fila)][campo]))
        e.focus()

        def ok(_=None):
            v = e.get().strip()
            e.destroy()
            try:
                if campo == "valor":
                    v = float(v.replace(",", "."))
                else:
                    v = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in v) or "cota"
                    if v[0].isdigit():
                        v = "c_" + v
                self.cotas[int(fila)][campo] = v
            except ValueError:
                messagebox.showwarning("Cotas", "Valor no válido.", parent=self)
            self.refrescar()
        e.bind("<Return>", ok)
        e.bind("<FocusOut>", ok)
        e.bind("<Escape>", lambda _: e.destroy())

    def elegidas(self):
        sel = [c for c in self.cotas if c["usar"]]
        if not sel:
            messagebox.showinfo("Cotas", "No hay ninguna cota marcada.", parent=self)
            return None
        nombres = [c["nombre"].lower() for c in sel]
        if len(set(nombres)) != len(nombres):
            messagebox.showwarning("Cotas", "Hay nombres repetidos: cámbialos para que cada variable sea única.",
                                   parent=self)
            return None
        return sel

    def json(self):
        sel = self.elegidas()
        if sel is None:
            return
        base = os.path.splitext(self.pdf)[0] + "_cotas.json"
        p = filedialog.asksaveasfilename(initialfile=os.path.basename(base), initialdir=os.path.dirname(base),
                                         parent=self, defaultextension=".json", filetypes=[("JSON", "*.json")])
        if p:
            datos = {c["nombre"]: {"valor_mm": c["valor"], "tipo": c["tipo"], "veces": c["n"],
                                   "tolerancia": c["tol"], "texto_pdf": c["texto"], "que_es": c.get("donde", "")}
                     for c in sel}
            with open(p, "w", encoding="utf-8") as f:
                json.dump(datos, f, indent=2, ensure_ascii=False)
            self.app.escribe(f"JSON guardado: {p}", "ok")

    def al_editor(self, modo):
        sel = self.elegidas()
        if sel is None:
            return
        import pdfcotas
        nombre = os.path.splitext(os.path.basename(self.pdf))[0].replace(" ", "_")
        self.app.codigo.delete("1.0", "end")
        self.app.codigo.insert("1.0", pdfcotas.a_vba(sel, f"Cotas_{nombre}", modo))
        self.app.titulo.configure(text=f"Cotas_{nombre} (generado)")
        self.app.actual = None
        self.app._pintar_lista()
        self.app.escribe(f"{len(sel)} cotas pasadas al editor ({'con variables globales de SolidWorks' if modo == 'variables' else 'solo constantes'}). "
                         "Usa «Enviar a SolidWorks» para ejecutarlas o «Guardar como…».", "ok")
        self.destroy()


if __name__ == "__main__":
    Taller().mainloop()
