# Taller SolidWorks

Programa de escritorio (Windows, Python) para trabajar con SolidWorks 2020:

- **Convertir `.bas` a `.swp`**: crea macros que SolidWorks ejecuta directamente, sin pegar el código a mano. Usa una macro grabada por SolidWorks como plantilla (`plantilla_macro.swp`), así funcionan los tipos y constantes de la API (`SldWorks`, `SwConst`...).
- **Ejecutar macros** `.swp` / `.bas` en el SolidWorks abierto.
- **STL → macro**: reconstruye una malla STL por capas (cortes + extrusiones) y escribe la macro. En desarrollo: sirve para piezas prismáticas sencillas.
- Plano PDF → código VBA, copias de seguridad, estado de documentos, etc.

## Uso

```
pip install -r requirements.txt
python taller_solidworks.py
```

Para generar el `.exe`: `pyinstaller --noconfirm TallerSolidWorks.spec`.

Requiere SolidWorks 2020 instalado (control por COM).
