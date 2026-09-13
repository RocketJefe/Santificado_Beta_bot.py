import logging
import os
import io
import urllib.parse
from dotenv import load_dotenv

from telegram import Update, constants
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
import google.generativeai as genai
from PIL import Image
import requests

# 1. Variables de entorno
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_KEY = os.getenv("GOOGLE_API_KEY")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

if not TELEGRAM_TOKEN or not GOOGLE_KEY:
    logging.error("ERROR: Faltan credenciales en el entorno (.env o panel de la nube).")
    exit(1)

# 2. Inicialización de Gemini 3.8 Flash
genai.configure(api_key=GOOGLE_KEY)
MODEL_NAME = "models/gemini-3.8-flash"

try:
    vision_model = genai.GenerativeModel(MODEL_NAME)
    logging.info(f"Santificado_Beta iniciado con {MODEL_NAME}")
except Exception as e:
    logging.error(f"Error fatal al inicializar Gemini: {e}")
    exit(1)

# Memoria de prompts de estilo por usuario
user_styles = {}

# 3. Funciones de IA
def extraer_estilo_base(imagen_bytes):
    """Fase 1: Extrae la estética y crea el prompt maestro listo para usar."""
    try:
        img = Image.open(io.BytesIO(imagen_bytes))
    except Exception as e:
        return f"Error al abrir la imagen: {e}"

    instruccion = (
        "Analyze this image in extreme aesthetic detail. "
        "Extract the exact lighting style, color grading, shadows, rim lights, textures, materials, and overall mood. "
        "Formulate a precise generative prompt in English describing ONLY this visual style and lighting atmosphere "
        "so that it can be applied to any subject. Do not include introductory text, return only the ready prompt."
    )

    try:
        respuesta = vision_model.generate_content(contents=[img, instruccion])
        if not respuesta.text:
            return "No se obtuvo respuesta del análisis de estilo."
        return respuesta.text.strip()
    except Exception as e:
        return f"Error Gemini: {e}"

def describir_sujeto_destino(imagen_bytes):
    """Fase 2: Extrae únicamente la estructura física de la imagen a transformar."""
    try:
        img = Image.open(io.BytesIO(imagen_bytes))
    except Exception as e:
        return f"Error al abrir la imagen: {e}"

    instruccion = (
        "Describe ONLY the structural content, key figures, pose, layout, and subject composition in this image. "
        "Strictly DO NOT mention colors, lighting, or artistic medium. "
        "Keep it to one concise English sentence focused purely on what is physically depicted."
    )

    try:
        respuesta = vision_model.generate_content(contents=[img, instruccion])
        if not respuesta.text:
            return "No se obtuvo descripción estructural."
        return respuesta.text.strip()
    except Exception as e:
        return f"Error Gemini: {e}"

def renderizar_fusion(sujeto, estilo):
    """Generación final en Pollinations (Flux)."""
    prompt_final = f"{sujeto}, {estilo}, highly detailed, cinematic lighting, edge-to-edge full scene composition, masterpiece"
    prompt_encoded = urllib.parse.quote(prompt_final)
    url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1024&height=1024&nologo=true&model=flux"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        res = requests.get(url, headers=headers, timeout=120)
        if res.status_code == 200 and len(res.content) > 5000:
            return res.content
    except Exception as e:
        logging.error(f"Error Pollinations: {e}")
    return None

# 4. Handlers de Telegram
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_styles.pop(update.effective_user.id, None)
    texto = (
        "🕊️ **Santificado Beta Bot**\n\n"
        "**Flujo de trabajo:**\n"
        "1. Envía una imagen de referencia para extraer su prompt de estilo.\n"
        "2. Recibirás el prompt listo para usar en cualquier plataforma.\n"
        "3. Envía la imagen base que quieres transformar.\n\n"
        "Envía la primera foto para comenzar."
    )
    await update.message.reply_text(texto, parse_mode=constants.ParseMode.MARKDOWN)

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_styles.pop(update.effective_user.id, None)
    await update.message.reply_text("🔄 Sesión reseteada. Envía una nueva imagen de estilo.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message

    photo_file = await message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()

    # PASO 1: Extracción del prompt de estilo
    if user_id not in user_styles:
        status_msg = await message.reply_text("🔍 Analizando estilo y generando prompt maestro con Gemini 3.8 Flash...")
        prompt_estilo = extraer_estilo_base(photo_bytes)

        if "Error" in prompt_estilo:
            await status_msg.edit_text(f"❌ Falló el análisis: {prompt_estilo}")
            return

        user_styles[user_id] = prompt_estilo

        texto_respuesta = (
            "✅ **Prompt maestro recopilado:**\n\n"
            f"```text\n{prompt_estilo}\n```\n\n"
            "📥 **Listo:** Envía ahora la imagen que deseas transformar con este estilo.\n"
            "_(Usa /reset para cambiar de referencia)_"
        )
        await status_msg.edit_text(texto_respuesta, parse_mode=constants.ParseMode.MARKDOWN)

    # PASO 2: Transformación estructural
    else:
        estilo_activo = user_styles[user_id]
        status_msg = await message.reply_text("⏳ Analizando composición base y aplicando estilo...")

        sujeto = describir_sujeto_destino(photo_bytes)
        if "Error" in sujeto:
            await status_msg.edit_text(f"❌ Error estructural: {sujeto}")
            return

        await status_msg.edit_text("🎨 Renderizando resultado final...")
        imagen_final = renderizar_fusion(sujeto, estilo_activo)

        if not imagen_final:
            await status_msg.edit_text("❌ Error al renderizar la imagen final.")
            return

        await status_msg.edit_text("✅ ¡Transformación completada!")
        await message.reply_photo(
            photo=io.BytesIO(imagen_final),
            caption=(
                "🕊️ **Santificado Beta - Render Final**\n\n"
                f"**Estructura base:** _{sujeto}_\n\n"
                "Puedes enviar otra imagen para seguir transformando, o /reset para un nuevo estilo."
            ),
            parse_mode=constants.ParseMode.MARKDOWN,
        )

# 5. Arranque
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("-------------------------------------------------------")
    print("🕊️ SANTIFICADO BETA BOT ONLINE (GEMINI 3.8 FLASH) 🕊️")
    print("-------------------------------------------------------")
    app.run_polling()
