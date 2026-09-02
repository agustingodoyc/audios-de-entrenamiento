"""Síntesis de voz y armado de la pista de audio de una rutina."""

import asyncio
import io
import math
import os
from typing import Dict, List, Sequence, Tuple

import edge_tts
from pydub import AudioSegment

from config import (
    BITRATE_EXPORT,
    CANALES,
    CARPETA_RUTINAS_AUDIOS,
    FRAME_RATE,
    MARGEN_ACELERACION,
    MAX_ACELERACION_PCT,
    MAX_SINTESIS_SIMULTANEAS,
    MS_BLOQUE_ANUNCIO,
    MS_BLOQUE_AVISO,
    MS_BLOQUE_PREPARACION,
    MS_FADE_EJECUCION,
    MS_FADE_RECORTE,
    SAMPLE_WIDTH,
    VELOCIDAD_NORMAL,
    VELOCIDAD_RAPIDA,
    VOZ,
)
from datos import IndiceEjercicios, nombre_seguro

TEXTO_CAMBIO_LADO = "Cambio de lado."
TEXTO_FINAL = "Rutina finalizada. Excelente entrenamiento."


# ------------------------------------------------------- Helpers de audio

def _normalizar(audio: AudioSegment) -> AudioSegment:
    """Lleva todo al mismo formato para poder concatenar sin reconversiones."""
    return (audio
            .set_frame_rate(FRAME_RATE)
            .set_channels(CANALES)
            .set_sample_width(SAMPLE_WIDTH))


def _silencio(ms: int) -> AudioSegment:
    """Silencio en el formato del proyecto.

    `AudioSegment.silent()` usa 11025 Hz por defecto; al mezclarlo con voz de
    24 kHz pydub tendría que resamplear todo el bloque.
    """
    return AudioSegment.silent(duration=max(0, ms), frame_rate=FRAME_RATE)


def _desde_pcm(datos: bytes) -> AudioSegment:
    return AudioSegment(data=datos, sample_width=SAMPLE_WIDTH,
                        frame_rate=FRAME_RATE, channels=CANALES)


def _concatenar(segmentos: Sequence[AudioSegment]) -> AudioSegment:
    """Une los segmentos en una sola pasada.

    Encadenar con `+=` copia la pista entera en cada paso (coste cuadrático).
    Como todos los segmentos ya están normalizados al mismo formato, alcanza
    con pegar sus buffers PCM y construir un único AudioSegment.
    """
    if not segmentos:
        return AudioSegment.empty()
    return _desde_pcm(b"".join(s.raw_data for s in segmentos))


def _bytes_por_ms() -> float:
    return FRAME_RATE * SAMPLE_WIDTH * CANALES / 1000.0


def _encajar(audio: AudioSegment, ms: int) -> AudioSegment:
    """Ajusta el segmento a una duración exacta, al nivel de la muestra.

    Trabajar sobre el buffer PCM en lugar de cortar por milisegundos evita
    que se acumule un desfase de fracciones de milisegundo bloque a bloque.
    """
    objetivo = int(round(ms * _bytes_por_ms()))
    objetivo -= objetivo % (SAMPLE_WIDTH * CANALES)   # Alineado a frame entero
    datos = audio.raw_data[:objetivo]
    return _desde_pcm(datos + b"\x00" * (objetivo - len(datos)))


# ------------------------------------------------------------ Sintetizador

class Sintetizador:
    """Genera voz con edge-tts, en paralelo y sin repetir frases.

    - Un semáforo limita los pedidos simultáneos al servicio.
    - Cada frase se sintetiza una sola vez: las repeticiones (un ejercicio que
      aparece en dos rutinas encadenadas, por ejemplo) reutilizan el resultado.
    """

    def __init__(self, voz: str = VOZ, max_simultaneas: int = MAX_SINTESIS_SIMULTANEAS) -> None:
        self.voz = voz
        self._semaforo = asyncio.Semaphore(max_simultaneas)
        self._tareas: Dict[Tuple[str, str], asyncio.Task] = {}

    async def _sintetizar(self, texto: str, velocidad: str) -> AudioSegment:
        async with self._semaforo:
            buffer = io.BytesIO()
            comunicacion = edge_tts.Communicate(texto, self.voz, rate=velocidad)
            async for chunk in comunicacion.stream():
                if chunk["type"] == "audio":
                    buffer.write(chunk["data"])
            buffer.seek(0)
            return _normalizar(AudioSegment.from_file(buffer, format="mp3"))

    def voz_de(self, texto: str, velocidad: str = VELOCIDAD_NORMAL) -> asyncio.Task:
        """Devuelve la tarea que sintetiza esa frase, creándola si no existe."""
        clave = (texto, velocidad)
        if clave not in self._tareas:
            self._tareas[clave] = asyncio.create_task(self._sintetizar(texto, velocidad))
        return self._tareas[clave]

    async def bloque_fijo(self, texto: str, ms: int) -> AudioSegment:
        """Frase encajada en un bloque de duración exacta `ms`.

        Si a velocidad normal no entra, se vuelve a sintetizar acelerada lo
        justo para que quepa, en lugar de cortarla a mitad de palabra. El
        sobrante se rellena con silencio.
        """
        audio = await self.voz_de(texto, VELOCIDAD_NORMAL)

        if len(audio) > ms:
            exceso = (len(audio) / ms) * (1 + MARGEN_ACELERACION)
            pct = min(math.ceil((exceso - 1) * 100), MAX_ACELERACION_PCT)
            audio = await self.voz_de(texto, f"+{pct}%")

        if len(audio) > ms:   # Ni al máximo entró: recorte con fundido, sin corte seco
            audio = _encajar(audio, ms).fade_out(MS_FADE_RECORTE)

        return _encajar(audio, ms)


