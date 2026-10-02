import os
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# --- Conversation States ---
WAITING_PAYMENT_METHOD, WAITING_PAYMENT_DETAILS = range(2)

# --- Admin Telegram Chat ID ---
# Replace this with your actual Telegram User ID so the bot sends notifications directly to you!
ADMIN_CHAT_ID =   982922116

# --- Render Port-Check Server ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"MailPay Bot is Live!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()
# --------------------------------

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("Error: BOT_TOKEN is missing. Please check your .env file.")

SUPPORT_USERNAME = "@CHUNKLA47"
SUPPORT_URL = "https://t.me/CHUNKLA47"
CHANNEL_URL = "https://t.me/MailPayEt"
WEBSITE_URL = "https://mailpayet.github.io/daneildays-gmail.com/"

SLOTS = {
    1: {
        "first_name": "Yeshitila",
        "last_name": "Lencho",
        "email": "upapeqamep699@gmail.com",
        "yob": "2001",
        "password": "sJPwvyNeoit0J",
        "status": "AVAILABLE",
        "assigned_to": None,
        "assigned_at": None,
    },
    2: {
        "first_name": "Mathewos",
        "last_name": "Kidane",
        "email": "osozosobeq893@gmail.com",
        "yob": "1996",
        "password": "UoNUj9oKgCnyTr",
        "status": "AVAILABLE",
        "assigned_to": None,
        "assigned_at": None,
    },
    3: {
        "first_name": "Bereket",
        "last_name": "Abdella",
        "email": "vudijowuv738@gmail.com",
        "yob": "2005",
        "password": "34aagpUgngPv",
        "status": "AVAILABLE",
        "assigned_to": None,
        "assigned_at": None,
    },
}

SLOT_TIMEOUT_MINUTES = 20

def release_expired_slots():
    now = datetime.now()
    for slot_id, slot in SLOTS.items():
        if slot["status"] == "ASSIGNED" and slot["assigned_at"]:
            if now - slot["assigned_at"] > timedelta(minutes=SLOT_TIMEOUT_MINUTES):
                slot["status"] = "AVAILABLE"
                slot["assigned_to"] = None
                slot["assigned_at"] = None


WELCOME = """👋 Welcome to MailPay 🇪🇹

Looking for a simple way to earn?

We provide the information you need to
participate in our Gmail account service.

Choose an option below 👇"""

HOW_IT_WORKS = """📚 HOW IT WORKS

1️⃣ Tap '➕ Get Gmail Task' to get your assigned target account details.

2️⃣ Follow the exact First Name, Last Name, Email, Year of Birth, and Password given.

3️⃣ Create the Gmail account using those details.

4️⃣ Tap '✅ I Have Created the Account' and submit your payment details.

5️⃣ Once verified (within 3 days), you receive 10 ETB per verified account!

🔄 *Note:* The info email account will update every 24 hours.

💡 Note: Once verified, you can safely log out / remove the created account from your device.

💰 Payment: 10 ETB × number of verified accounts."""

PAYMENT_INFO = """💰 PAYMENT INFO

You will receive:

10 ETB 💵 for each Gmail account
that is successfully verified.

📊 Example:
• 1 verified account = 10 ETB
• 5 verified accounts = 50 ETB
• 10 verified accounts = 100 ETB

⏳ VERIFICATION

After you submit evidence of your account
creation, we check your submission.

Verification can take up to 3 days.

Once your accounts are verified, we'll tell
you when to send your payment information.

🇪🇹 AVAILABLE PAYMENT METHODS

• Telebirr
• M-Pesa (Safaricom users)
• Commercial Bank of Ethiopia (CBE)

⚠️ Make sure your payment information is
correct before sending it to us."""

REQUIREMENTS = """📋 REQUIREMENTS & PAYMENT RULES

Before participating, please read these rules carefully:

🇪🇹 PAYMENT METHODS

We only make payments through digital
payment methods available in Ethiopia:

• Telebirr — most commonly used
• M-Pesa — for Safaricom users
• Commercial Bank of Ethiopia (CBE)

💰 PAYMENT PROCESS

After your account has been checked and
approved, we will tell you when to send
your payment information.

⚠️ IMPORTANT

Please check your payment information
carefully before sending it to us.

If you provide an incorrect phone number
or bank account number and the payment is
sent to the wrong account, MailPay is not
responsible for the mistake."""

