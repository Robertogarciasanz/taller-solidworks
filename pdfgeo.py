"""Paso 1 (geometria): lee los trazados VECTORIALES de un plano PDF y encuentra sus contornos cerrados.

Solo funciona con PDF vectoriales (exportados de CAD). No hace OCR ni lee fotos/escaneos.
Devuelve contornos como lineas, arcos o circulos en coordenadas de la hoja (puntos PDF, y hacia abajo).
"""
import math

import pymupdf as fitz

TOL = 0.2          # puntos PDF: dos extremos a menos de esto se consideran el mismo punto
PT_MM = 25.4 / 72  # 1 punto PDF en mm (si el plano esta a escala 1:1)


def _p(pt):
    return (float(pt.x), float(pt.y))


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _circ3(a, b, c):
    """Circulo por 3 puntos: (cx, cy, r) o None si estan alineados."""
    ax, ay = a; bx, by = b; cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / d
    uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / d
    return ux, uy, math.hypot(ax - ux, ay - uy)


def _bezier(p0, p1, p2, p3, t):
    u = 1 - t
    return (u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1])


def _segmentos(pagina):
    """Lista de segmentos ('l', p0, p1) o ('c', p0, mid, p3) de los trazos continuos (no discontinuos)."""
    segs = []
    for dr in pagina.get_drawings():
        if dr.get("type") == "f":          # solo relleno: puntas de flecha, simbolos
            continue
        dash = dr.get("dashes")
        if dash and dash.strip() not in ("[] 0", "[] 0.0", ""):
            continue                        # lineas ocultas / de eje
        for it in dr["items"]:
            k = it[0]
            if k == "l":
                a, b = _p(it[1]), _p(it[2])
                if _d(a, b) > 1e-6:
                    segs.append(("l", a, b))
            elif k == "c":
                p0, p1, p2, p3 = (_p(it[i]) for i in (1, 2, 3, 4))
                segs.append(("c", p0, _bezier(p0, p1, p2, p3, 0.5), p3))
            elif k == "re":
                r = it[1]
                q = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
                for i in range(4):
                    segs.append(("l", q[i], q[(i + 1) % 4]))
            elif k == "qu":
                q = it[1]
                pts = [_p(q.ul), _p(q.ur), _p(q.lr), _p(q.ll)]
                for i in range(4):
                    segs.append(("l", pts[i], pts[(i + 1) % 4]))
    return segs


def _extremos(s):
    return (s[1], s[2]) if s[0] == "l" else (s[1], s[3])


