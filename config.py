"""Constantes de configuración del generador de audios de entrenamiento."""

import os

# ---------------------------------------------------------------- Voz y ritmo

VOZ = "es-AR-ElenaNeural"
VELOCIDAD_NORMAL = "+0%"
VELOCIDAD_RAPIDA = "+100%"

# Los bloques de anuncio y preparación tienen duración fija. Cuando la frase no
# entra, se vuelve a sintetizar acelerada en lugar de cortarla a mitad de palabra.
MAX_ACELERACION_PCT = 150

# La relación entre `rate` y duración no es perfectamente lineal (los silencios
# inicial y final del sintetizador no se escalan), así que se pide un poco de más.
MARGEN_ACELERACION = 0.06

# ------------------------------------------------------------ Formato de audio

# edge-tts entrega MP3 mono de 24 kHz. Fijar estos valores evita que pydub
# tenga que resamplear al mezclar voz con silencios.
FRAME_RATE = 24000
CANALES = 1
SAMPLE_WIDTH = 2
BITRATE_EXPORT = "192k"

# ----------------------------------------------------- Duración de los bloques

MS_BLOQUE_ANUNCIO = 2000       # "Ejercicio por empezar. {nombre}."
MS_BLOQUE_AVISO = 4000         # "Cambio de lado."
MS_BLOQUE_PREPARACION = 4000   # "Preparación para el próximo ejercicio. {siguiente}."
MS_FADE_EJECUCION = 500        # Fundido al final del bloque de ejecución
MS_FADE_RECORTE = 80           # Fundido de emergencia si ni acelerada entra

# --------------------------------------------------------------- Concurrencia

# Pedidos simultáneos a edge-tts. Subirlo acelera la generación; valores muy
# altos pueden hacer que el servicio rechace pedidos.
MAX_SINTESIS_SIMULTANEAS = 6

# --------------------------------------------------------------------- Gemini

MODELO_GEMINI = "gemini-2.5-flash"
SEGUNDOS_ENTRE_LLAMADAS = 12   # Espera entre imágenes para cuidar la cuota gratuita
PALABRAS_CLAVE_CUOTA = ("quota", "limit", "exhausted", "429", "token")

# ---------------------------------------------------------------------- Rutas

ARCHIVO_EJERCICIOS = "ejercicios.json"
ARCHIVO_RUTINAS = "rutinas.json"

CARPETA_EJERCICIOS = "Ejercicios"
CARPETA_RUTINAS = "Rutinas"
CARPETA_RUTINAS_IMAGENES = os.path.join(CARPETA_RUTINAS, "Imágenes")
CARPETA_RUTINAS_AUDIOS = os.path.join(CARPETA_RUTINAS, "Audios")

CARPETAS_REQUERIDAS = (
    CARPETA_EJERCICIOS,
    CARPETA_RUTINAS_IMAGENES,
    CARPETA_RUTINAS_AUDIOS,
)

EXTENSIONES_IMAGEN = (".png", ".jpg", ".jpeg", ".webp")
PREFIJO_CRUDO = "whatsapp"     # Las capturas sin procesar llegan con este prefijo
