import asyncio
import edge_tts
from pydub import AudioSegment
import os
import json
import sys
import bisect
import time
import io
import re
import zipfile
import subprocess
import platform
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

VOZ = "es-AR-ElenaNeural"
VELOCIDAD_NORMAL = "+0%"
VELOCIDAD_RAPIDA = "+100%"

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    print("⚠️ No se encontró GEMINI_API_KEY. Copiá '.env.example' a '.env' y cargá tu clave.")
    print("   El generador de audios funciona igual, pero el escaneo de imágenes estará deshabilitado.")
    client = None
else:
    try:
        client = genai.Client(api_key=API_KEY)
    except Exception as e:
        print(f"⚠️ Error al inicializar Gemini: {e}. El escaneo de imágenes no funcionará.")
        client = None

ARCHIVO_EJERCICIOS = "ejercicios.json"
ARCHIVO_RUTINAS = "rutinas.json"

CARPETA_EJERCICIOS = "Ejercicios"
CARPETA_RUTINAS = "Rutinas"

# SUBCARPETAS DENTRO DE "Rutinas"
CARPETA_RUTINAS_IMAGENES = os.path.join(CARPETA_RUTINAS, "Imágenes")
CARPETA_RUTINAS_AUDIOS = os.path.join(CARPETA_RUTINAS, "Audios")

def abrir_carpeta_audios(ruta_carpeta):
    """Abre la carpeta de audios en el explorador de archivos del sistema operativo."""
    try:
        if platform.system() == "Windows":
            os.startfile(ruta_carpeta)
        elif platform.system() == "Darwin":  # macOS
            subprocess.run(["open", ruta_carpeta])
        else:  # Linux / Unix
            subprocess.run(["xdg-open", ruta_carpeta])
        print(f"📂 Explorador de archivos abierto en: {ruta_carpeta}")
    except Exception as e:
        print(f"⚠️ No se pudo abrir automáticamente la carpeta: {e}")

def descomprimir_zips_whatsapp(carpeta_destino):
    """
    Busca archivos .zip que comiencen con 'whatsapp' en la carpeta indicada,
    extrae todas las imágenes a la raíz de esa carpeta y elimina el archivo zip.
    Si no hay archivos ZIP, continúa normalmente.
    """
    if not os.path.exists(carpeta_destino):
        return

    archivos_zip = [f for f in os.listdir(carpeta_destino) if f.lower().startswith("whatsapp") and f.lower().endswith(".zip")]

    for nombre_zip in archivos_zip:
        ruta_zip = os.path.join(carpeta_destino, nombre_zip)
        print(f"📦 Descomprimiendo archivo ZIP encontrado: '{nombre_zip}' en '{carpeta_destino}'...")

        try:
            with zipfile.ZipFile(ruta_zip, 'r') as zip_ref:
                for member in zip_ref.infolist():
                    if member.is_dir() or os.path.basename(member.filename).startswith('.'):
                        continue
                    
                    nombre_archivo_limpio = os.path.basename(member.filename)
                    if nombre_archivo_limpio:
                        ruta_salida = os.path.join(carpeta_destino, nombre_archivo_limpio)
                        with zip_ref.open(member) as fuente, open(ruta_salida, "wb") as destino:
                            destino.write(fuente.read())

            os.remove(ruta_zip)
            print(f"🗑️ Archivo comprimido '{nombre_zip}' procesado y eliminado.")

        except Exception as e:
            print(f"❌ Error al descomprimir '{nombre_zip}': {e}")

