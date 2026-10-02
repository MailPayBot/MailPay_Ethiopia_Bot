import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
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

# --- LOAD ENVIRONMENT VARIABLES ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

# --- CONVERSATION STATES ---
AWAITING_EMAIL_INFO, AWAITING_PAYMENT_INFO = range(2)

# --- IN-MEMORY DATABASE & SLOTS (3-Slot Buffer) ---
# Update the 'info' strings below with the exact Gmail formatting instructions provided by your buyers/agencies
SLOTS = {
    1: {
        "provider": "Agency Slot 1",
        "info": "Format: Firstname Lastname + 3 random numbers (e.g. JohnDoe482@gmail.com)\nPassword rules: Strong password with symbols (e.g. Pass#2026!)",
        "status": "AVAILABLE",
        "assigned_to": None,
        "assigned_at": None,
    },
    2: {
        "provider": "Agency Slot 2",
        "info": "Format: Standard English names only\nPassword rules: Must end with 2026 (e.g. Account2026)",
        "status": "AVAILABLE",
        "assigned_to": None,
        "assigned_at": None,
    },
    3: {
        "provider": "Agency Slot 3",
        "info": "Format: Random 8-character string\nPassword rules: Minimum 10 characters",
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


# --- USER FLOW HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler."""
    keyboard = [
        [InlineKeyboardButton("➕ Create Gmail Account", callback_data="create_account")],
        [InlineKeyboardButton("ℹ️ How It Works", callback_data="how_it_works")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Welcome to MailPay ET!\n\n"
        "Earn 10 ETB for each verified Gmail account created using our admin instructions. "
        "Payouts are processed within 3 days of approval.",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles main menu inline buttons."""
    query = update.callback_query
    await query.answer()

    if query.data == "how_it_works":
        await query.edit_message_text(
            "📋 *How MailPay ET Works:*\n\n"
            "1️⃣ Tap 'Create Gmail Account' to get an active slot and creation instructions.\n"
            "2️⃣ Follow the exact creation format given by the admin.\n"
            "3️⃣ Submit the created Gmail & password + your Telebirr/CBE payout details.\n"
            "4️⃣ Once verified by admin, you will receive 10 ETB within 3 days!",
            parse_mode="Markdown"
        )
    elif query.data == "create_account":
        release_expired_slots()
        
        assigned_slot_id = None
        user_id = query.from_user.id

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
                "⚠️ All 3 active creation slots are currently in use!\n\n"
                "Please try again in 15–20 minutes once a slot frees up."
            )
            return ConversationHandler.END

        context.user_data["current_slot"] = assigned_slot_id

        keyboard = [[InlineKeyboardButton("✅ I Have Created It", callback_data="task_done")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        slot_data = SLOTS[assigned_slot_id]
        await query.edit_message_text(
            f"🎯 *Task Assigned! (Slot #{assigned_slot_id})*\n\n"
            f"📌 *Admin Instructions for Creation:*\n"
            f"{slot_data['info']}\n\n"
            f"⚠️️ *Important:* You have 20 minutes to complete this slot. "
            f"Once created, tap the button below to submit your credentials.",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

async def task_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts user for Gmail credentials."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📝 Please reply with the *Gmail address* and *Password* you created:\n\n"
        "Example: `example@gmail.com | MyPassword123`",
        parse_mode="Markdown"
    )
    return AWAITING_EMAIL_INFO

async def receive_email_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stores email info and prompts for payment details."""
    context.user_data["submission_email"] = update.message.text
    await update.message.reply_text(
        "💳 Great! Now enter your *Payment Info* (Telebirr or CBE account number and Account Name):\n\n"
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
        f"Your Gmail submission is now pending verification.\n"
        f"Once verified, 10 ETB will be sent to your payment info within 3 days.",
        parse_mode="Markdown"
    )

    admin_keyboard = [
        [
            InlineKeyboardButton("✅ Approve (Pay 10 ETB)", callback_data=f"admin_approve_{submission_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"admin_reject_{submission_id}")
        ]
    ]
    admin_markup = InlineKeyboardMarkup(admin_keyboard)

    admin_msg = (
        f"📩 *NEW GMAIL SUBMISSION #{submission_id}*\n"
        f"──────────────────────────────\n"
        f"👤 *User:* @{user.username or user.first_name} (ID: `{user.id}`)\n"
        f"📧 *Credentials:* `{context.user_data['submission_email']}`\n"
        f"🏦 *Payment Details:* `{context.user_data['submission_payment']}`\n"
        f"⏱ *Submitted:* {submissions[submission_id]['timestamp']}\n"
        f"──────────────────────────────\n"
        f"Status: ⏳ Pending Verification"
    )

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=admin_msg,
        parse_mode="Markdown",
        reply_markup=admin_markup
    )

    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels conversation if user types /cancel."""
    await update.message.reply_text("Process cancelled.")
    return ConversationHandler.END


# --- ADMIN PANEL HANDLERS ---

async def admin_decision_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes Approve and Reject buttons pressed by Admin."""
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
            f"✅ *SUBMISSION #{sub_id} APPROVED*\n"
            f"User: @{sub_data['username']}\n"
            f"Payment Details: `{sub_data['payment_info']}`\n"
            f"Status: Approved & Scheduled for Payout!",
            parse_mode="Markdown"
        )

        try:
            await context.bot.send_message(
                chat_id=sub_data["user_id"],
                text=f"🎉 *Account Approved!*\n\nYour Gmail submission (#{sub_id}) has been verified. "
                     f"Your 10 ETB payment is being processed to: `{sub_data['payment_info']}`.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Could not notify user: {e}")

    elif action == "admin_reject":
        sub_data["status"] = "REJECTED"

        await query.edit_message_text(
            f"❌ *SUBMISSION #{sub_id} REJECTED*\n"
            f"User: @{sub_data['username']}\n"
            f"Email: `{sub_data['email_info']}`",
            parse_mode="Markdown"
        )

        try:
            await context.bot.send_message(
                chat_id=sub_data["user_id"],
                text=f"❌ *Submission Rejected*\n\n"
                     f"Your Gmail submission (#{sub_id}) could not be verified or did not meet requirements. "
                     f"Please try again or contact support.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Could not notify user: {e}")


# --- MAIN APPLICATION STARTUP ---

def main():
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
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(create_account|how_it_works)$"))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(admin_decision_handler, pattern="^admin_(approve|reject)_"))

    logging.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
