"""Lectura y escritura de los índices JSON de ejercicios y rutinas."""

import json
import os
import sys
from typing import Dict, List, Optional

from config import ARCHIVO_EJERCICIOS, ARCHIVO_RUTINAS

Ejercicio = Dict[str, object]        # {"nombre": str, "seg": int, "cambio_lado": bool}
Rutinas = Dict[str, List[Ejercicio]]


# --------------------------------------------------------------- Utilidades

def nombre_seguro(texto: str, extra: str = "._- ") -> str:
    """Deja solo caracteres válidos para un nombre de archivo."""
    return "".join(c for c in texto if c.isalnum() or c in extra).strip()


# ------------------------------------------------------------------ Rutinas

def cargar_rutinas() -> Rutinas:
    if not os.path.exists(ARCHIVO_RUTINAS):
        ejemplo: Rutinas = {
            "Pecho": [{"nombre": "Círculos con los Brazos", "seg": 30, "cambio_lado": False}]
        }
        guardar_rutinas(ejemplo)
        return ejemplo

    with open(ARCHIVO_RUTINAS, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"❌ '{ARCHIVO_RUTINAS}' tiene un formato JSON inválido: {e}")
            sys.exit(1)


def guardar_rutinas(datos: Rutinas) -> None:
    with open(ARCHIVO_RUTINAS, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)


# --------------------------------------------------------------- Ejercicios

class IndiceEjercicios:
    """Índice de ejercicios, con búsqueda exacta por nombre.

    La comparación distingue mayúsculas y tildes a propósito: dos ejercicios
    distintos pueden compartir el nombre y diferenciarse solo por la grafía
    ('Flexión hacia Adelante' y 'Flexión Hacia Adelante' NO son el mismo).
    Cualquier normalización los fusionaría y el audio saldría con las
    instrucciones del otro.

    El diccionario ya está en memoria, así que la búsqueda es O(1) sobre una
    tabla hash. El archivo se guarda ordenado alfabéticamente para que sea
    cómodo de leer y de editar a mano.
    """

    def __init__(self, datos: Optional[Dict[str, str]] = None) -> None:
        self._datos: Dict[str, str] = datos or {}

    # -- lectura ---------------------------------------------------------
    def __contains__(self, nombre: str) -> bool:
        return nombre in self._datos

    def __len__(self) -> int:
        return len(self._datos)

    def obtener(self, nombre: str) -> Optional[str]:
        return self._datos.get(nombre)

    def faltantes(self, nombres) -> List[str]:
        """Nombres que no están indexados, sin repetir y en orden de aparición."""
        vistos, faltan = set(), []
        for n in nombres:
            if n not in self._datos and n not in vistos:
                vistos.add(n)
                faltan.append(n)
        return faltan

    # -- escritura -------------------------------------------------------
    def agregar(self, nombre: str, texto: str) -> None:
        self._datos[nombre] = texto

    def guardar(self) -> None:
        ordenados = {k: self._datos[k] for k in sorted(self._datos)}
        with open(ARCHIVO_EJERCICIOS, "w", encoding="utf-8") as f:
            json.dump(ordenados, f, ensure_ascii=False, indent=4)


def cargar_ejercicios() -> IndiceEjercicios:
    if not os.path.exists(ARCHIVO_EJERCICIOS):
        return IndiceEjercicios()

    with open(ARCHIVO_EJERCICIOS, "r", encoding="utf-8") as f:
        try:
            return IndiceEjercicios(json.load(f))
        except json.JSONDecodeError:
            print(f"⚠️ '{ARCHIVO_EJERCICIOS}' está corrupto. Se parte de un índice vacío.")
            return IndiceEjercicios()