def cargar_rutinas():
    if os.path.exists(ARCHIVO_RUTINAS):
        with open(ARCHIVO_RUTINAS, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print(f"❌ Error crítico: El archivo '{ARCHIVO_RUTINAS}' tiene un formato JSON inválido.")
                sys.exit()
    else:
        ejemplo = {"Pecho": [{"nombre": "Círculos con los Brazos", "seg": 30, "cambio_lado": False}]}
        with open(ARCHIVO_RUTINAS, "w", encoding="utf-8") as f:
            json.dump(ejemplo, f, ensure_ascii=False, indent=4)
        return ejemplo

def guardar_rutinas(datos):
    with open(ARCHIVO_RUTINAS, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)

def cargar_ejercicios_globales():
    if os.path.exists(ARCHIVO_EJERCICIOS):
        with open(ARCHIVO_EJERCICIOS, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def guardar_ejercicios_globales_ordenados(datos):
    datos_ordenados = {k: datos[k] for k in sorted(datos.keys())}
    with open(ARCHIVO_EJERCICIOS, "w", encoding="utf-8") as f:
        json.dump(datos_ordenados, f, ensure_ascii=False, indent=4)

def buscar_ejercicio_eficiente(nombre_ejercicio, lista_claves_ordenada):
    index = bisect.bisect_left(lista_claves_ordenada, nombre_ejercicio)
    if index < len(lista_claves_ordenada) and lista_claves_ordenada[index] == nombre_ejercicio:
        return True
    return False

def obtener_clave_orden_whatsapp(nombre_archivo):
    """
    Ordena correctamente las imágenes de WhatsApp:
    1. Base sin número (se le asigna el índice 0) -> va PRIMERO.
    2. Versiones con (1), (2), (10) -> van en orden numérico creciente.
    """
    patron = r'^(.*?)(?:\s*\((\d+)\))?\.[a-zA-Z0-9]+$'
    match = re.match(patron, nombre_archivo)
    
    if match:
        base = match.group(1).lower()
        numero_sub = int(match.group(2)) if match.group(2) else 0
        return (base, numero_sub)
    
    return (nombre_archivo.lower(), 0)

def procesar_imagenes_rutinas():
    descomprimir_zips_whatsapp(CARPETA_RUTINAS_IMAGENES)

    if not client or not os.path.exists(CARPETA_RUTINAS_IMAGENES):
        return

    extensiones_validas = (".png", ".jpg", ".jpeg", ".webp")
    archivos_crudos = [f for f in os.listdir(CARPETA_RUTINAS_IMAGENES) if f.lower().startswith("whatsapp") and f.lower().endswith(extensiones_validas)]

    if not archivos_crudos:
        return

    archivos = sorted(archivos_crudos, key=obtener_clave_orden_whatsapp)

    print(f"\n📋 Se encontraron {len(archivos)} imágenes nuevas de rutina en '{CARPETA_RUTINAS_IMAGENES}'...")
    print("📌 Orden de lectura de imágenes:")
    for idx, arch in enumerate(archivos, start=1):
        print(f"   {idx}. {arch}")

    partes_imagenes = []
    for nombre_archivo in archivos:
        ruta_origen = os.path.join(CARPETA_RUTINAS_IMAGENES, nombre_archivo)
        ext = os.path.splitext(nombre_archivo)[1]
        with open(ruta_origen, "rb") as f:
            bytes_imagen = f.read()
        mime = "image/png" if ext.lower() == ".png" else "image/jpeg"
        partes_imagenes.append(types.Part.from_bytes(data=bytes_imagen, mime_type=mime))

    prompt = """
    Analiza TODAS las capturas de pantalla adjuntas enviadas EN ESTE ORDEN ESTRICTO.
    
    1. 'nombre_rutina': Extrae el título principal de la rutina (encabezado superior de la PRIMERA imagen).
    2. 'ejercicios': Procesa las imágenes de la primera a la última de manera secuencial y mantén ese orden en la lista resultante.
       - 'nombre': Nombre exacto del ejercicio.
       - 'seg': Duración convertida a segundos (ej. 0:30 = 30, 1:00 = 60).
       - 'cambio_lado': true si tiene la burbuja con flechas (⇄), false en caso contrario.
    """

    try:
        print("\n⏳ Consultando a Gemini para procesar las imágenes...")
        time.sleep(2)
        respuesta = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[*partes_imagenes, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
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
                                    "cambio_lado": {"type": "BOOLEAN"}
                                },
                                "required": ["nombre", "seg", "cambio_lado"]
                            }
                        }
                    },
                    "required": ["nombre_rutina", "ejercicios"]
                }
            )
        )

        datos_rutina = json.loads(respuesta.text.strip())
        nombre_rutina = datos_rutina.get("nombre_rutina", "").strip()
        lista_ejercicios = datos_rutina.get("ejercicios", [])

        if not nombre_rutina or not lista_ejercicios:
            print("❌ No se pudo extraer la información completa de la rutina.")
            return

        rutinas_actuales = cargar_rutinas()
        rutinas_actuales[nombre_rutina] = lista_ejercicios
        guardar_rutinas(rutinas_actuales)
        print(f"✅ Rutina '{nombre_rutina}' guardada correctamente ({len(lista_ejercicios)} ejercicios).")

        nombre_seguro_rutina = "".join(x for x in nombre_rutina if x.isalnum() or x in "._- ")
        for idx, nombre_archivo in enumerate(archivos, start=1):
            ext = os.path.splitext(nombre_archivo)[1]
            ruta_origen = os.path.join(CARPETA_RUTINAS_IMAGENES, nombre_archivo)
            nuevo_nombre_foto = f"{nombre_seguro_rutina} {idx}{ext.lower()}"
            ruta_destino = os.path.join(CARPETA_RUTINAS_IMAGENES, nuevo_nombre_foto)

            if os.path.exists(ruta_destino):
                os.remove(ruta_destino)

            os.rename(ruta_origen, ruta_destino)
            print(f"📸 Imagen de rutina renombrada: '{nuevo_nombre_foto}'")

    except Exception as e:
        error_msg = str(e).lower()
        print(f"❌ Error al procesar la rutina: {e}")
        if any(k in error_msg for k in ["quota", "limit", "exhausted", "429", "token"]):
            print("🛑 [DETENCIÓN DE SEGURIDAD] Límite de cuota detectado al procesar la rutina.")

