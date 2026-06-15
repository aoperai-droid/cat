import logging
import tempfile
import os
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai

# ---------- ЗАГРУЗКА ТОКЕНОВ ----------
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# -------------------------------------

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

daily_messages = {}
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)


def extract_author_and_date(message):
    """
    Для пересланных — берёт оригинального автора и дату.
    Для обычных — текущего отправителя и сегодня.
    """
    # Если это пересланное сообщение
    if message.forward_origin:
        # Пытаемся вытащить оригинальную дату
        if hasattr(message.forward_origin, 'date'):
            msg_date = message.forward_origin.date.strftime("%Y-%m-%d")
        else:
            msg_date = datetime.now().strftime("%Y-%m-%d")
        
        # Пытаемся вытащить оригинального автора
        if hasattr(message.forward_origin, 'sender_user') and message.forward_origin.sender_user:
            author = message.forward_origin.sender_user.first_name or message.forward_origin.sender_user.username or "Неизвестный"
        else:
            author = "Кто-то из прошлого"
        
        return author, msg_date, True  # True = пересланное
    
    # Обычное сообщение
    author = message.from_user.first_name or message.from_user.username
    msg_date = datetime.now().strftime("%Y-%m-%d")
    return author, msg_date, False


# ---------- ОБРАБОТЧИКИ СООБЩЕНИЙ ----------
async def collect_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет текстовые сообщения, включая пересланные"""
    message = update.message
    text = message.text
    
    if text.startswith('/'):
        return
    
    author, msg_date, is_forwarded = extract_author_and_date(message)
    
    if msg_date not in daily_messages:
        daily_messages[msg_date] = []
    
    prefix = "↩️ " if is_forwarded else ""
    daily_messages[msg_date].append(f"{prefix}{author}: {text}")
    
    logging.info(f"💬 Сохранено: {author} | Пересланное: {is_forwarded}")


async def collect_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Расшифровывает голосовые, включая пересланные"""
    message = update.message
    author, msg_date, is_forwarded = extract_author_and_date(message)
    
    status_msg = await update.message.reply_text("🎙️ Расшифровываю голосовое...")
    
    try:
        voice = message.voice
        file = await context.bot.get_file(voice.file_id)
        
        with tempfile.NamedTemporaryFile(suffix=".oga", delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            tmp_path = tmp.name
        
        audio_file = genai.upload_file(tmp_path)
        response = model.generate_content([
            "Расшифруй это голосовое сообщение на русском языке. Верни ТОЛЬКО текст, без пояснений.",
            audio_file
        ])
        
        os.unlink(tmp_path)
        
        text = response.text.strip()
        if text:
            if msg_date not in daily_messages:
                daily_messages[msg_date] = []
            
            prefix = "↩️ " if is_forwarded else ""
            daily_messages[msg_date].append(f"{prefix}{author} 🎙️: {text}")
            
            await status_msg.edit_text(
                f"🎙️ {author}: «{text[:100]}{'…' if len(text) > 100 else ''}»"
            )
            logging.info(f"🎤 Голосовое от {author} расшифровано")
        else:
            await status_msg.edit_text("🤷 Не удалось разобрать слова")
    
    except Exception as e:
        logging.error(f"Ошибка голосового: {e}")
        await status_msg.edit_text("😵 Ошибка расшифровки")


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерирует шуточную сводку дня через Gemini"""
    today = datetime.now().strftime("%Y-%m-%d")
    messages = daily_messages.get(today, [])
    
    if not messages:
        await update.message.reply_text("📭 Сегодня в чате тишина. Даже котики молчат.")
        return
    
    await update.message.reply_text("⏳ Сочиняю семейную хронику...")
    
    prompt = f"""
Ты — семейный летописец с отличным чувством юмора. Прочитай логи чата за сегодня и сделай шуточную сводку дня.
Пиши в стиле "Вечерние новости" с иронией и добрыми подколами.
Придумай смешные номинации для участников:
— «Скандалист дня»
— «Главный кулинар»
— «Мемолог вечера»
— «Голосовой спамер» (если много 🎙️)

Иконка 🎙️ означает голосовое сообщение — обыграй это.
Иконка ↩️ означает пересланное сообщение из другого чата — можно пошутить про "привет из прошлого" или "архивные находки".
Не используй markdown. Максимум 150 слов.

СООБЩЕНИЯ:
{chr(10).join(messages[-50:])}
"""
    
    try:
        response = model.generate_content(prompt)
        summary = response.text
        await update.message.reply_text(f"📰 **Срочный выпуск семейных новостей:**\n\n{summary}")
    
    except Exception as e:
        logging.error(f"Ошибка генерации: {e}")
        await update.message.reply_text("🔮 Хрустальный шар запотел. Попробуйте /итоги позже.")


# ---------- ЗАПУСК ----------
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Обработчики
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_text))
    app.add_handler(MessageHandler(filters.VOICE, collect_voice))
    app.add_handler(CommandHandler("итоги", summary_command))
    
    print("👂 Бот-летописец слушает чат (включая пересланные)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
