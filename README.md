# Generador de Audios de Entrenamiento

Convierte rutinas de ejercicio en un **único archivo MP3 guiado por voz**, para entrenar sin tener que mirar la pantalla del celular.

El punto de partida son capturas de pantalla de una app de entrenamiento. El script las lee con **Gemini**, extrae los ejercicios y sus instrucciones, y arma con **edge-tts** una pista continua que anuncia cada ejercicio, lee la técnica mientras lo hacés, avisa el cambio de lado a mitad de tiempo y anticipa el siguiente.

---

## Por qué

Seguir una rutina desde capturas implica frenar entre ejercicio y ejercicio, buscar el cronómetro y leer la técnica. Con un audio de fondo el entrenamiento fluye: cada bloque dura exactamente lo que tiene que durar y la voz te va guiando.

---

## Cómo funciona

`main.py` orquesta tres etapas:

### 1. Lectura de rutinas (`indexado.py`)

Toma todas las capturas nuevas de `Rutinas/Imágenes/` y las manda **juntas y en orden** a Gemini con un `response_schema` estricto, que devuelve:

```json
{ "nombre_rutina": "Pecho 1", "ejercicios": [{ "nombre": "...", "seg": 30, "cambio_lado": true }] }
```

Mandarlas todas en una sola llamada es lo que permite que el modelo respete la secuencia original de la rutina aunque esté repartida en varias capturas. El resultado se guarda en `rutinas.json` y las imágenes se renombran con el nombre de la rutina.

### 2. Indexado de ejercicios (`indexado.py`)

Por cada captura de ejercicio en `Ejercicios/`, Gemini transcribe el título y el texto de INSTRUCCIONES y CONSEJOS. Cada resultado se guarda en `ejercicios.json` usando el nombre del ejercicio como clave.

Dos detalles de eficiencia:

- **Cache**: si el ejercicio ya está indexado, no se hace la llamada a la API.
- **Búsqueda exacta**: el nombre del ejercicio es la clave del diccionario, así que encontrarlo es O(1). La comparación distingue mayúsculas y tildes a propósito: dos ejercicios distintos pueden compartir el nombre y diferenciarse solo por la grafía («Flexión hacia Adelante» y «Flexión Hacia Adelante» son ejercicios distintos), y normalizarlos los fusionaría. El archivo se guarda ordenado alfabéticamente para que sea cómodo de editar a mano.

También descomprime automáticamente los `.zip` que exporta WhatsApp y los ordena de forma natural (`imagen.jpg`, `imagen (1).jpg`, `imagen (2).jpg`… en ese orden, no el alfabético que pondría `(10)` antes que `(2)`).

### 3. Generación del audio (`audio.py`)

Antes de generar nada, verifica que **todos** los ejercicios de la rutina estén indexados; si falta alguno intenta escanear imágenes pendientes y, si aun así falta, aborta en lugar de producir un audio incompleto.

Cada ejercicio se arma como tres bloques concatenados:

| Bloque | Duración | Contenido |
|---|---|---|
| Anuncio | 2 s exactos | «Ahora, *{nombre}*.» |
| Ejecución | `seg` s exactos | Nombre + instrucciones a **+100 %** de velocidad, en loop hasta llenar el tiempo, con *fade out* de 500 ms |
| Preparación | 4 s exactos | «Próximo ejercicio. *{siguiente}*.» |

Si el ejercicio tiene `cambio_lado`, a la mitad exacta del bloque de ejecución se inserta un aviso de 4 s: «Cambio de lado.»

Los bloques de anuncio y preparación tienen duración fija. Las dos frases son cortas a propósito: las fórmulas largas que usaban antes gastaban ocho y trece sílabas antes de llegar al nombre, y eran las que no dejaban entrar la frase en su caja. Son las mismas que usa la versión web, para que las dos digan lo mismo. Aun así, los nombres más largos no entran a velocidad normal: en vez de cortarlos, se vuelven a sintetizar acelerados lo justo para que quepan (`anunciar`, `preparar` y `bloque_fijo` en `audio.py`). El ritmo del audio queda clavado y no se pierde ni una palabra. Si preferís que la voz nunca se apure, subí `MS_BLOQUE_ANUNCIO` en `config.py`.

La síntesis de todas las frases se lanza en paralelo (hasta `MAX_SINTESIS_SIMULTANEAS` pedidos a la vez) y cada frase se genera una sola vez, aunque un ejercicio se repita en varias rutinas encadenadas. El armado posterior es local y respeta el orden original.

El último ejercicio cierra con «Rutina finalizada. Excelente entrenamiento.»

Todos los bloques se concatenan en un solo MP3 a 192 kbps en `Rutinas/Audios/`, y al terminar se abre el explorador de archivos en esa carpeta.

---

## Instalación

**Requisitos previos**