def procesar_imagenes_nuevas_whatsapp():
    descomprimir_zips_whatsapp(CARPETA_EJERCICIOS)

    if not client or not os.path.exists(CARPETA_EJERCICIOS):
        return

    ejercicios_globales = cargar_ejercicios_globales()
    hubo_cambios = False

    extensiones_validas = (".png", ".jpg", ".jpeg", ".webp")
    archivos = [f for f in os.listdir(CARPETA_EJERCICIOS) if f.lower().startswith("whatsapp") and f.lower().endswith(extensiones_validas)]

    if not archivos:
        return

    print(f"\n🔍 Se encontraron {len(archivos)} imágenes nuevas de ejercicios en '{CARPETA_EJERCICIOS}'...")

    for nombre_archivo in archivos:
        ruta_origen = os.path.join(CARPETA_EJERCICIOS, nombre_archivo)
        ext = os.path.splitext(nombre_archivo)[1]

        nombre_sin_ext = os.path.splitext(nombre_archivo)[0]
        if nombre_sin_ext in ejercicios_globales:
            print(f"⚡ El ejercicio '{nombre_sin_ext}' ya está indexado. Salteando llamada a la API.")
            continue

        print(f"📸 Analizando ejercicio crudo: {nombre_archivo}...")

        try:
            with open(ruta_origen, "rb") as f:
                bytes_imagen = f.read()
            mime = "image/png" if ext.lower() == ".png" else "image/jpeg"
            imagen_input = types.Part.from_bytes(data=bytes_imagen, mime_type=mime)

            prompt = "Transcribe el título principal en 'nombre' y todo el texto restante (INSTRUCCIONES y CONSEJOS) en 'texto'."
            
            print("⏳ Esperando 12 segundos para cuidar la cuota de la API...")
            time.sleep(12)

            respuesta = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[imagen_input, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "OBJECT",
                        "properties": {
                            "nombre": {"type": "STRING"},
                            "texto": {"type": "STRING"}
                        },
                        "required": ["nombre", "texto"]
                    }
                )
            )
            
            datos_ia = json.loads(respuesta.text.strip())
            nombre_ejercicio = datos_ia.get("nombre", "").strip()
            texto_transcrito = datos_ia.get("texto", "").strip()

            if not nombre_ejercicio or nombre_ejercicio.upper() in ["INSTRUCCIONES", "CONSEJOS"]:
                print(f"❌ Nombre inválido detectado en {nombre_archivo}: '{nombre_ejercicio}'. Reintentando...")
                continue

            # --- LIMPIEZA LOCAL Y FORMATEO DE TÍTULOS ---
            texto_transcrito = texto_transcrito.replace('\n', ' ')
            texto_transcrito = re.sub(r' +', ' ', texto_transcrito).strip()

            texto_transcrito = re.sub(r'\b(INSTRUCCIONES|CONSEJOS)\b(?!\s*:)', r'\1:', texto_transcrito, flags=re.IGNORECASE)
            texto_transcrito = re.sub(r'\b(INSTRUCCIONES|CONSEJOS):(\S)', r'\1: \2', texto_transcrito, flags=re.IGNORECASE)

            ejercicios_globales[nombre_ejercicio] = texto_transcrito
            hubo_cambios = True

            nombre_seguro = "".join(x for x in nombre_ejercicio if x.isalnum() or x in "._- ")
            ruta_destino = os.path.join(CARPETA_EJERCICIOS, f"{nombre_seguro}{ext.lower()}")

            if os.path.exists(ruta_destino):
                os.remove(ruta_destino)

            os.rename(ruta_origen, ruta_destino)
            print(f"💾 Éxito: Imagen renombrada a '{nombre_seguro}{ext.lower()}' e indexada.")

        except Exception as e:
            error_msg = str(e).lower()
            print(f"❌ Error al procesar la imagen {nombre_archivo}: {e}")
            if any(k in error_msg for k in ["quota", "limit", "exhausted", "429", "token"]):
                print("\n🛑 [DETENCIÓN DE SEGURIDAD] Se detectó un límite de tokens o cuotas en Gemini.")
                break

    if hubo_cambios:
        guardar_ejercicios_globales_ordenados(ejercicios_globales)
        print(f"📝 Archivo '{ARCHIVO_EJERCICIOS}' guardado y actualizado con éxito.")

