"""Extracción de rutinas y ejercicios a partir de capturas de pantalla, con Gemini."""

import json
import os
import re
import time
import zipfile
from typing import List, Optional

from config import (
    CARPETA_EJERCICIOS,
    CARPETA_RUTINAS_IMAGENES,
    EXTENSIONES_IMAGEN,
    MODELO_GEMINI,
    PALABRAS_CLAVE_CUOTA,
    PREFIJO_CRUDO,
    SEGUNDOS_ENTRE_LLAMADAS,
)
from datos import IndiceEjercicios, cargar_rutinas, guardar_rutinas, nombre_seguro

_ESQUEMA_RUTINA = {
    "type": "OBJECT",
    "properties": {
        "nombre_rutina": {"type": "STRING"},
        "ejercicios": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "nombre": {"type": "STRING"},
                    "seg": {"type": "INTEGER"},
                    "cambio_lado": {"type": "BOOLEAN"},
                },
                "required": ["nombre", "seg", "cambio_lado"],
            },
        },
    },
    "required": ["nombre_rutina", "ejercicios"],
}

_ESQUEMA_EJERCICIO = {
    "type": "OBJECT",
    "properties": {"nombre": {"type": "STRING"}, "texto": {"type": "STRING"}},
    "required": ["nombre", "texto"],
}

_PROMPT_RUTINA = """
Analiza TODAS las capturas de pantalla adjuntas enviadas EN ESTE ORDEN ESTRICTO.

1. 'nombre_rutina': Extrae el título principal de la rutina (encabezado superior de la PRIMERA imagen).
2. 'ejercicios': Procesa las imágenes de la primera a la última de manera secuencial y mantén ese orden en la lista resultante.
   - 'nombre': Nombre exacto del ejercicio.
   - 'seg': Duración convertida a segundos (ej. 0:30 = 30, 1:00 = 60).
   - 'cambio_lado': true si tiene la burbuja con flechas (⇄), false en caso contrario.
"""

_PROMPT_EJERCICIO = (
    "Transcribe el título principal en 'nombre' y todo el texto restante "
    "(INSTRUCCIONES y CONSEJOS) en 'texto'."
)


class ErrorDeCuota(RuntimeError):
    """La API rechazó el pedido por límite de cuota o de tokens."""


def _es_error_de_cuota(e: Exception) -> bool:
    mensaje = str(e).lower()
    return any(k in mensaje for k in PALABRAS_CLAVE_CUOTA)


# ----------------------------------------------------------- Archivos crudos

def descomprimir_zips(carpeta: str) -> None:
    """Extrae a la raíz de `carpeta` los .zip que exporta WhatsApp y los elimina."""
    if not os.path.isdir(carpeta):
        return

    for nombre_zip in os.listdir(carpeta):
        if not (nombre_zip.lower().startswith(PREFIJO_CRUDO)
                and nombre_zip.lower().endswith(".zip")):
            continue

        ruta_zip = os.path.join(carpeta, nombre_zip)
        print(f"📦 Descomprimiendo '{nombre_zip}'...")
        try:
            with zipfile.ZipFile(ruta_zip) as zf:
                for miembro in zf.infolist():
                    if miembro.is_dir():
                        continue
                    # basename(): descarta rutas internas y evita escribir fuera de la carpeta
                    destino = os.path.basename(miembro.filename)
                    if not destino or destino.startswith("."):
                        continue
                    with zf.open(miembro) as origen, open(os.path.join(carpeta, destino), "wb") as salida:
                        salida.write(origen.read())
            os.remove(ruta_zip)
            print(f"🗑️ '{nombre_zip}' procesado y eliminado.")
        except (zipfile.BadZipFile, OSError) as e:
            print(f"❌ Error al descomprimir '{nombre_zip}': {e}")


def _orden_whatsapp(nombre_archivo: str):
    """Ordena 'foto.jpg' antes que 'foto (1).jpg', y '(2)' antes que '(10)'."""
    match = re.match(r"^(.*?)(?:\s*\((\d+)\))?\.[a-zA-Z0-9]+$", nombre_archivo)
    if not match:
        return (nombre_archivo.lower(), 0)
    return (match.group(1).lower(), int(match.group(2) or 0))


def _capturas_sin_procesar(carpeta: str) -> List[str]:
    if not os.path.isdir(carpeta):
        return []
    archivos = [
        f for f in os.listdir(carpeta)
        if f.lower().startswith(PREFIJO_CRUDO) and f.lower().endswith(EXTENSIONES_IMAGEN)
    ]
    return sorted(archivos, key=_orden_whatsapp)


def _parte_imagen(types, ruta: str):
    with open(ruta, "rb") as f:
        datos = f.read()
    mime = "image/png" if ruta.lower().endswith(".png") else "image/jpeg"
    return types.Part.from_bytes(data=datos, mime_type=mime)


def _renombrar(carpeta: str, viejo: str, nuevo_base: str) -> str:
    ext = os.path.splitext(viejo)[1].lower()
    destino = os.path.join(carpeta, f"{nuevo_base}{ext}")
    if os.path.exists(destino):
        os.remove(destino)
    os.rename(os.path.join(carpeta, viejo), destino)
    return os.path.basename(destino)


