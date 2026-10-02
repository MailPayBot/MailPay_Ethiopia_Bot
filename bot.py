import os
import logging
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# --- KEEP-ALIVE HTTP SERVER FOR RENDER WEB SERVICE ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"MailPay ET Bot is running successfully!")

    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logging.info(f"Health check web server running on port {port}")
    server.serve_forever()

# --- ENVIRONMENT VARIABLES ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
raw_admin_id = os.getenv("ADMIN_CHAT_ID", "982922116").strip().replace('"', '').replace("'", "")
ADMIN_CHAT_ID = int(raw_admin_id)

# --- CONVERSATION STATES ---
AWAITING_EMAIL_INFO, AWAITING_PAYMENT_INFO = range(2)

# --- LINKS & CONSTANTS ---
OFFICIAL_CHANNEL_URL = "https://t.me/MailPayET"  # Replace with your Telegram Channel link
WEBSITE_URL = "https://mailpay-ethiopia-bot.onrender.com"  # Replace with your Website URL

# --- IN-MEMORY SLOTS & SUBMISSIONS ---
# You can update these slot details directly whenever you have new target accounts from buyers
SLOTS = {
    1: {
        "email_format": "john.smith.et2026@gmail.com",
        "password_req": "MailPay#2026",
        "recovery_email": "rec.mailpay@gmail.com",
        "status": "AVAILABLE",
        "assigned_to": None,
        "assigned_at": None,
    },
    2: {
        "email_format": "abebe.bikila.et26@gmail.com",
        "password_req": "Ethiopia#2026",
        "recovery_email": "rec.mailpay@gmail.com",
        "status": "AVAILABLE",
        "assigned_to": None,
        "assigned_at": None,
    },
    3: {
        "email_format": "kebede.chala.et26@gmail.com",
        "password_req": "SecurePass#2026",
        "recovery_email": "rec.mailpay@gmail.com",
        "status": "AVAILABLE",
        "assigned_to": None,
        "assigned_at": None,
    },
}

submissions = {}
submission_counter = 1000
SLOT_TIMEOUT_MINUTES = 20


def release_expired_slots():
    """Auto-release slots if user didn't complete within 20 mins."""
    now = datetime.now()
    for slot_id, slot in SLOTS.items():
        if slot["status"] == "ASSIGNED" and slot["assigned_at"]:
            if now - slot["assigned_at"] > timedelta(minutes=SLOT_TIMEOUT_MINUTES):
                slot["status"] = "AVAILABLE"
                slot["assigned_to"] = None
                slot["assigned_at"] = None


def get_main_keyboard():
    """Generates the comprehensive main menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("➕ Create Gmail Account", callback_data="create_account")],
        [
            InlineKeyboardButton("ℹ️ How It Works", callback_data="how_it_works"),
            InlineKeyboardButton("📌 Requirements & Rules", callback_data="rules")
        ],
        [
            InlineKeyboardButton("💳 Payment Info", callback_data="payment_info"),
            InlineKeyboardButton("📢 Official Channel", url=OFFICIAL_CHANNEL_URL)
        ],
        [InlineKeyboardButton("🌐 Visit Website", url=WEBSITE_URL)]
    ]
    return InlineKeyboardMarkup(keyboard)


# --- USER FLOW HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler."""
    await update.message.reply_text(
        "👋 *Welcome to MailPay ET!*\n\n"
        "Earn **10 ETB** for each verified Gmail account created using our specific target details.\n\n"
        "Select an option below to get started or read our requirements.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles main menu inline buttons."""
    query = update.callback_query
    await query.answer()

    back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]])

    if query.data == "main_menu":
        await query.edit_message_text(
            "👋 *Welcome to MailPay ET!*\n\n"
            "Earn **10 ETB** for each verified Gmail account created using our specific target details.\n\n"
            "Select an option below to get started or read our requirements.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

    elif query.data == "how_it_works":
        await query.edit_message_text(
            "📋 *How MailPay ET Works:*\n\n"
            "1️⃣ Tap **'➕ Create Gmail Account'** to receive assigned target creation details.\n"
            "2️⃣ Go to Gmail / Google Sign-Up and create the account using the exact Email, Password, and Recovery Email provided.\n"
            "3️⃣ Return here, tap **'✅ I Have Created It'**, and submit your created credentials.\n"
            "4️⃣ Enter your Telebirr or CBE account details.\n"
            "5️⃣ Once verified by our admin, receive **10 ETB** credited within 3 days!",
            parse_mode="Markdown",
            reply_markup=back_keyboard
        )

    elif query.data == "rules":
        await query.edit_message_text(
            "📌 *Account Requirements & Creation Rules:*\n\n"
            "• **Exact Match:** You MUST use the exact Gmail address handle and password assigned to your slot.\n"
            "• **Recovery Email:** Always add the specified recovery email address during account setup.\n"
            "• **Phone Verification:** Use a valid Ethiopian phone number if Google prompts for SMS verification.\n"
            "• **Time Limit:** Each slot reservation lasts for **20 minutes**. Incomplete slots will auto-expire.\n"
            "• **No Duplicates:** Submitting fake or already-existing accounts will lead to a permanent ban.",
            parse_mode="Markdown",
            reply_markup=back_keyboard
        )

    elif query.data == "payment_info":
        await query.edit_message_text(
            "💳 *Payment Rates & Payout Details:*\n\n"
            "💰 **Rate:** 10.00 ETB per approved Gmail account\n"
            "🏦 **Supported Payment Methods:** Telebirr & Commercial Bank of Ethiopia (CBE)\n"
            "⏱ **Payout Speed:** Processed within 24 to 72 hours following admin verification\n\n"
            "Ensure your account name and phone/account number match accurately upon submission.",
            parse_mode="Markdown",
            reply_markup=back_keyboard
        )

    elif query.data == "create_account":
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
                "⚠️ *All active creation slots are currently occupied!*\n\n"
                "Please check back in 10–15 minutes as slots automatically free up.",
                parse_mode="Markdown",
                reply_markup=back_keyboard
            )
            return ConversationHandler.END

        context.user_data["current_slot"] = assigned_slot_id
        slot_data = SLOTS[assigned_slot_id]

        task_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ I Have Created It", callback_data="task_done")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
        ])

        await query.edit_message_text(
            f"🎯 *Task Assigned! (Slot #{assigned_slot_id})*\n\n"
            f"Please create a Gmail account with these **EXACT** details:\n\n"
            f"📧 **Target Email:** `{slot_data['email_format']}`\n"
            f"🔑 **Password:** `{slot_data['password_req']}`\n"
            f"🛡 **Recovery Email:** `{slot_data['recovery_email']}`\n\n"
            f"⏱ *Time Limit:* 20 Minutes\n\n"
            f"Tap **'✅ I Have Created It'** once done to submit.",
            parse_mode="Markdown",
            reply_markup=task_keyboard
        )