async def generar_audio_palabra(palabra, velocidad=VELOCIDAD_NORMAL):
    comunicacion = edge_tts.Communicate(palabra, VOZ, rate=velocidad)
    buffer = io.BytesIO()
    async for chunk in comunicacion.stream():
        if chunk["type"] == "audio":
            buffer.write(chunk["data"])
    buffer.seek(0)
    return AudioSegment.from_file(buffer, format="mp3")

async def generar_audio_ejercicio(nombre_ejercicio, texto_instrucciones, segundos, cambio_lado, audio_cambio_base, audio_preparacion_siguiente):
    ms_bloque_2s = 2000
    ms_bloque_4s = 4000

    texto_anuncio = f"Ejercicio por empezar. {nombre_ejercicio}."
    audio_anuncio_base = await generar_audio_palabra(texto_anuncio, VELOCIDAD_NORMAL)
    silencio_anuncio = AudioSegment.silent(duration=max(0, ms_bloque_2s - len(audio_anuncio_base)))
    audio_anuncio_final = (audio_anuncio_base + silencio_anuncio)[:ms_bloque_2s]

    texto_completo_ejercicio = f"{nombre_ejercicio}. {texto_instrucciones}"
    comunicacion = edge_tts.Communicate(texto_completo_ejercicio, VOZ, rate=VELOCIDAD_RAPIDA)
    audio_buffer = io.BytesIO()
    
    async for chunk in comunicacion.stream():
        if chunk["type"] == "audio":
            audio_buffer.write(chunk["data"])
            
    audio_buffer.seek(0)
    audio_voz_rapida = AudioSegment.from_file(audio_buffer, format="mp3")
    
    ms_originales = int(segundos * 1000)
    ms_base_rapida = len(audio_voz_rapida)
    
    if ms_base_rapida >= ms_originales:
        audio_ejecucion_plana = audio_voz_rapida[:ms_originales]
    else:
        veces_completas = ms_originales // ms_base_rapida
        resto_ms = ms_originales % ms_base_rapida
        audio_ejecucion_plana = (audio_voz_rapida * veces_completas) + audio_voz_rapida[:resto_ms]
    
    audio_ejecucion_plana = audio_ejecucion_plana.fade_out(500)

    if cambio_lado:
        mitad_ms = ms_originales // 2
        silencio_aviso = AudioSegment.silent(duration=max(0, ms_bloque_4s - len(audio_cambio_base)))
        bloque_cambio = (audio_cambio_base + silencio_aviso)[:ms_bloque_4s]
        audio_ejecucion_final = audio_ejecucion_plana[:mitad_ms] + bloque_cambio + audio_ejecucion_plana[mitad_ms:]
    else:
        audio_ejecucion_final = audio_ejecucion_plana

    silencio_relleno = AudioSegment.silent(duration=max(0, ms_bloque_4s - len(audio_preparacion_siguiente)))
    bloque_preparacion = (audio_preparacion_siguiente + silencio_relleno)[:ms_bloque_4s]
    
    audio_bloque_total = audio_anuncio_final + audio_ejecucion_final + bloque_preparacion
    return audio_bloque_total

