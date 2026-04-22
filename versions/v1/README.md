
# Snapshot Installer Scanner (PyQt6)

Para Windows 10.

## Qué hace
1. Escanea una ruta (por ejemplo `C:\`).
2. Guarda un snapshot en una base de datos SQLite.
3. Te pide instalar el programa que quieras analizar.
4. Hace un segundo snapshot.
5. Compara ambos snapshots.
6. Exporta los cambios a archivos CSV y un TXT resumen.

## Información registrada
- Ruta completa
- Si es archivo o carpeta
- Tamaño
- Fecha/hora de modificación
- Fecha/hora de cambio
- Modo/atributos básicos
- Errores de acceso durante el escaneo

## Requisitos
- Windows 10
- Python en el PATH
- PyQt6

## Instalación
Abre CMD o PowerShell y ejecuta:

```bash
pip install PyQt6
```

## Ejecución
En la carpeta del programa:

```bash
python thinapp_like_snapshot_scanner.py
```

## Uso recomendado
- Ejecuta la aplicación como **Administrador** si vas a escanear todo `C:\`, para reducir errores por permisos.
- Primer botón: **Crear escaneo inicial**
- Instala el programa que quieres analizar
- Segundo botón: **Crear escaneo después de instalar**
- Luego pulsa **Comparar snapshots**

## Archivos generados al comparar
Se crean en la carpeta de exportación:
- `cambios_creados_*.csv`
- `cambios_eliminados_*.csv`
- `cambios_modificados_*.csv`
- `resumen_comparacion_*.txt`

## Notas importantes
- Escanear todo `C:\` puede tardar bastante dependiendo del disco y la cantidad de archivos.
- Algunos archivos del sistema pueden dar error de acceso; esos errores también se guardan.
- Esta versión detecta cambios por metadatos del sistema de archivos. No calcula hash del contenido, para que el escaneo no sea tan lento.