async def task_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts user for final created credentials."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📝 Please reply with the created **Gmail address** and **Password** to confirm:\n\n"
        "Example: `example@gmail.com | MyPassword123`",
        parse_mode="Markdown"
    )
    return AWAITING_EMAIL_INFO

async def receive_email_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stores credentials and prompts for payout details."""
    context.user_data["submission_email"] = update.message.text
    await update.message.reply_text(
        "💳 Enter your **Payment Details** (Telebirr or CBE account number + Account Name):\n\n"
        "Example: `Telebirr - 0912345678 (Zablon)`",
        parse_mode="Markdown"
    )
    return AWAITING_PAYMENT_INFO

async def receive_payment_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalizes submission and alerts Admin Panel."""
    global submission_counter
    user = update.message.from_user
    context.user_data["submission_payment"] = update.message.text
    
    submission_id = submission_counter
    submission_counter += 1
    slot_id = context.user_data.get("current_slot")
    
    submissions[submission_id] = {
        "user_id": user.id,
        "username": user.username or user.first_name,
        "email_info": context.user_data["submission_email"],
        "payment_info": context.user_data["submission_payment"],
        "status": "PENDING",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    if slot_id and slot_id in SLOTS:
        SLOTS[slot_id]["status"] = "AVAILABLE"
        SLOTS[slot_id]["assigned_to"] = None
        SLOTS[slot_id]["assigned_at"] = None

    await update.message.reply_text(
        f"✅ *Submission Received! (Ref #{submission_id})*\n\n"
        f"Your account credentials are now pending admin verification.\n"
        f"Upon approval, **10 ETB** will be transferred to your account within 3 days.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

    admin_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve (Pay 10 ETB)", callback_data=f"admin_approve_{submission_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"admin_reject_{submission_id}")
        ]
    ])

    admin_msg = (
        f"📩 *NEW GMAIL SUBMISSION #{submission_id}*\n"
        f"──────────────────────────────\n"
        f"👤 *User:* @{user.username or user.first_name} (ID: `{user.id}`)\n"
        f"📧 *Submitted Credentials:* `{context.user_data['submission_email']}`\n"
        f"🏦 *Payment Info:* `{context.user_data['submission_payment']}`\n"
        f"⏱ *Time:* {submissions[submission_id]['timestamp']}\n"
        f"──────────────────────────────\n"
        f"Status: ⏳ Pending Verification"
    )

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=admin_msg,
        parse_mode="Markdown",
        reply_markup=admin_keyboard
    )

    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels current interactive sequence."""
    await update.message.reply_text("Process cancelled.", reply_markup=get_main_keyboard())
    return ConversationHandler.END


# --- ADMIN PANEL HANDLERS ---

async def admin_decision_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes Approve and Reject actions from Admin."""
    query = update.callback_query
    await query.answer()

    data = query.data
    action, sub_id_str = data.rsplit("_", 1)
    sub_id = int(sub_id_str)

    if sub_id not in submissions:
        await query.edit_message_text("❌ Submission not found or already processed.")
        return

    sub_data = submissions[sub_id]

    if action == "admin_approve":
        sub_data["status"] = "APPROVED"
        await query.edit_message_text(
            f"✅ *SUBMISSION #{sub_id} APPROVED*\n\n"
            f"User: @{sub_data['username']}\n"
            f"Payment Details: `{sub_data['payment_info']}`\n"
            f"Status: Approved & Scheduled for Payment!",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                chat_id=sub_data["user_id"],
                text=f"🎉 *Account Approved!*\n\nYour submission (#{sub_id}) was verified. "
                     f"Your 10 ETB payment is scheduled for: `{sub_data['payment_info']}`.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Failed to notify user: {e}")

    elif action == "admin_reject":
        sub_data["status"] = "REJECTED"
        await query.edit_message_text(
            f"❌ *SUBMISSION #{sub_id} REJECTED*\n\n"
            f"User: @{sub_data['username']}\n"
            f"Credentials: `{sub_data['email_info']}`",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                chat_id=sub_data["user_id"],
                text=f"❌ *Submission Rejected*\n\n"
                     f"Your submission (#{sub_id}) could not be verified. "
                     f"Please ensure you followed all requirements and try again.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Failed to notify user: {e}")


# --- MAIN APPLICATION STARTUP ---

def main():
    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(task_done_callback, pattern="^task_done$")],
        states={
            AWAITING_EMAIL_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_email_info)],
            AWAITING_PAYMENT_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_payment_info)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(create_account|how_it_works|rules|payment_info|main_menu)$"))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(admin_decision_handler, pattern="^admin_(approve|reject)_"))

    logging.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