async def principal(nombres_rutinas):
    rutinas_config = cargar_rutinas()

    if isinstance(nombres_rutinas, str):
        nombres_rutinas = [nombres_rutinas]

    for nr in nombres_rutinas:
        if nr not in rutinas_config:
            print(f"❌ La rutina '{nr}' no existe en '{ARCHIVO_RUTINAS}'.")
            return

    nombre_unificado = " + ".join(nombres_rutinas)
    nombre_seguro_unificado = "".join(x for x in nombre_unificado if x.isalnum() or x in "._- +")

    if not os.path.exists(CARPETA_RUTINAS_AUDIOS):
        os.makedirs(CARPETA_RUTINAS_AUDIOS)

    ejercicios_globales = cargar_ejercicios_globales()
    claves_ordenadas = sorted(list(ejercicios_globales.keys()))

    lista_ejercicios = []
    for nr in nombres_rutinas:
        lista_ejercicios.extend(rutinas_config[nr])
        
    cantidad_ejercicios = len(lista_ejercicios)

    # VERIFICACIÓN PREVIA DE EJERCICIOS INDEXADOS
    for ej in lista_ejercicios:
        nombre_ejercicio = ej["nombre"]
        if not buscar_ejercicio_eficiente(nombre_ejercicio, claves_ordenadas):
            print(f"\n🔍 El ejercicio '{nombre_ejercicio}' no está indexado. Verificando si hay imágenes sin procesar...")
            procesar_imagenes_nuevas_whatsapp()
            
            # Recargar la base de datos tras el escaneo
            ejercicios_globales = cargar_ejercicios_globales()
            claves_ordenadas = sorted(list(ejercicios_globales.keys()))
            
            # Verificar nuevamente
            if not buscar_ejercicio_eficiente(nombre_ejercicio, claves_ordenadas):
                print(f"🛑 [ABORTADO] El ejercicio '{nombre_ejercicio}' no está indexado ni se encontraron imágenes para procesarlo. No se generará el audio.")
                return

    print("🎙️ Inicializando alertas de voz...")
    audio_cambio_base = await generar_audio_palabra("Cambio de lado.", VELOCIDAD_NORMAL)

    print(f"\n🚀 Iniciando generación de la rutina unificada: {nombre_unificado}")
    
    audio_completo_rutina = AudioSegment.empty()

    for i in range(cantidad_ejercicios):
        ej = lista_ejercicios[i]
        nombre_ejercicio = ej["nombre"]
        segundos = ej["seg"]
        cambio_lado = ej.get("cambio_lado", False)

        instrucciones = ejercicios_globales[nombre_ejercicio]
        
        if i + 1 < cantidad_ejercicios:
            siguiente_nombre = lista_ejercicios[i + 1]["nombre"]
            texto_preparacion = f"Preparación para el próximo ejercicio. {siguiente_nombre}."
        else:
            texto_preparacion = "Rutina finalizada. Excelente entrenamiento."
            
        audio_preparacion_siguiente = await generar_audio_palabra(texto_preparacion, VELOCIDAD_NORMAL)
        
        audio_fragmento = await generar_audio_ejercicio(
            nombre_ejercicio,
            instrucciones, 
            segundos, 
            cambio_lado, 
            audio_cambio_base, 
            audio_preparacion_siguiente
        )
        
        audio_completo_rutina += audio_fragmento

    if len(audio_completo_rutina) > 0:
        ruta_final_unificada = os.path.join(CARPETA_RUTINAS_AUDIOS, f"{nombre_seguro_unificado}.mp3")
        
        print(f"\n💾 Exportando pista completa unificada...")
        audio_completo_rutina.export(
            ruta_final_unificada,
            format="mp3",
            bitrate="192k",
            parameters=["-id3v2_version", "3"]
        )
        print(f"✅ ¡Éxito! Archivo de audio unificado guardado en: {ruta_final_unificada}")
        
        # ABRIR LA CARPETA DE AUDIOS
        abrir_carpeta_audios(CARPETA_RUTINAS_AUDIOS)
    else:
        print("❌ No se pudo generar ningún audio para esta rutina.")

