# Informe de pruebas: recetas STL/PDF → FreeCAD 1.1

Fecha: 19/10/2026. Prueba: `py probar_recetas.py` (genera la receta, la valida y la construye con
`fc_constructor.py` en freecadcmd). Tolerancias: volumen < 2 %, caja envolvente ±0,50 mm.
Para los PDF, la caja de FreeCAD se compara con las cotas principales del plano y, si hay STL de la misma pieza, también el volumen.
Recetas y piezas en `freecad\recetas_prueba\`.

| Archivo | Operaciones (receta) | Volumen original (mm³) | Volumen FreeCAD (mm³) | Error | Caja FreeCAD (mm) | Estado | Qué falta |
|---|---|---|---|---|---|---|---|
| caja66.STL | 1 saliente + 9 cortes (Alzado), 12 redondeos R7,00 | 87930,70 | 87511,90 | -0,48 % | 120,00 x 88,20 x 40,00 (±0,11) | bien | — |
| Brazo_engranaje.STL | 1 saliente (0–20) + 1 corte del alma (10–21) | 154886,30 | 155191,00 | +0,20 % | 192,00 x 103,00 x 20,00 (±0,00) | bien | — |
| Caja_asas.STL | 3 salientes (fondo 1,50 + paredes + borde), 8 redondeos | 86685,20 | 86530,30 | -0,18 % | 200,00 x 60,00 x 120,00 (±0,00) | bien | La reconstruye como sólido extruido, no como chapa |
| Brazo_engranaje.pdf | 1 saliente (0–20, 4 agujeros) + 1 corte del alma (10–21), 3 redondeos | 154886,30 (STL) | 155053,00 | +0,11 % | 192,00 x 103,00 x 20,00 (cotas 148+R22+R22 = 192; espesor 20, alma 10) | bien | Los 3 redondeos (R10,00, R9,40 y R9,10) salen de arcos del croquis convertidos en esquina; habría que revisar si son esos radios o R11/R16 |
| caja23.PDF | 1 saliente (0–40, 4 taladros de las orejetas) + 1 corte del vaciado (3,92–41), 2 redondeos R5,80 | 87930,70 (caja66.STL, otra versión) | 95225,30 | +8,30 % (solo orientativo) | 120,02 x 87,63 x 40,00 (cotas 120 x 80 + orejetas x 40) | bien (medidas); limitación (interior) | El plano no da profundidades interiores: tabiques, alojamiento, ventanas laterales y rebaje no se modelan. El fondo se supone igual a la pared (3,92; la caja real tiene 3,00) |
| Tapa_caja.pdf | 1 saliente (0–14,99), 2 redondeos | — | 383808,90 | — | 204,95 x 125,06 x 14,99 | limitación | Es chapa (1,50 con faldón de 15): el plano no tiene cotas y en planta solo hay líneas de pliegue, así que sale un bloque macizo con las medidas exteriores. Falta un lector de chapa (espesor + faldón) |

## Cómo lee ahora los PDF (`receta_pdf.receta_por_vistas`)

1. Toma los trazos visibles (negros, continuos, del grosor de arista) y los agrupa en vistas.
2. La vista principal es la que tiene más cotas cerca; si no hay cotas, la que tiene otra vista alineada (así se descarta la isométrica). La escala sale del cajetín.
3. Engorda los trazos 0,25 pt y toma como caras los huecos que quedan entre ellos. Así se cierran también las uniones tangentes o en T: con `pdfgeo`, el alma del brazo y el interior de caja23 se perdían, y por eso antes salían 69 x 44 y 60 x 60 mm.
4. La silueta va como saliente base. Los lazos aislados que no contienen nada son agujeros pasantes.
5. La profundidad sale de la vista lateral (o de la superior/inferior) y se ajusta a la cota escrita si está a menos del 1,5 %.
6. Escalones: si la vista lateral tiene un nivel intermedio, las caras que no rodean un agujero (el alma) se cortan hasta ese nivel.
7. Vaciado: si dentro hay un componente grande con varios lazos (una caja), se corta su contorno desde el fondo.
8. Si la lectura por vistas falla, usa el método antiguo de contornos de `pdfgeo`.

## Pendiente

- caja23: modelar los detalles interiores necesita profundidades que el plano no da (o una sección).
- Tapa_caja y piezas de chapa: hace falta un lector específico.
- Brazo PDF: comprobar los radios de los redondeos finales.
- El asistente de PDF de la app (botón «asistente») sigue usando el método de contornos. El método por vistas está en el botón «PDF → pieza (automático)».