def _cadenas_cerradas(segs):
    """Une segmentos por sus extremos y devuelve los lazos cerrados (listas de segmentos orientados)."""
    def clave(p):
        return (round(p[0] / TOL), round(p[1] / TOL))
    por_punto = {}
    for i, s in enumerate(segs):
        for p in _extremos(s):
            por_punto.setdefault(clave(p), []).append(i)
    usado = [False] * len(segs)
    lazos = []
    for i0, s0 in enumerate(segs):
        if usado[i0]:
            continue
        usado[i0] = True
        a, b = _extremos(s0)
        cadena = [(s0, False)]
        fin = b
        inicio = a
        ok = False
        for _ in range(len(segs)):
            if _d(fin, inicio) <= TOL * 1.5 and len(cadena) > 1:
                ok = True
                break
            sig = None
            k = clave(fin)
            for kk in [(k[0] + dx, k[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]:
                for j in por_punto.get(kk, ()):
                    if usado[j]:
                        continue
                    e0, e1 = _extremos(segs[j])
                    if _d(e0, fin) <= TOL * 1.5:
                        sig = (j, False, e1); break
                    if _d(e1, fin) <= TOL * 1.5:
                        sig = (j, True, e0); break
                if sig:
                    break
            if not sig:
                break
            usado[sig[0]] = True
            cadena.append((segs[sig[0]], sig[1]))
            fin = sig[2]
        if ok or (len(cadena) > 1 and _d(fin, inicio) <= TOL * 1.5):
            lazos.append(cadena)
        else:
            for s, _ in cadena:           # cadena abierta (cota, eje...): se descarta, pero se libera
                pass
    return lazos


def _area(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def _contorno(cadena):
    """Convierte un lazo en un dict {tipo, ...}: circulo o polilinea con arcos."""
    # orienta cada segmento
    items = []
    for s, inv in cadena:
        if s[0] == "l":
            a, b = (s[2], s[1]) if inv else (s[1], s[2])
            items.append(("l", a, b))
        else:
            a, m, b = (s[3], s[2], s[1]) if inv else (s[1], s[2], s[3])
            items.append(("a", a, m, b))
    pts = [i[1] for i in items]
    xs = [p[0] for p in pts] + [i[-1][0] for i in items]
    ys = [p[1] for p in pts] + [i[-1][1] for i in items]
    # circulo: todo arcos con el mismo centro y radio, o muchas lineas cortas sobre un circulo
    if len(items) >= 8 or all(i[0] == "a" for i in items):
        todos = pts + [items[len(items) // 2][-2] if items[len(items) // 2][0] == "a" else items[len(items) // 2][2]]
        c = _circ3(pts[0], pts[len(pts) // 3], pts[2 * len(pts) // 3]) if len(pts) >= 3 else None
        if c and c[2] > 0.3 and all(abs(math.hypot(p[0] - c[0], p[1] - c[1]) - c[2]) < max(TOL * 2, 0.012 * c[2]) for p in pts):
            return dict(tipo="circulo", cx=c[0], cy=c[1], r=c[2], area=math.pi * c[2] ** 2,
                        bbox=(c[0] - c[2], c[1] - c[2], c[0] + c[2], c[1] + c[2]))
    poly = []
    for i in items:
        poly.append(i[1])
        if i[0] == "a":
            poly.append(i[2])
    return dict(tipo="contorno", items=items, area=abs(_area(poly)),
                bbox=(min(xs), min(ys), max(xs), max(ys)))


def leer_geometria(ruta, pagina=0):
    """-> dict(ancho, alto, contornos=[...]) ordenados por area decreciente."""
    doc = fitz.open(ruta)
    pg = doc[pagina]
    segs = _segmentos(pg)
    contornos = [_contorno(c) for c in _cadenas_cerradas(segs)]
    W, H = pg.rect.width, pg.rect.height
    # fuera: marco de la hoja y cajetin (contornos que ocupan casi toda la hoja)
    contornos = [c for c in contornos if c["area"] > 4
                 and (c["bbox"][2] - c["bbox"][0]) < 0.93 * W and (c["bbox"][3] - c["bbox"][1]) < 0.93 * H]
    contornos.sort(key=lambda c: -c["area"])
    return dict(ancho=W, alto=H, contornos=contornos, n_segmentos=len(segs))


def textos_numericos(ruta, pagina=0):
    """Numeros que aparecen como texto en la hoja (posibles cotas), con su posicion."""
    import re
    doc = fitz.open(ruta)
    out = []
    for x0, y0, x1, y1, txt, *_ in doc[pagina].get_text("words"):
        t = txt.replace(",", ".").strip("Ø⌀ø()R")
        if re.fullmatch(r"\d{1,4}(\.\d{1,3})?", t):
            out.append((float(t), (x0 + x1) / 2, (y0 + y1) / 2))
    return out


def datos_cajetin(ruta, pagina=0):
    """Escala (a, b) escrita en el cajetin ("ESCALA:1:2") y espesor ("Chapa de acero 2 mm") si aparecen."""
    import re
    doc = fitz.open(ruta)
    texto = doc[pagina].get_text()
    esc = None
    m = re.search(r"(?i)escala\s*:?\s*(\d+(?:[.,]\d+)?)\s*:\s*(\d+(?:[.,]\d+)?)", texto)
    if m:
        esc = (float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", ".")))
    esp = None
    for ln in texto.splitlines():
        if re.search(r"(?i)chapa|espesor|grosor|e\s*=", ln) and not re.search(r"(?i)expresan", ln):
            m = re.search(r"(\d+(?:[.,]\d+)?)\s*mm", ln, re.I)
            if m:
                esp = float(m.group(1).replace(",", "."))
                break
    return dict(escala=esc, espesor=esp)


def sugerir_escala(contorno_exterior, numeros, escala_texto=None):
    """Escala mm por punto PDF. Prueba las escalas normalizadas y elige la que hace que el ancho o el alto
    del contorno coincidan con alguna cota escrita en el plano."""
    if escala_texto:
        a, b = escala_texto
        if a > 0 and b > 0:
            return PT_MM * b / a, f"cajetín: ESCALA {a:g}:{b:g}"
    x0, y0, x1, y1 = contorno_exterior["bbox"]
    lados = [x1 - x0, y1 - y0]
    valores = [n[0] for n in numeros]
    mejor = (None, 1e9)
    for k in (1, 2, 5, 10, 20, 50, 0.5, 0.2, 0.1):          # escala de dibujo 1:k  /  k:1
        for razon in (k, 1 / k):
            mm_pt = PT_MM * razon
            for lado in lados:
                est = lado * mm_pt
                for v in valores:
                    err = abs(est - v) / max(v, 1e-9) + 0.004 * abs(math.log10(razon))   # prefiere escalas cercanas a 1:1
                    if err < mejor[1]:
                        mejor = (mm_pt, err)
    if mejor[0] is not None and mejor[1] < 0.04:
        return mejor[0], f"coincide con una cota escrita (error {mejor[1] * 100:.1f} %)"
    return PT_MM, "sin coincidencia con las cotas: se asume escala 1:1"