# ------------------------------------------------------------------ Rutinas

def procesar_capturas_de_rutina(client, types) -> Optional[str]:
    """Lee las capturas de Rutinas/Imágenes y guarda la rutina en rutinas.json.

    Devuelve el nombre de la rutina cargada, o None si no había nada que hacer.
    """
    descomprimir_zips(CARPETA_RUTINAS_IMAGENES)
    archivos = _capturas_sin_procesar(CARPETA_RUTINAS_IMAGENES)
    if not client or not archivos:
        return None

    print(f"\n📋 {len(archivos)} capturas de rutina nuevas. Orden de lectura:")
    for i, nombre in enumerate(archivos, 1):
        print(f"   {i}. {nombre}")

    partes = [_parte_imagen(types, os.path.join(CARPETA_RUTINAS_IMAGENES, a)) for a in archivos]

    try:
        print("\n⏳ Consultando a Gemini...")
        respuesta = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=[*partes, _PROMPT_RUTINA],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_ESQUEMA_RUTINA,
            ),
        )
        datos = json.loads(respuesta.text.strip())
    except Exception as e:
        print(f"❌ Error al procesar la rutina: {e}")
        if _es_error_de_cuota(e):
            print("🛑 Límite de cuota detectado.")
        return None

    nombre_rutina = datos.get("nombre_rutina", "").strip()
    ejercicios = datos.get("ejercicios", [])
    if not nombre_rutina or not ejercicios:
        print("❌ No se pudo extraer la información completa de la rutina.")
        return None

    rutinas = cargar_rutinas()
    rutinas[nombre_rutina] = ejercicios
    guardar_rutinas(rutinas)
    print(f"✅ Rutina '{nombre_rutina}' guardada ({len(ejercicios)} ejercicios).")

    base = nombre_seguro(nombre_rutina)
    for i, archivo in enumerate(archivos, 1):
        print(f"📸 Renombrada: '{_renombrar(CARPETA_RUTINAS_IMAGENES, archivo, f'{base} {i}')}'")

    return nombre_rutina


# --------------------------------------------------------------- Ejercicios

def _limpiar_transcripcion(texto: str) -> str:
    """Une el texto en un párrafo y normaliza los encabezados a 'INSTRUCCIONES: '."""
    texto = re.sub(r" +", " ", texto.replace("\n", " ")).strip()
    texto = re.sub(r"\b(INSTRUCCIONES|CONSEJOS)\b(?!\s*:)", r"\1:", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\b(INSTRUCCIONES|CONSEJOS):(\S)", r"\1: \2", texto, flags=re.IGNORECASE)
    return texto


def procesar_capturas_de_ejercicios(client, types, indice: IndiceEjercicios) -> bool:
    """Transcribe las capturas nuevas de Ejercicios/ y las agrega al índice.

    Devuelve True si el índice cambió. Modifica `indice` en el lugar.
    """
    descomprimir_zips(CARPETA_EJERCICIOS)
    archivos = _capturas_sin_procesar(CARPETA_EJERCICIOS)
    if not client or not archivos:
        return False

    print(f"\n🔍 {len(archivos)} capturas de ejercicio nuevas en '{CARPETA_EJERCICIOS}'.")
    hubo_cambios = False
    primera_llamada = True

    for archivo in archivos:
        if os.path.splitext(archivo)[0] in indice:
            print(f"⚡ '{archivo}' ya está indexado. Se saltea la llamada a la API.")
            continue

        # La espera va entre llamadas, no antes de la primera.
        if not primera_llamada:
            print(f"⏳ Esperando {SEGUNDOS_ENTRE_LLAMADAS} s para cuidar la cuota...")
            time.sleep(SEGUNDOS_ENTRE_LLAMADAS)
        primera_llamada = False

        print(f"📸 Analizando '{archivo}'...")
        try:
            respuesta = client.models.generate_content(
                model=MODELO_GEMINI,
                contents=[
                    _parte_imagen(types, os.path.join(CARPETA_EJERCICIOS, archivo)),
                    _PROMPT_EJERCICIO,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_ESQUEMA_EJERCICIO,
                ),
            )
            datos = json.loads(respuesta.text.strip())
        except Exception as e:
            print(f"❌ Error al procesar '{archivo}': {e}")
            if _es_error_de_cuota(e):
                print("\n🛑 [DETENCIÓN DE SEGURIDAD] Límite de cuota de Gemini alcanzado.")
                break
            continue

        nombre = datos.get("nombre", "").strip()
        if not nombre or nombre.upper() in ("INSTRUCCIONES", "CONSEJOS"):
            print(f"❌ Nombre inválido en '{archivo}': '{nombre}'. Se omite.")
            continue

        indice.agregar(nombre, _limpiar_transcripcion(datos.get("texto", "").strip()))
        hubo_cambios = True
        nuevo = _renombrar(CARPETA_EJERCICIOS, archivo, nombre_seguro(nombre))
        print(f"💾 Indexado y renombrado a '{nuevo}'.")

    if hubo_cambios:
        indice.guardar()
        print(f"📝 Índice de ejercicios actualizado ({len(indice)} en total).")

    return hubo_cambios
