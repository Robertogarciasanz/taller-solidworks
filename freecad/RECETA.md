# Receta de pieza (formato común SolidWorks / FreeCAD)

Un archivo `.receta.json` describe una pieza como la modelaría una persona en SolidWorks:
variables principales, croquis sobre un plano, saliente base, cortes y redondeos al final.
Lo generan los lectores (PDF, STL) y lo consumen los constructores
(`freecad/fc_constructor.py` para FreeCAD; más adelante uno para SolidWorks).

Unidades: mm y grados. Planos con la convención de SolidWorks (Y hacia arriba):

| plano    | croquis x | croquis y | normal |
|----------|-----------|-----------|--------|
| `Alzado` | +X        | +Y        | +Z     |
| `Planta` | +X        | -Z        | +Y     |
| `Lateral`| -Z        | +Y        | +X     |

```json
{
  "version": 1,
  "nombre": "caja66",
  "origen": "STL caja66.STL",
  "variables": {"espesor": 10, "ancho_exterior": 200},
  "operaciones": [
    {"tipo": "saliente", "nombre": "Saliente-Extruir1", "plano": "Alzado",
     "desde": 0, "hasta": 40,
     "perfiles": [
       [["L", [0, 0], [200, 0]], ["A", [190, 10], [200, 10], [190, 20], 1], ["L", [190, 20], [0, 20]],
        ["L", [0, 20], [0, 0]]],
       [["C", [50, 10], 4]]
     ],
     "cotas": {"hasta": "espesor"}},
    {"tipo": "corte", "nombre": "Cortar-Extruir1", "plano": "Alzado",
     "desde": 2, "hasta": 41, "pasante": false, "perfiles": [ ... ]}
  ],
  "redondeos": [{"radio": 3, "puntos": [[10, 0, 40], [190, 0, 40]]}]
}
```

- `operaciones` en orden. `tipo`: `saliente` (Pad / Extruir saliente) o `corte` (Pocket / Extruir corte).
- `desde`/`hasta`: distancias a lo largo de la normal del plano (el croquis se coloca en `desde`).
  `pasante: true` = corte a través de todo.
- `perfiles`: lista de lazos cerrados; cada lazo es una lista de entidades encadenadas:
  - `["L", [x1, y1], [x2, y2]]` línea
  - `["A", [cx, cy], [xi, yi], [xf, yf], s]` arco de centro c de inicio a fin; `s` = 1 antihorario, -1 horario
  - `["C", [cx, cy], r]` círculo (lazo de una sola entidad)
  En un mismo croquis, los lazos interiores son agujeros (como en SolidWorks).
- `cotas` (opcional): parámetro de la operación -> nombre de variable (`hasta`, `desde`); el constructor
  enlaza ese valor a la variable (hoja de cálculo en FreeCAD, ecuación en SolidWorks).
- `redondeos`: al final. Cada uno redondea las aristas más cercanas a los `puntos` (coordenadas 3D del
  modelo terminado) con ese radio.
- `variables`: solo las principales (ver memoria "macros: modelado eficaz").
