# Lo aprendido el 18/10/2026: Gemini + SolidWorks

Sesión larga: Google AI Studio (Gemini) conectado al Taller SolidWorks para pasar de un **plano PDF a una pieza**
y de la **pieza a un plano A4 en PDF**, además de un **servidor MCP** para manejar SolidWorks desde Claude Code.

---

## 1. Qué se ha construido

| Archivo (en `taller-solidworks\`) | Qué hace |
|---|---|
| `gemini_plano.py` | Llama a Gemini y lee las cotas de un plano PDF o una foto. `a_json()` lee la respuesta aunque traiga texto de más. |
| `plano_a_macro.py` | **Plano → receta (Gemini) → macro VBA → pieza en SolidWorks → comprobación.** Opciones: `--rondas N`, `--original x.SLDPRT`, `--misma-receta`. |
| `biblioteca_sw.bas` | Funciones VBA ya probadas (skill solidworks-macro-modelado) que usan las macros generadas. |
| `planos_gemini.py` | **Pieza → plano A4 en PDF.** Gemini elige las cotas, SolidWorks dibuja (con `lib/swplanos.py`) y Gemini revisa la colocación, la vista de detalle y la sección parcial. |
| `mcp_solidworks.py` | Servidor MCP «solidworks»: estado, abrir, medir, captura, ejecutar_macro, plano_a_pieza, generar_plano, cerrar_sin_guardar, traer_al_frente. Registrado en Claude Code (usuario). |
| `ejemplos\brazo_engranaje.json` | Receta comprobada contra la pieza real; Gemini la recibe como ejemplo resuelto. |
| Taller (`TallerSolidWorks.exe`) | Nuevo botón «Leer plano con Gemini». «SolidWorks al frente», arreglado. |
| `Abrir_Taller.swp` | Rehecho; el botón de SolidWorks apunta al módulo `Macro11`. |

## 2. Gemini (Google AI Studio)

- **La clave** se guarda con `setx GEMINI_API_KEY "..."` y nunca se pega en el chat. Los programas abiertos antes del
  `setx` no la ven: se lee del registro (`HKCU\Environment`).
- **Modelos**: `gemini-2.5-flash` ya no está disponible para cuentas nuevas (404). `gemini-pro-latest` da error de cuota en el plan
  gratuito (429). Se usa `gemini-flash-latest` y, si está saturado (503), los de reserva `gemini-3-flash-preview` y
  `gemini-flash-lite-latest`, **con un solo intento por modelo** (antes se perdían 30 s reintentando).
- Lee muy bien **cotas sueltas** (caja23: 17 de 17) y **no se inventa** las que no están (Tapa_caja).
- Falla en **cotas encadenadas y ángulos**: en el brazo leyó mal la cota 148 y el colisón curvo (puso 25–65° cuando
  era 0–40°). Lecciones añadidas al prompt:
  - una cota del cubo al extremo de una ranura **fija esa coordenada** (60 → extremo en (60, 0));
  - el ángulo de una ranura en arco se comprueba con las cotas lineales;
  - las cotas encadenadas se reparten (148 = 88 + 60).
- **Su autorrevisión no es fiable**: dijo «coincide» con un 9 % menos de volumen y, en otra ronda, empeoró la pieza.
  → Por defecto, una sola lectura. Con un original, se manda el **volumen** y no se acepta si difiere más de un 2 %.
- **Aprender con ejemplos**: guardar recetas comprobadas en `ejemplos\` y pasárselas en el prompt funcionó mejor que
  las reglas: sin su propio ejemplo ya acertó el colisón y el ancho (192 mm).
- **No sirve para dibujar planos** con medidas exactas. Su papel bueno es **decidir** (qué cotas, dónde ponerlas, si
  hace falta detalle o sección), y que **SolidWorks dibuje**.

## 3. Generar la pieza (receta → VBA)

- La receta describe la pieza con formas que Python convierte en geometría **exacta**:
  - `caja`, `cilindro`;
  - `contorno`: círculos unidos por **rectas tangentes**, **arcos cóncavos R** o **arcos convexos concéntricos** (`arco_centro`);
  - `ranura` y `ranura_arco`: **ranuras nativas** de SolidWorks (`CreateSketchSlot`);
  - `spline` (`CreateSpline2`);
  - `equidistancia` (el lóbulo = colisón desplazado 11 mm; para splines, `SketchOffset2`);
  - `redondeo` en el eje X, Y o Z.
- **Orden**: se respeta el que da Gemini (cuerpo → vaciado → tabiques → ventanas/agujeros). Si van todos los salientes primero,
  el vaciado se come los tabiques. **Los redondeos van al final**, de menor a mayor radio. Si hay una caja vaciada,
  el redondeo interior R−e se añade solo (si no, el R10 exterior atraviesa la pared).
- **Comprobar cada operación** (`OpAx`): que vaya del inicio al final en su eje. Las caras coplanarias se funden con caras
  existentes y «se salen» del tramo: se comprueban las **tapas**, no todas las caras.
- Si un corte coincide con aristas existentes, falla: se repite **0,01 mm mayor**.
- **Contorno de círculos**:
  - los círculos van en sentido antihorario y, si llegan en horario, se invierten;
  - los extremos se dibujan en antihorario y los arcos de unión cóncavos en horario;
  - si un arco de unión toca el círculo «por detrás», se hace tangente a la **recta** (así queda el R44 del brazo).
- **Resultado**: con la receta correcta, el brazo sale **idéntico al original (155,1 cm³, 192 × 103 × 20 mm)**. caja23 sale bien de forma, pero sin las orejetas exteriores. La Tapa_caja no tiene medidas en el plano (el original mide 205 × 125).

## 4. Planos en PDF

- Para que haya cotas en el plano, **los croquis tienen que estar acotados**: radio en los arcos del contorno
  (puestos **al cerrar el contorno**, no arco a arco, porque así rompían el alma) y posición de las ranuras.
- **Sin cotas repetidas**: en el alma no se acotan los radios que ya da otra operación (R20 = Ø40/2, R22 = 44/2, R82 = 60 + 22).
- **Rutas con `\`**: con `/`, `CreateDrawViewFromModelView3` da «Error interno».
- **Separación entre vistas**: `GAP` pasa de 22 a 32 mm; la isométrica, con 1,5 × GAP (con 2 × GAP quedaba diminuta).
- **Regla fija**: el texto de una cota queda a ≤ 15 mm de **su** vista (si no, sus líneas cruzan otras vistas). El
  auditor de planos no lo detectaba.
- **Gemini coloca las cotas**: ve la imagen del plano y la lista de cotas y propone movimientos. Solo se conservan si **bajan los
  defectos** del auditor; si no, se deshacen.
- **Vista de detalle**: círculo en la vista madre + `CreateDetailViewAt4` y se pasan las cotas pequeñas allí.
  **Sección parcial**: rectángulo + `CreateBreakOutSection`, **siempre al final**. Implementadas; aún sin probar
  porque SolidWorks se colgó.
- La nota de parámetros solo con valores reales (Gemini se inventó «pared de 4 mm»).

## 5. SolidWorks por COM: trampas encontradas

| Síntoma | Causa | Solución |
|---|---|---|
| Las piezas «se cierran solas» | `OpenDoc6` las abre **invisibles** y SolidWorks las cierra con el dibujo que las usa | `doc.Visible = True` al abrir (herramienta `abrir` del MCP) |
| Desaparece Pieza1 | SolidWorks cierra la Pieza1 vacía de arranque al abrir otro documento | Normal |
| Ninguna macro se ejecuta (RunMacro2 = FALLO, error 0) | Un error de compilación VBA deja el motor atascado | Reiniciar SolidWorks |
| «Variable no definida» | `Dim` de módulo escrito después de los `Sub` | Los `Dim` de módulo, siempre arriba |
| No deja sobrescribir el `.swp` | SolidWorks bloquea la macro ya ejecutada | Nombre nuevo (`_macro_2.swp`…) |
| «El objeto invocado ha desconectado» | Referencia guardada de un documento que se cerró o reactivó | Volver a pedir `ActiveDoc` después de `ActivateDoc3` |
| Se usaba Pieza1 vacía como pieza del plano | Al cerrar el dibujo, la activa pasa a Pieza1 | Si la activa está vacía, usar la única pieza con sólido |
| `tareas.val` falla («NoneType… CDispatch») | Falta preparar el enlace COM | Conectar con `tareas._sw()` |
| «SolidWorks al frente» no hacía nada | Windows bloquea `SetForegroundWindow` desde segundo plano | `AttachThreadInput` + `BringWindowToTop` |
| APPCRASH en `ntdll` (FaultTolerantHeap) | Memoria dañada tras horas de llamadas COM | Reiniciar SolidWorks de vez en cuando en sesiones largas |
| Al probar varias versiones se mezclan piezas | Cada prueba abría una pieza nueva | Cerrar la anterior sin guardar antes de cada prueba; una pieza cada vez |

## 6. Programación (errores míos que no repetir)

- Al editar Python **desde un heredoc** con `"\n"` dentro de cadenas, se convierte en un salto real y rompe el
  archivo (pasó 4 veces). → Para código con caracteres de escape, editar con la herramienta de edición, no con scripts.
- `str.format` con plantillas que llevan `{}` de JSON falla → `replace` del marcador.
- MCP 2.x: `FastMCP` se llama ahora `MCPServer` (`from mcp.server.mcpserver import MCPServer, Image`). La salida
  estándar es del protocolo: todo lo que imprimen los módulos se recoge con `redirect_stdout`.
- Comprobar **siempre** con medidas (sólidos, volumen, tamaño), con una captura y, si existe, con el **original**.
  «Se parece» no basta.

## 7. Forma de trabajar que pide el usuario

- **Un modelo cada vez** y **preguntar tras cada uno** para que lo revise; no mezclar piezas abiertas.
- **Corregir mis propios errores** antes de enseñar nada: medir, mirar la captura y auditar el PDF.
- **Ir más rápido**: menos reintentos y no rehacer lo que ya funciona.
- Usar las herramientas buenas de SolidWorks: spline, equidistancia, ranuras, vista de detalle, sección parcial.
- Redondeos siempre al final. Trabajar sobre **copias** de sus archivos.
- No llenar el Taller de botones: lo que quiere es **un solo botón: PDF → pieza** (pendiente).

## 8. Hecho al final del día

- **Planos de la bici** (15 hojas, carpeta `diseños 3d\Bicicleta_planos_2026-10-18\planos`): nombre y archivo de
  cada pieza, secciones parciales (ruedas, cuadro, bielas, cassette, cambio, eje y buje) y **JSON de medidas
  incrustado en cada PDF** y suelto al lado. 10 de 15 hojas con 0 defectos (sillín 11, bielas 5, cuadro 4).
- Auditor por hoja (antes sumaba todas las hojas de la carpeta).
- **Plugin de Claude Code** `taller-solidworks` (MCP + skill + /pdf-a-pieza, /plano-de-pieza, /planos-carpeta).
- `ida_y_vuelta.py`: pieza → PDF → pieza y comparación de volumen y tamaño.
- Notas en dibujos: `InsertNote` devuelve un objeto sin información de tipo → `_FlagAsMethod("GetAnnotation")`.
- Cualquier SaveAs del PDF borra lo incrustado → nombres y secciones primero, medidas al final.

## 9. Pendiente (para retomar)

0. **PRIMERO: bucle automático PDF → pieza hasta que COINCIDA.** El usuario probó «Plano PDF → pieza» con
   Bielas_platos: el PDF antiguo (sin medidas) dio 1 disco + bielas en línea (431 cm³, 25 mm de ancho; la real
   mide 511,6 cm³ y 414 × 208 × 256). Con el PDF nuevo (medidas incrustadas) salen 2 bielas, pedales y eje, pero
   con 2 sólidos y 333 cm³. Hacer: construir → `comparar_con_pdf` → devolver a Gemini la diferencia exacta →
   corregir la receta → repetir (máx. 4) → si COINCIDE, guardar la receta en el JSON del PDF.
   El Taller ya solo tiene las dos direcciones (PDF → pieza; pieza → planos); la macro generada pasa a
   «Mis macros» y al editor, y el registro dice COINCIDE / NO COINCIDE.

1. ✅ **Ida y vuelta del brazo APROBADA**: pieza → PDF (con receta incrustada) → pieza = 155,110 cm³ y
   192 × 103 × 20 mm, 0,00 % de diferencia. Falta la 2.ª prueba con una pieza de la bici sin receta
   (rodamiento: 3,619 cm³). La rueda trasera falló al regenerarse (cota sin `GetPosition` en
   `acercar_a_su_vista`: falta un try) y quedó con dos cortes (376 y 334 mm).
2. Rueda trasera: comprobar la sección corregida (profundidad = radio real) y llevar las cotas de los **piñones**
   a la sección.
3. Recetas verificadas para las piezas de la bici (Gemini + medidas exactas → construir → si el volumen cuadra,
   guardar la receta en el JSON).
4. **Recompilar el exe** del Taller (ahora lleva el motor anterior, sin medidas incrustadas ni secciones).
5. Sillín (curvas): medidas generales y ángulos. Horquilla: faltan cotas.
6. caja1: la sección parcial tumbó SolidWorks (el detalle sí funciona). caja23: orejetas. Tapa_caja: 205 × 125.
7. `Pieza5.SLDPRT` de la bici quedó fuera (¿resto de pruebas?).