FAQ_ANSWERS = {
    "faq_earn": """💰 HOW MUCH DO I EARN?

You receive 10 ETB 💵 for each Gmail account
that is successfully verified.""",
    "faq_paid": """⏱ WHEN WILL I GET PAID?

We verify your submission within 3 days.
Payment is made after the verification process.""",
    "faq_submit": """📨 HOW DO I SUBMIT AN ACCOUNT?

Tap '➕ Get Gmail Task', follow the account details, and click '✅ I Have Created the Account' when finished.""",
    "faq_remove": """📱 HOW TO LOG OUT / REMOVE AN ACCOUNT FROM YOUR DEVICE

After creating and submitting a Gmail account, you can safely remove it from your device via phone Settings.""",
    "faq_rejected": """❌ WHAT IF MY SUBMISSION ISN'T VERIFIED?

Only successfully verified accounts qualify for payment.""",
    "faq_multiple": """🔢 CAN I SUBMIT MULTIPLE ACCOUNTS?

You can submit multiple accounts, provided that each account follows instructions.""",
    "faq_methods": """💳 WHICH PAYMENT METHODS ARE AVAILABLE?

Telebirr, M-Pesa, or Commercial Bank of Ethiopia (CBE).""",
    "faq_change": """🔄 CAN I CHANGE MY PAYMENT INFORMATION?

Contact support before sending payment info if changes are needed.""",
    "faq_missing": """😢 WHY HAVEN'T I RECEIVED MY PAYMENT?

Verification takes up to 3 days. Contact support if the period has passed.""",
}


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Get Gmail Task", callback_data="get_task")],
        [
            InlineKeyboardButton("📚 How It Works", callback_data="how_it_works"),
            InlineKeyboardButton("💰 Payment Info", callback_data="payment_info"),
        ],
        [
            InlineKeyboardButton("📋 Requirements & Rules", callback_data="requirements"),
            InlineKeyboardButton("❓ FAQ", callback_data="faq"),
        ],
        [
            InlineKeyboardButton("📢 Official Channel", url=CHANNEL_URL),
            InlineKeyboardButton("🌐 Visit Website", url=WEBSITE_URL),
        ],
        [InlineKeyboardButton("👤 Contact Support", callback_data="support")],
    ])


def back_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
    ])


def faq_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 How much do I earn?", callback_data="faq_earn")],
        [InlineKeyboardButton("⏱ When will I get paid?", callback_data="faq_paid")],
        [InlineKeyboardButton("📨 How do I submit an account?", callback_data="faq_submit")],
        [InlineKeyboardButton("📱 How to remove / log out account?", callback_data="faq_remove")],
        [InlineKeyboardButton("❌ What if my submission isn't verified?", callback_data="faq_rejected")],
        [InlineKeyboardButton("🔢 Can I submit multiple accounts?", callback_data="faq_multiple")],
        [InlineKeyboardButton("💳 Which payment methods are available?", callback_data="faq_methods")],
        [InlineKeyboardButton("🔄 Can I change my payment information?", callback_data="faq_change")],
        [InlineKeyboardButton("😢 Why haven't I received my payment?", callback_data="faq_missing")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
    ])


