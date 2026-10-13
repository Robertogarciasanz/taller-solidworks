"""Escribe una macro .swp de SolidWorks a partir de codigo VBA, sin abrir SolidWorks.

Usa un .swp real como plantilla (Abrir_Taller.swp), sustituye el codigo de su modulo
y quita la cache compilada para que SolidWorks recompile desde el texto.
"""
import os
import struct

import olefile
import pythoncom
import pywintypes
from oletools.olevba import decompress_stream

def _buscar_plantilla():
    """plantilla_macro.swp: un .swp grabado por SolidWorks (trae las referencias SldWorks/SwConst)."""
    import sys
    aqui = [getattr(sys, "_MEIPASS", ""), os.path.dirname(os.path.abspath(__file__)), r"C:\SOLIDWORKS Data\Taller"]
    for d in aqui:
        p = os.path.join(d, "plantilla_macro.swp")
        if d and os.path.exists(p):
            return p
    return os.path.join(aqui[-1], "plantilla_macro.swp")


PLANTILLA = _buscar_plantilla()
VBA_DIR = "apc/The VBA Project/_VBA_Project/VBA"
CRLF, LF = chr(13) + chr(10), chr(10)


# ------------------------------------------------------------ compresion MS-OVBA
def _comprimir_chunk(datos):
    out = bytearray()
    pos = 0
    n = len(datos)
    while pos < n:
        flag_pos = len(out)
        out.append(0)
        flag = 0
        for bit in range(8):
            if pos >= n:
                break
            # bits para offset segun la posicion actual dentro del chunk
            bits = max((pos - 1).bit_length(), 4) if pos > 0 else 4
            len_mask = 0xFFFF >> bits
            max_len = len_mask + 3
            max_off = 1 << bits
            mejor_l, mejor_o = 0, 0
            if pos >= 1:
                ini = max(0, pos - max_off)
                for cand in range(pos - 1, ini - 1, -1):
                    l = 0
                    while pos + l < n and l < max_len and datos[cand + l] == datos[pos + l]:
                        l += 1
                    if l > mejor_l:
                        mejor_l, mejor_o = l, pos - cand
                        if l == max_len:
                            break
            if mejor_l >= 3:
                tok = ((mejor_o - 1) << (16 - bits)) | (mejor_l - 3)
                out += struct.pack("<H", tok)
                flag |= 1 << bit
                pos += mejor_l
            else:
                out.append(datos[pos])
                pos += 1
        out[flag_pos] = flag
    return bytes(out)


def comprimir(datos):
    res = bytearray(b"\x01")
    for i in range(0, len(datos), 4096):
        trozo = datos[i:i + 4096]
        c = _comprimir_chunk(trozo)
        if len(c) > 4095:
            raise ValueError("chunk no comprimible")
        res += struct.pack("<H", 0xB000 | (len(c) + 2 - 3)) + c
    return bytes(res)


# ------------------------------------------------------------ lectura de la plantilla
def _recorrer(o, ruta=""):
    """(ruta, es_storage) de todo el contenido, padres antes que hijos."""
    for p in o.listdir(streams=True, storages=True):
        yield "/".join(p), o.get_type("/".join(p)) == olefile.STGTY_STORAGE


def _parchear_dir(dir_dec, modulo):
    """Pone MODULEOFFSET = 0 en el modulo indicado (el flujo pasa a ser solo texto)."""
    b = bytearray(dir_dec)
    i = 0
    actual = None
    while i + 6 <= len(b):
        rid, size = struct.unpack_from("<HI", b, i)
        if rid == 0x0019:
            actual = bytes(b[i + 6:i + 6 + size]).decode("cp1252", "replace")
        if rid == 0x0031 and actual == modulo:
            struct.pack_into("<I", b, i + 6, 0)
        i += 6 + size + (2 if rid == 0x0009 else 0)
    return bytes(b)


def nombre_modulo(dir_dec):
    """Primer modulo que no es ThisLibrary."""
    d, i = dir_dec, 0
    while i + 6 <= len(d):
        rid, size = struct.unpack_from("<HI", d, i)
        if rid == 0x0019:
            n = bytes(d[i + 6:i + 6 + size]).decode("cp1252", "replace")
            if n != "ThisLibrary":
                return n
        i += 6 + size + (2 if rid == 0x0009 else 0)
    raise ValueError("la plantilla no tiene modulo")


def leer_bas(ruta):
    """Texto VBA de un .bas sin las lineas Attribute (las pone el escritor)."""
    b = open(ruta, "rb").read()
    try:
        t = b.decode("utf-8-sig")
    except UnicodeDecodeError:
        t = b.decode("cp1252")
    return LF.join(l for l in t.replace(CRLF, LF).split(LF) if not l.startswith("Attribute VB_"))


def bas_a_swp(ruta_bas, destino=None):
    """Convierte un .bas en un .swp que SolidWorks ejecuta (con Sub main)."""
    destino = destino or os.path.splitext(ruta_bas)[0] + ".swp"
    return escribir_swp(leer_bas(ruta_bas), destino)


def _offset_modulo(dir_dec, modulo):
    d, i, act = dir_dec, 0, None
    while i + 6 <= len(d):
        rid, size = struct.unpack_from("<HI", d, i)
        if rid == 0x0019:
            act = bytes(d[i + 6:i + 6 + size]).decode("cp1252", "replace")
        if rid == 0x0031 and act == modulo:
            return struct.unpack_from("<I", d, i + 6)[0]
        i += 6 + size + (2 if rid == 0x0009 else 0)
    raise ValueError("modulo no encontrado en la plantilla")


def escribir_swp(codigo, destino, plantilla=PLANTILLA):
    """codigo: texto VBA (con Sub main). Crea destino (.swp) a partir de la plantilla.

    Se conserva todo el contenedor y la cabecera del modulo; solo se sustituye el texto
    comprimido. SolidWorks recompila desde el texto (probado con SolidWorks 2020).
    """
    codigo = codigo.replace(CRLF, LF).replace(LF, CRLF)
    if not codigo.endswith(CRLF):
        codigo += CRLF
    o = olefile.OleFileIO(plantilla)
    dir_dec = decompress_stream(bytearray(o.openstream(VBA_DIR + "/dir").read()))
    MODULO = nombre_modulo(dir_dec)
    fuente = ('Attribute VB_Name = "%s"' % MODULO) + CRLF + codigo
    off = _offset_modulo(dir_dec, MODULO)
    ruta_mod = VBA_DIR + "/" + MODULO
    nuevo_mod = o.openstream(ruta_mod).read()[:off] + comprimir(fuente.encode("cp1252", "replace"))

    if os.path.exists(destino):
        os.remove(destino)
    raiz = pythoncom.StgCreateDocfile(destino, 0x1012 | 0x2, 0)
    almacenes = {"": raiz}
    for ruta, es_dir in _recorrer(o):
        padre, _, nombre = ruta.rpartition("/")
        if es_dir:
            almacenes[ruta] = almacenes[padre].CreateStorage(nombre, 0x1012 | 0x2, 0)
        else:
            datos = nuevo_mod if ruta == ruta_mod else o.openstream(ruta).read()
            almacenes[padre].CreateStream(nombre, 0x1012 | 0x2, 0).Write(datos)
    for k in sorted(almacenes, key=len, reverse=True):
        almacenes[k].Commit(0)
    o.close()
    return destino


if __name__ == "__main__":
    import sys
    print(bas_a_swp(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
