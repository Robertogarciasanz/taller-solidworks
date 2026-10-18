"""Lee las cotas de un plano (PDF o foto) con Google Gemini.

La clave va en la variable de entorno GEMINI_API_KEY (setx). Si el proceso se abrio antes del setx,
se lee del registro (HKCU\\Environment).
Devuelve las cotas en el mismo formato que pdfcotas.leer_cotas, para usar la misma TablaCotas.
"""
import json
import mimetypes
import os
import unicodedata

MODELO = "gemini-flash-latest"

PROMPT = """Eres un delineante experto en SolidWorks. Lee este plano y devuelve SOLO JSON con:
{"pieza": str, "material": str|null, "espesor_mm": num|null,
 "cotas": [{"nombre": str, "valor": num, "tipo": "lineal|diametro|radio|angulo", "veces": int,
            "texto": str, "que_mide": str, "vista": str}],
 "operaciones_sugeridas": [str]
}
- nombre: variable corta en minusculas, sin tildes ni espacios (largo, ancho, alto, r_esquina, d_agujero...), unica.
- texto: la cota tal como aparece en el plano (R10,00; 2xØ4; 120,00).
- veces: cuantas veces se repite (2x, 4x...), 1 si no se indica.
- Incluye las cotas de notas y del cajetin (espesor de chapa, radios de plegado...).
- operaciones_sugeridas: orden SolidWorks con pocas operaciones: saliente base, cortes, matrices, redondeos al final.
Usa solo cotas que aparecen en el plano; no inventes."""


def a_json(texto):
    """Primer objeto JSON de la respuesta de Gemini (a veces añade texto o un segundo bloque detrás)."""
    texto = (texto or "").strip()
    if texto.startswith("```"):
        texto = texto.split("\n", 1)[1].rsplit("```", 1)[0]
    i = min([k for k in (texto.find("{"), texto.find("[")) if k >= 0], default=0)
    return json.JSONDecoder().raw_decode(texto[i:])[0]


def _clave():
    if os.environ.get("GEMINI_API_KEY"):
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            os.environ["GEMINI_API_KEY"] = winreg.QueryValueEx(k, "GEMINI_API_KEY")[0]
    except OSError:
        raise SystemExit("Falta la clave de Gemini: crea la API key en aistudio.google.com y guárdala con "
                         "setx GEMINI_API_KEY \"tu_clave\" en PowerShell; luego reinicia el Taller.")


def leer(ruta, modelo=MODELO):
    """JSON tal como lo devuelve Gemini."""
    from google import genai
    from google.genai import types
    _clave()
    mime = mimetypes.guess_type(ruta)[0] or "application/pdf"
    with open(ruta, "rb") as f:
        datos = f.read()
    cliente = genai.Client()
    r = cliente.models.generate_content(
        model=modelo,
        contents=[types.Part.from_bytes(data=datos, mime_type=mime), PROMPT],
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1))
    return a_json(r.text)


def _limpio(txt):
    txt = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode().lower()
    txt = "".join(ch if ch.isalnum() else "_" for ch in txt).strip("_")
    while "__" in txt:
        txt = txt.replace("__", "_")
    return ("c_" + txt if txt[:1].isdigit() else txt) or "cota"


def a_cotas(datos):
    """Convierte el JSON de Gemini a la lista de cotas de TablaCotas."""
    cotas, usados = [], {}
    for c in datos.get("cotas") or []:
        try:
            valor = float(str(c.get("valor")).replace(",", "."))
        except (TypeError, ValueError):
            continue
        base = _limpio(c.get("nombre") or c.get("que_mide"))
        usados[base] = usados.get(base, 0) + 1
        nombre = base if usados[base] == 1 else f"{base}_{usados[base]}"
        vista = c.get("vista") or ""
        cotas.append({"nombre": nombre, "valor": valor, "tipo": c.get("tipo") or "lineal",
                      "n": int(c.get("veces") or 1), "tol": "", "texto": c.get("texto") or f"{valor:g}",
                      "donde": (c.get("que_mide") or "") + (f" ({vista})" if vista else ""), "usar": True})
    return cotas


def leer_plano(ruta, guardar_json=True):
    """(cotas, datos). Guarda <plano>_gemini.json junto al plano."""
    datos = leer(ruta)
    if guardar_json:
        with open(os.path.splitext(ruta)[0] + "_gemini.json", "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=1, ensure_ascii=False)
    return a_cotas(datos), datos


if __name__ == "__main__":
    import sys
    cotas, datos = leer_plano(sys.argv[1], guardar_json=False)
    for c in cotas:
        print(f"{c['nombre']:<20} {c['valor']:>8g}  {c['tipo']:<9} x{c['n']}  {c['donde']}")
    print("\n".join("- " + o for o in datos.get("operaciones_sugeridas") or []))