# ------------------------------------------------------ Bloques de la rutina

def _bloque_ejecucion(voz_rapida: AudioSegment, segundos: int,
                      cambio_lado: bool, aviso_cambio: AudioSegment) -> AudioSegment:
    """Instrucciones en loop durante exactamente `segundos`.

    Con `cambio_lado`, a la mitad exacta se inserta el aviso de 4 s; el tiempo
    de ejercicio efectivo sigue siendo `segundos`.
    """
    ms_objetivo = int(segundos * 1000)
    ms_voz = len(voz_rapida)

    if ms_voz <= 0:
        plana = _silencio(ms_objetivo)
    elif ms_voz >= ms_objetivo:
        plana = voz_rapida
    else:
        repeticiones = math.ceil(ms_objetivo / ms_voz)
        plana = _concatenar([voz_rapida] * repeticiones)

    plana = _encajar(plana, ms_objetivo).fade_out(MS_FADE_EJECUCION)

    if not cambio_lado:
        return plana

    mitad = int(round((ms_objetivo // 2) * _bytes_por_ms()))
    mitad -= mitad % (SAMPLE_WIDTH * CANALES)
    crudo = plana.raw_data
    return _concatenar([_desde_pcm(crudo[:mitad]), aviso_cambio, _desde_pcm(crudo[mitad:])])


async def generar_rutina(nombres_rutinas: List[str], rutinas: Dict[str, list],
                         indice: IndiceEjercicios) -> str:
    """Genera el MP3 unificado de una o varias rutinas encadenadas.

    Devuelve la ruta del archivo generado.
    """
    ejercicios: List[dict] = []
    for nombre in nombres_rutinas:
        ejercicios.extend(rutinas[nombre])

    total = len(ejercicios)
    sintetizador = Sintetizador()

    # 1. Se lanzan todas las síntesis a la vez y se esperan juntas.
    #    El armado posterior es puro cálculo local y mantiene el orden original.
    print(f"🎙️ Sintetizando voz ({total} ejercicios, "
          f"hasta {MAX_SINTESIS_SIMULTANEAS} pedidos en paralelo)...")

    tarea_aviso = sintetizador.bloque_fijo(TEXTO_CAMBIO_LADO, MS_BLOQUE_AVISO)
    tareas_anuncio, tareas_ejecucion, tareas_preparacion = [], [], []

    for i, ej in enumerate(ejercicios):
        nombre = ej["nombre"]
        instrucciones = indice.obtener(nombre)

        tareas_anuncio.append(
            sintetizador.bloque_fijo(f"Ejercicio por empezar. {nombre}.", MS_BLOQUE_ANUNCIO))
        tareas_ejecucion.append(
            sintetizador.voz_de(f"{nombre}. {instrucciones}", VELOCIDAD_RAPIDA))

        siguiente = ejercicios[i + 1]["nombre"] if i + 1 < total else None
        texto_prep = (f"Preparación para el próximo ejercicio. {siguiente}."
                      if siguiente else TEXTO_FINAL)
        tareas_preparacion.append(
            sintetizador.bloque_fijo(texto_prep, MS_BLOQUE_PREPARACION))

    aviso_cambio, anuncios, ejecuciones, preparaciones = await asyncio.gather(
        tarea_aviso,
        asyncio.gather(*tareas_anuncio),
        asyncio.gather(*tareas_ejecucion),
        asyncio.gather(*tareas_preparacion),
    )

    # 2. Armado de la pista.
    print("🧩 Armando la pista...")
    piezas: List[AudioSegment] = []
    for i, ej in enumerate(ejercicios):
        piezas.append(anuncios[i])
        piezas.append(_bloque_ejecucion(
            ejecuciones[i], ej["seg"], ej.get("cambio_lado", False), aviso_cambio))
        piezas.append(preparaciones[i])

    pista = _concatenar(piezas)

    # 3. Exportación.
    os.makedirs(CARPETA_RUTINAS_AUDIOS, exist_ok=True)
    ruta = os.path.join(
        CARPETA_RUTINAS_AUDIOS,
        f"{nombre_seguro(' + '.join(nombres_rutinas), extra='._- +')}.mp3",
    )

    print("💾 Exportando...")
    pista.export(ruta, format="mp3", bitrate=BITRATE_EXPORT,
                 parameters=["-id3v2_version", "3"])

    minutos, segundos = divmod(round(len(pista) / 1000), 60)
    print(f"✅ Listo: {ruta} ({minutos} min {segundos} s)")
    return ruta
