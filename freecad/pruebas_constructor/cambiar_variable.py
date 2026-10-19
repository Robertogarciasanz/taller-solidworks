# -*- coding: utf-8 -*-
"""Ejecutar con freecadcmd. Abre FC_ARCHIVO, pone la variable FC_VAR = FC_VALOR en la hoja
"Variables", recomputa e imprime 'RESULTADO {...}' con volumen, caja, valido y errores.
No guarda el archivo."""
import json, os, sys
import FreeCAD as App

res = {"ok": False, "volumen": 0, "caja": [], "valido": False, "errores": []}
try:
    doc = App.openDocument(os.environ["FC_ARCHIVO"])
    hoja = doc.getObjectsByLabel("Variables")[0]
    celda = hoja.getCellFromAlias(os.environ["FC_VAR"])
    hoja.set(celda, os.environ["FC_VALOR"])
    doc.recompute()
    malos = [o.Label for o in doc.Objects if "Invalid" in o.State or "Error" in o.State]
    body = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"][0]
    sh = body.Shape
    bb = sh.BoundBox
    res = {"ok": not malos, "volumen": round(sh.Volume, 4),
           "caja": [round(c, 4) for c in (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)],
           "valido": bool(sh.isValid()), "errores": malos}
    App.closeDocument(doc.Name)
except Exception as e:
    res["errores"].append("%s: %s" % (type(e).__name__, e))
sys.stdout.write("RESULTADO " + json.dumps(res) + "\n")
