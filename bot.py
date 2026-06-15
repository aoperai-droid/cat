import logging
import tempfile
import os
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import google.generativeai as genai

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY, transport="rest")
model = genai.GenerativeModel("gemini-1.5-flash")

daily_messages = {}
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)


def extract_author_and_date(message):
    if message.forward_origin:
        if hasattr(message.forward_origin, 'date'):
            msg_date = message.forward_origin.date.strftime("%Y-%m-%d")
        else:
            msg_date = datetime.now().strftime("%Y-%m-%d")
        
        if hasattr(message.forward_origin, 'sender_user') and message.forward_origin.sender_user:
            author = message.forward_origin.sender_user.first_name or message.forward_origin.sender_user.username or "Неизвестный"
        else:
            author = "Кто-то из прошлого"
        
        return author, msg_date, True
    
    author = message.from_user.first_name or message.from_user.username
    msg_date = datetime.now().strftime("%Y-%m-%d")
    return author, msg_date, False


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    
    if message.text and message.text.strip() == "/итоги":
        await summary_command(update, context)
        return
    
    if message.text and not message.text.startswith('/'):
        author, msg_date, is_forwarded = extract_author_and_date(message)
        
        if msg_date not in daily_messages:
            daily_messages[msg_date] = []
        
        prefix = "↩️ " if is_forwarded else ""
        daily_messages[msg_date].append(f"{prefix}{author}: {message.text}")
        logging.info(f"💬 {author}")
    
    elif message.voice:
        await collect_voice(update, context)


async def collect_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    author, msg_date, is_forwarded = extract_author_and_date(message)
    
    status_msg = await update.message.reply_text("🎙️ Расшифровываю голосовое...")
    
    try:
        voice = message.voice
        file = await context.bot.get_file(voice.file_id)
        
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            tmp_path = tmp.name
        
        audio_file = genai.upload_file(tmp_path, mime_type="audio/ogg")
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
            await status_msg.edit_text(f"🎙️ {author}: «{text[:100]}{'…' if len(text) > 100 else ''}»")
            logging.info(f"🎤 {author}: {text[:50]}...")
        else:
            await status_msg.edit_text("🤷 Не удалось разобрать слова")
    
    except Exception as e:
        logging.error(f"Ошибка голосового: {e}")
        await status_msg.edit_text("😵 Ошибка расшифровки")


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().strftime("%Y-%m-%d")
    messages = daily_messages.get(today, [])
    
    if not messages:
        await update.message.reply_text("📭 Сегодня в чате тишина. Даже котики молчат.")
        return
    
    await update.message.reply_text("⏳ Сочиняю семейную хронику...")
    
    prompt = f"""
Ты — семейный летописец с отличным чувством юмора. Прочитай логи чата за сегодня и сделай шуточную сводку дня.
Пиши в стиле "Вечерние новости" с иронией и добрыми подколами.
Придумай смешные номинации для участников.
Иконка 🎙️ означает голосовое сообщение — обыграй это.
Иконка ↩️ означает пересланное сообщение.
Не используй markdown. Максимум 150 слов.

СООБЩЕНИЯ:
{chr(10).join(messages[-50:])}
"""
    
    try:
        response = model.generate_content(prompt)
        summary = response.text
        await update.message.reply_text(f"📰 Срочный выпуск семейных новостей:\n\n{summary}")
        logging.info("✅ Сводка отправлена")
    
    except Exception as e:
        logging.error(f"Ошибка генерации: {e}")
        await update.message.reply_text("🔮 Хрустальный шар запотел. Попробуйте позже.")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE, handle_message))
    print("👂 Бот-летописец слушает чат...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
