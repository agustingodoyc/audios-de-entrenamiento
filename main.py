"""Generador de audios de entrenamiento.

Lee capturas de pantalla de rutinas y ejercicios, las indexa con Gemini y
genera una pista MP3 continua con la guía de voz de la rutina.
"""

import argparse
import asyncio
import os
import platform
import subprocess
import sys
from typing import List, Optional

from dotenv import load_dotenv

from audio import generar_rutina
from config import CARPETAS_REQUERIDAS, CARPETA_RUTINAS_AUDIOS
from datos import IndiceEjercicios, cargar_ejercicios, cargar_rutinas
from indexado import procesar_capturas_de_ejercicios, procesar_capturas_de_rutina


# ------------------------------------------------------------------ Entorno

def crear_cliente_gemini():
    """Cliente de Gemini, o (None, None) si no hay clave configurada.

    Sin clave el generador de audios funciona igual con los JSON existentes;
    lo único que se deshabilita es el escaneo de imágenes nuevas.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("⚠️ No se encontró GEMINI_API_KEY. Copiá '.env.example' a '.env' y cargá tu clave.")
        print("   El escaneo de imágenes queda deshabilitado; el resto funciona normal.")
        return None, None

    try:
        from google import genai
        from google.genai import types
        return genai.Client(api_key=api_key), types
    except Exception as e:
        print(f"⚠️ No se pudo inicializar Gemini: {e}. El escaneo de imágenes no funcionará.")
        return None, None


def abrir_carpeta(ruta: str) -> None:
    """Abre la carpeta en el explorador de archivos del sistema."""
    try:
        if platform.system() == "Windows":
            os.startfile(ruta)                                   # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.run(["open", ruta], check=False)
        else:
            subprocess.run(["xdg-open", ruta], check=False)
        print(f"📂 Explorador abierto en: {ruta}")
    except Exception as e:
        print(f"⚠️ No se pudo abrir la carpeta automáticamente: {e}")


# --------------------------------------------------------------- Selección

def menu_interactivo(opciones: List[str]) -> List[str]:
    print("\n==========================================")
    print("      GENERADOR DE AUDIOS DE ENTRENAMIENTO")
    print("==========================================")
    print("Rutinas disponibles en la base de datos:")
    for i, nombre in enumerate(opciones, 1):
        print(f"  [{i}] {nombre}")
    print("==========================================")
    print("Escribí los números de las rutinas que quieras procesar.")
    print("Si querés combinar varias, sepáralas con una coma (ejemplo: 1, 2)")

    seleccion = input("👉 Selección: ").strip()
    return resolver_seleccion(seleccion.split(","), opciones)


def resolver_seleccion(partes, opciones: List[str]) -> List[str]:
    """Traduce números o nombres a nombres de rutina válidos, en orden."""
    elegidas = []
    for parte in (p.strip() for p in partes):
        if not parte:
            continue
        if parte.isdigit() and 1 <= int(parte) <= len(opciones):
            elegidas.append(opciones[int(parte) - 1])
        elif parte in opciones:
            elegidas.append(parte)
        else:
            print(f"⚠️ Se ignora '{parte}': no es una rutina válida.")
    return elegidas


def verificar_indexado(elegidas: List[str], rutinas, indice: IndiceEjercicios,
                       client, types) -> Optional[IndiceEjercicios]:
    """Comprueba que todos los ejercicios estén indexados.

    Si falta alguno, intenta escanear una única vez las imágenes pendientes.
    Devuelve el índice actualizado, o None si sigue faltando algo.
    """
    nombres = [ej["nombre"] for r in elegidas for ej in rutinas[r]]
    faltantes = indice.faltantes(nombres)
    if not faltantes:
        return indice

    print(f"\n🔍 Faltan {len(faltantes)} ejercicios en el índice. Buscando imágenes sin procesar...")
    if procesar_capturas_de_ejercicios(client, types, indice):
        indice = cargar_ejercicios()
        faltantes = indice.faltantes(nombres)

    if faltantes:
        print("\n🛑 [ABORTADO] No se generó el audio. Faltan indexar:")
        for nombre in faltantes:
            print(f"   • {nombre}")
        print(f"\n   Agregá sus capturas a la carpeta de ejercicios y volvé a correr el script,")
        print(f"   o cargalos a mano en el índice de ejercicios.")
        return None

    return indice


# -------------------------------------------------------------------- Main

def parsear_argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera un MP3 guiado por voz a partir de una o varias rutinas.")
    parser.add_argument(
        "rutinas", nargs="*",
        help="Nombres o números de las rutinas a encadenar. Sin argumentos, "
             "se abre el menú interactivo.")
    parser.add_argument(
        "--sin-escaneo", action="store_true",
        help="No consulta a Gemini: usa solamente los índices ya guardados.")
    parser.add_argument(
        "--no-abrir", action="store_true",
        help="No abre el explorador de archivos al terminar.")
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parsear_argumentos()

    for carpeta in CARPETAS_REQUERIDAS:
        os.makedirs(carpeta, exist_ok=True)

    client, types = (None, None) if args.sin_escaneo else crear_cliente_gemini()

    if client:
        procesar_capturas_de_rutina(client, types)

    indice = cargar_ejercicios()
    if client:
        procesar_capturas_de_ejercicios(client, types, indice)

    rutinas = cargar_rutinas()
    opciones = list(rutinas)
    if not opciones:
        print("❌ No hay ninguna rutina cargada.")
        return 1

    elegidas = (resolver_seleccion(args.rutinas, opciones) if args.rutinas
                else menu_interactivo(opciones))
    if not elegidas:
        print("❌ No seleccionaste ninguna rutina válida.")
        return 1

    indice = verificar_indexado(elegidas, rutinas, indice, client, types)
    if indice is None:
        return 1

    print(f"\n🚀 Rutina a generar: {' + '.join(elegidas)}")
    asyncio.run(generar_rutina(elegidas, rutinas, indice))

    if not args.no_abrir:
        abrir_carpeta(CARPETA_RUTINAS_AUDIOS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