- Python 3.9 o superior
- [FFmpeg](https://ffmpeg.org/download.html) — `pydub` lo necesita para exportar MP3

```bash
# Debian / Ubuntu
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

**Pasos**

```bash
git clone https://github.com/agustingodoyc/<nombre-del-repo>.git
cd <nombre-del-repo>

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

**Configuración**

```bash
cp .env.example .env
```

Abrí `.env` y cargá tu API key de Gemini, que se obtiene gratis en [Google AI Studio](https://aistudio.google.com/apikey):

```
GEMINI_API_KEY=tu_clave_aca
```

> `.env` está en el `.gitignore`: la clave nunca se sube al repositorio.
> Si no configurás la clave, el generador de audios funciona igual con los JSON que ya tengas; lo único que se deshabilita es el escaneo de imágenes.

---

## Uso

1. Poné las capturas de la rutina en `Rutinas/Imágenes/` y las de cada ejercicio en `Ejercicios/`. Pueden ser los `.zip` que exporta WhatsApp: se descomprimen solos.
2. Ejecutá:

```bash
python main.py
```

3. El script escanea lo que haya nuevo y muestra el menú:

```
==========================================
      GENERADOR DE AUDIOS DE ENTRENAMIENTO
==========================================
Rutinas disponibles en la base de datos:
  [1] Pecho 1
  [2] Alargar
  [3] Tren inferior 1
==========================================
Escribí los números de las rutinas que quieras procesar.
Si querés combinar varias, sepáralas con una coma (ejemplo: 1, 2)
👉 Selección:
```

Podés combinar varias rutinas en una sola pista: `1, 3` genera `Pecho 1 + Tren inferior 1.mp3` como un audio continuo.

También se puede saltear el menú:

```bash
python main.py "Pecho 1" "Alargar"    # rutinas por nombre (o por número)
python main.py --sin-escaneo 1 3      # no consulta a Gemini, usa los índices guardados
python main.py --no-abrir 1           # no abre el explorador al terminar
```

---

## Estructura del proyecto

```
.
├── main.py                    # CLI: menú, argumentos y orquestación
├── config.py                  # Constantes: voz, duración de los bloques, rutas
├── datos.py                   # Lectura/escritura de los JSON e índice de ejercicios
├── indexado.py                # Capturas → JSON, vía Gemini
├── audio.py                   # Síntesis de voz y armado de la pista
├── requirements.txt
├── .env.example               # Plantilla de configuración
├── ejercicios.example.json    # Formato del índice de ejercicios
├── rutinas.example.json       # Formato del índice de rutinas
│
├── ejercicios.json            # (generado) Índice: nombre → instrucciones
├── rutinas.json               # (generado) Índice: rutina → lista de ejercicios
├── Ejercicios/                # (local) Capturas de cada ejercicio
└── Rutinas/
    ├── Imágenes/              # (local) Capturas de las rutinas
    └── Audios/                # (generado) MP3 finales
```

Los archivos marcados como *(local)* y *(generado)* están ignorados por git: son tu contenido y tus salidas, y cada quien aporta los suyos. Los `.example.json` documentan el formato exacto que espera el script.

### Formato de los datos

**`ejercicios.json`** — diccionario plano, ordenado alfabéticamente:

```json
{
    "Balanceo de Brazos": "INSTRUCCIONES: ... CONSEJOS: ..."
}
```

**`rutinas.json`** — cada rutina es una lista ordenada de ejercicios:

```json
{
    "Pecho 1": [
        { "nombre": "Balanceo de Brazos", "seg": 30, "cambio_lado": false }
    ]
}
```

| Campo | Tipo | Significado |
|---|---|---|
| `nombre` | string | Debe coincidir **exactamente** con una clave de `ejercicios.json`, mayúsculas y tildes incluidas |
| `seg` | int | Duración del ejercicio en segundos |
| `cambio_lado` | bool | Si es `true`, se inserta el aviso de cambio a mitad de tiempo |

Los dos archivos son texto plano y se pueden editar a mano sin pasar por la API.

---

## Decisiones técnicas

- **Índices separados** para ejercicios y rutinas. Un mismo ejercicio aparece en varias rutinas, así que su descripción se guarda una sola vez y las rutinas la referencian por nombre.
- **`response_schema` de Gemini** en lugar de parsear texto libre: la respuesta llega ya validada como JSON con los tipos correctos.
- **Velocidad `+100 %` en el bloque de ejecución** y normal en los anuncios. Las instrucciones se leen rápido para que entren en el tiempo del ejercicio; los avisos se leen claros, y solo se aceleran si no entran en su bloque.
- **Espera de 12 s entre llamadas** al indexar ejercicios y detención automática al detectar errores de cuota (429), para no agotar el nivel gratuito de la API.
- **Audio en memoria** (`io.BytesIO`) en lugar de archivos temporales en disco.
- **Concatenación en una sola pasada** sobre los buffers PCM. Encadenar con `+=` copia la pista entera en cada paso, lo que crece de forma cuadrática con la cantidad de ejercicios.
- **Todo a 24 kHz mono**, incluidos los silencios de relleno, para que pydub no tenga que resamplear al mezclar.
- **Duraciones ajustadas a nivel de muestra** y no de milisegundo, así no se acumula desfase bloque a bloque.

---

## Limitaciones

- Depende de la API de Gemini para el escaneo. Sin clave, el índice hay que cargarlo a mano.
- El nivel gratuito de Gemini tiene límites de cuota: indexar muchos ejercicios de una vez puede requerir varias corridas.
- `edge-tts` requiere conexión a internet: la síntesis de voz corre en los servidores de Microsoft.
- La voz está fijada en `es-AR-ElenaNeural`. Se cambia editando la constante `VOZ` en `config.py` ([lista de voces disponibles](https://github.com/rany2/edge-tts#voices)).

---

## Licencia

MIT — ver [LICENSE](LICENSE).
