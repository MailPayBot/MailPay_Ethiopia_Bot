import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Admin ID & Bot Token
ADMIN_ID = os.getenv("ADMIN_ID")  # Set your Telegram ID in environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")

# User language preference storage (In-memory storage)
user_languages = {}

# --- KEYBOARDS ---

def get_main_keyboard(lang):
    if lang == 'am':
        keyboard = [
            [KeyboardButton("➕ የጂሜይል ስራ አግኝ")],
            [KeyboardButton("📸 ስክሪንሾት ላክ")],
            [KeyboardButton("🌐 ማህበራዊ ሚዲያ"), KeyboardButton("⏰ የስራ ሰዓት")],
            [KeyboardButton("🌐 ቋንቋ ቀይር (Language)")]
        ]
    else:
        keyboard = [
            [KeyboardButton("➕ Get Gmail Task")],
            [KeyboardButton("📸 Submit Screenshot")],
            [KeyboardButton("🌐 Social Media"), KeyboardButton("⏰ Working Hours")],
            [KeyboardButton("🌐 Switch Language")]
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_language_keyboard():
    keyboard = [
        [KeyboardButton("🇬🇧 English"), KeyboardButton("🇪🇹 አማርኛ")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_languages:
        await update.message.reply_text(
            "Welcome to MailPay ET! / ወደ MailPay ET እንኳን ደህና መጡ!\n\nPlease select your preferred language / እባክዎን ቋንቋ ይምረጡ:",
            reply_markup=get_language_keyboard()
        )
    else:
        lang = user_languages[user_id]
        msg = (
            "እንኳን ወደ MailPay ET በደህና መጡ! ለእያንዳንዱ ከተረጋገጠ አካውንት 10 ETB ያግኙ።"
            if lang == 'am' else
            "Welcome back to MailPay ET! Earn 10 ETB for every verified Gmail account."
        )
        await update.message.reply_text(msg, reply_markup=get_main_keyboard(lang))

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if "English" in text:
        user_languages[user_id] = 'en'
        await update.message.reply_text(
            "Language set to English! 🇬🇧",
            reply_markup=get_main_keyboard('en')
        )
    elif "አማርኛ" in text:
        user_languages[user_id] = 'am'
        await update.message.reply_text(
            "ቋንቋው ወደ አማርኛ ተቀይሯል! 🇪🇹",
            reply_markup=get_main_keyboard('am')
        )

async def socials_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = user_languages.get(user_id, 'en')

    if lang == 'am':
        text = (
            "🌐 **የ MailPay ET ማህበራዊ ሚዲያ ገጾች:**\n\n"
            "🔹 **Facebook:** https://web.facebook.com/share/p/1MN18PyRa2/\n"
            "📸 **Instagram:** https://www.instagram.com/reel/DeFXtuQlZjo/\n"
            "💬 **WhatsApp:** https://wa.me/message/4AGHRHT64MI4K1\n"
            "🎵 **TikTok:** https://vm.tiktok.com/ZS9Aveo3qnhSJ-gMcyh/\n"
            "🌐 **ዌብሳይታችን:** https://mailpayet.github.io/MailPayET/\n\n"
            "📢 **ቻናላችን:** @MailPayEt"
        )
    else:
        text = (
            "🌐 **MailPay ET Social Media Links:**\n\n"
            "🔹 **Facebook:** https://web.facebook.com/share/p/1MN18PyRa2/\n"
            "📸 **Instagram:** https://www.instagram.com/reel/DeFXtuQlZjo/\n"
            "💬 **WhatsApp:** https://wa.me/message/4AGHRHT64MI4K1\n"
            "🎵 **TikTok:** https://vm.tiktok.com/ZS9Aveo3qnhSJ-gMcyh/\n"
            "🌐 **Official Website:** https://mailpayet.github.io/MailPayET/\n\n"
            "📢 **Official Channel:** @MailPayEt"
        )

    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)

async def working_hours_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = user_languages.get(user_id, 'en')

    if lang == 'am':
        text = (
            "⏰ **የ MailPay ET የስራ ሰዓት:**\n\n"
            "📅 **ሰኞ - አርብ (Mon - Fri):** 6:00 PM – 10:00 PM\n"
            "📅 **ቅዳሜ - እሁድ (Sat - Sun):** 12:00 PM – 10:00 PM\n\n"
            "💡 *በስራ ሰዓት ውስጥ ብቻ ተግባራትን (Tasks) ይቀበሉ።*"
        )
    else:
        text = (
            "⏰ **MailPay ET Working Hours:**\n\n"
            "📅 **Monday – Friday:** 6:00 PM – 10:00 PM\n"
            "📅 **Saturday – Sunday:** 12:00 PM – 10:00 PM\n\n"
            "💡 *Please request tasks during operational hours only.*"
        )

    await update.message.reply_text(text, parse_mode="Markdown")

async def get_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = user_languages.get(user_id, 'en')

    if lang == 'am':
        text = "እባክዎን ከAdmin ጋር በመገናኘት የተግባር መረጃዎን ይቀበሉ: @CHUNKLA47"
    else:
        text = "Please contact Admin to receive your target account details: @CHUNKLA47"

    await update.message.reply_text(text)

async def submit_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = user_languages.get(user_id, 'en')

    if lang == 'am':
        text = "እባክዎን ያጠናቀቁትን አካውንት ስክሪንሾት (Screenshot) እዚህ ይላኩ።"
    else:
        text = "Please send/upload your proof screenshot here."

    await update.message.reply_text(text)

# --- MAIN RUNNER ---

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("socials", socialshandler if 'socials_handler' in locals() else socials_handler))

    # Text Filters for Menu Buttons
    app.add_handler(MessageHandler(filters.Regex("^(🇬🇧 English|🇪🇹 አማርኛ)$"), set_language))
    app.add_handler(MessageHandler(filters.Regex("^(➕ Get Gmail Task|➕ የጂሜይል ስራ አግኝ)$"), get_task))
    app.add_handler(MessageHandler(filters.Regex("^(📸 Submit Screenshot|📸 ስክሪንሾት ላክ)$"), submit_screenshot))
    app.add_handler(MessageHandler(filters.Regex("^(🌐 Social Media|🌐 ማህበራዊ ሚዲያ)$"), socials_handler))
    app.add_handler(MessageHandler(filters.Regex("^(⏰ Working Hours|⏰ የስራ ሰዓት)$"), working_hours_handler))
    app.add_handler(MessageHandler(filters.Regex("^(🌐 Switch Language|🌐 ቋንቋ ቀይር \(Language\))$"), start))

    app.run_polling()

if __name__ == '__main__':
    main()