if __name__ == "__main__":
    if not os.path.exists(CARPETA_EJERCICIOS):
        os.makedirs(CARPETA_EJERCICIOS)
    if not os.path.exists(CARPETA_RUTINAS_IMAGENES):
        os.makedirs(CARPETA_RUTINAS_IMAGENES)
    if not os.path.exists(CARPETA_RUTINAS_AUDIOS):
        os.makedirs(CARPETA_RUTINAS_AUDIOS)

    procesar_imagenes_rutinas()
    procesar_imagenes_nuevas_whatsapp()
    
    rutinas_config = cargar_rutinas()
    opciones_rutinas = list(rutinas_config.keys())
    
    print("\n==========================================")
    print("      GENERADOR DE AUDIOS DE ENTRENAMIENTO")
    print("==========================================")
    print("Rutinas disponibles en la base de datos:")
    for idx, nombre_r in enumerate(opciones_rutinas, 1):
        print(f"  [{idx}] {nombre_r}")
    print("==========================================")
    print("Escribí los números de las rutinas que quieras procesar.")
    print("Si querés combinar varias, sepáralas con una coma (ejemplo: 1, 2)")
    
    seleccion = input("👉 Selección: ").strip()
    
    rutinas_elegidas = []
    partes = [p.strip() for p in seleccion.split(",") if p.strip()]
    
    for p in partes:
        if p.isdigit():
            indice = int(p) - 1
            if 0 <= indice < len(opciones_rutinas):
                rutinas_elegidas.append(opciones_rutinas[indice])
        elif p in rutinas_config:
            rutinas_elegidas.append(p)
            
    if rutinas_elegidas:
        asyncio.run(principal(rutinas_elegidas))
    else:
        print("❌ No seleccionaste ninguna rutina válida.")