def faq_back():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to FAQ", callback_data="faq")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, reply_markup=main_menu())


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        await query.edit_message_text(WELCOME, reply_markup=main_menu())

    elif data == "get_task":
        release_expired_slots()
        user_id = query.from_user.id
        assigned_slot_id = None

        for sid, slot in SLOTS.items():
            if slot["assigned_to"] == user_id and slot["status"] == "ASSIGNED":
                assigned_slot_id = sid
                break

        if not assigned_slot_id:
            for sid, slot in SLOTS.items():
                if slot["status"] == "AVAILABLE":
                    slot["status"] = "ASSIGNED"
                    slot["assigned_to"] = user_id
                    slot["assigned_at"] = datetime.now()
                    assigned_slot_id = sid
                    break

        if not assigned_slot_id:
            await query.edit_message_text(
                "⚠️ *All available account tasks are currently in use!*\n\n"
                "Please check back in 15–20 minutes once a task frees up.",
                parse_mode="Markdown",
                reply_markup=back_main(),
            )
            return

        slot_data = SLOTS[assigned_slot_id]

        task_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ I Have Created the Account", callback_data="account_created")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ])

        task_msg = (
            f"🎯 *ASSIGNED GMAIL TASK (Slot #{assigned_slot_id})*\n\n"
            f"Please create the Gmail account using these **EXACT** details:\n\n"
            f"👤 **First Name:** `{slot_data['first_name']}`\n"
            f"👤 **Last Name:** `{slot_data['last_name']}`\n"
            f"📧 **Email:** `{slot_data['email']}`\n"
            f"🎂 **Year of Birth:** `{slot_data['yob']}`\n"
            f"🔑 **Password:** `{slot_data['password']}`\n\n"
            f"⏱ *Time Limit:* 20 Minutes\n"
            f"🔄 *Note:* The info email account will update every 24 hours.\n\n"
            f"Once created, click the button below to submit your payment details!"
        )

        await query.edit_message_text(task_msg, parse_mode="Markdown", reply_markup=task_keyboard)

    elif data == "how_it_works":
        await query.edit_message_text(HOW_IT_WORKS, reply_markup=back_main())

    elif data == "payment_info":
        await query.edit_message_text(PAYMENT_INFO, reply_markup=back_main())

    elif data == "requirements":
        await query.edit_message_text(REQUIREMENTS, reply_markup=back_main())

    elif data == "faq":
        await query.edit_message_text(
            "❓ FREQUENTLY ASKED QUESTIONS\n\nChoose a question below 👇",
            reply_markup=faq_menu(),
        )

    elif data in FAQ_ANSWERS:
        await query.edit_message_text(FAQ_ANSWERS[data], reply_markup=faq_back())

    elif data == "support":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Contact Support Admin", url=SUPPORT_URL)],
            [InlineKeyboardButton("📢 Official Channel", url=CHANNEL_URL)],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ])

        await query.edit_message_text(
            f"👤 CONTACT SUPPORT\n\nNeed help or have a question?\n\nContact our support admin:\n{SUPPORT_USERNAME}\n\nOr visit our official channel:\n{CHANNEL_URL}",
            reply_markup=keyboard,
        )


# --- PAYMENT & SUBMISSION FLOW ---
async def start_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    method_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Telebirr", callback_data="method_Telebirr")],
        [InlineKeyboardButton("M-Pesa", callback_data="method_M-Pesa")],
        [InlineKeyboardButton("Commercial Bank of Ethiopia (CBE)", callback_data="method_CBE")],
    ])

    await query.edit_message_text(
        "💳 *SELECT YOUR PAYMENT METHOD*\n\nPlease choose where you would like to receive your payment:",
        parse_mode="Markdown",
        reply_markup=method_keyboard,
    )
    return WAITING_PAYMENT_METHOD


async def select_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    method = query.data.replace("method_", "")
    context.user_data["payment_method"] = method

    await query.edit_message_text(
        f"📱 *ENTER YOUR {method.upper()} DETAILS*\n\n"
        f"Please reply with your phone number or account number for **{method}**:",
        parse_mode="Markdown",
    )
    return WAITING_PAYMENT_DETAILS


async def receive_payment_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_details = update.message.text
    method = context.user_data.get("payment_method", "Unknown Method")
    user = update.message.from_user

    # Find user's assigned slot
    assigned_slot = None
    for sid, slot in SLOTS.items():
        if slot["assigned_to"] == user.id:
            assigned_slot = slot
            break

    slot_email = assigned_slot["email"] if assigned_slot else "Unknown Email"

    # Send notification to Admin
    if ADMIN_CHAT_ID:
        try:
            admin_msg = (
                f"🚨 *NEW ACCOUNT CREATED!*\n\n"
                f"👤 **User:** @{user.username or 'No Username'} (ID: `{user.id}`)\n"
                f"📧 **Assigned Email:** `{slot_email}`\n"
                f"💳 **Payment Method:** {method}\n"
                f"🔢 **Payment Details:** `{user_details}`"
            )
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Failed to send notification to admin: {e}")

    # Confirmation message to user
    await update.message.reply_text(
        "🎉 *You have successfully created the account!*\n\n"
        "Once it is verified, you will get paid **10 ETB** per account.\n\n"
        "Thank you for participating with MailPay 🇪🇹",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )

    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, reply_markup=main_menu())


if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_submission, pattern="^account_created$")],
        states={
            WAITING_PAYMENT_METHOD: [CallbackQueryHandler(select_payment_method, pattern="^method_")],
            WAITING_PAYMENT_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_payment_details)],
        },
        fallbacks=[],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(buttons))

    print("MailPay Ethiopia bot is running...")
    app.run_polling()
