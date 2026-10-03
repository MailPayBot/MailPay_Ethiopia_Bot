import os
import threading
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
WAITING_SCREENSHOT, WAITING_PAYMENT_METHOD, WAITING_PAYMENT_DETAILS, WAITING_RECEIPT_PHOTO = range(4)

# --- Admin Telegram Configuration ---
# ⚠️ IMPORTANT: Replace 123456789 with your actual numeric Telegram User ID!
ADMIN_CHAT_ID = 982922116
SUPPORT_USERNAME = "@CHUNKLA47"
SUPPORT_URL = "https://t.me/CHUNKLA47"
CHANNEL_URL = "https://t.me/MailPayEt"
WEBSITE_URL = "https://mailpayet.github.io/daneildays-gmail.com/"

# --- Render Health Check Server ---
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

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("Error: BOT_TOKEN is missing. Please check your environment variables.")

# --- Text Content ---
WELCOME = """👋 Welcome to MailPay 🇪🇹

Looking for a simple way to earn?

We provide the information you need to
participate in our Gmail account service.

Choose an option below 👇"""

HOW_IT_WORKS = """📚 HOW IT WORKS

1️⃣ Tap '➕ Get Gmail Task' to contact our Admin for your account details.

2️⃣ Create the Gmail account using the exact details given by the Admin.

3️⃣ Tap '📸 Submit Screenshot' to upload proof of the created account.

4️⃣ Once verified by Admin, you earn 10 ETB per verified account!

5️⃣ Enter your payment details (Telebirr, M-Pesa, or CBE) to receive your payout and receipt.

💰 Payment: 10 ETB × number of verified accounts."""

PAYMENT_INFO = """💰 PAYMENT INFO

You will receive:
10 ETB 💵 for each Gmail account successfully verified.

📊 Example:
• 1 verified account = 10 ETB
• 5 verified accounts = 50 ETB
• 10 verified accounts = 100 ETB

⏳ VERIFICATION
Verification and payout receipts are processed within 3 days after submission.

🇪🇹 AVAILABLE PAYMENT METHODS
• Telebirr
• M-Pesa (Safaricom users)
• Commercial Bank of Ethiopia (CBE)"""

REQUIREMENTS = """📋 REQUIREMENTS & PAYMENT RULES

• Follow the exact credentials given by the Admin.
• Make sure your payment details are completely accurate before submitting.
• MailPay is not responsible for transfers sent to incorrect account numbers provided by users."""

FAQ_ANSWERS = {
    "faq_earn": "💰 HOW MUCH DO I EARN?\nYou receive 10 ETB for each verified Gmail account.",
    "faq_paid": "⏱ WHEN WILL I GET PAID?\nVerification and payout occur within 3 days of submission.",
    "faq_submit": "📨 HOW DO I SUBMIT AN ACCOUNT?\nContact Admin for details, then use '📸 Submit Screenshot' to submit proof.",
    "faq_methods": "💳 WHICH PAYMENT METHODS ARE AVAILABLE?\nTelebirr, M-Pesa, or Commercial Bank of Ethiopia (CBE).",
}

# --- Keyboards ---
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Get Gmail Task", callback_data="get_task")],
        [InlineKeyboardButton("📸 Submit Screenshot", callback_data="start_submit_screenshot")],
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
        [InlineKeyboardButton("💳 Which payment methods are available?", callback_data="faq_methods")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
    ])

def faq_back():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to FAQ", callback_data="faq")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ])

# --- Core Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, reply_markup=main_menu())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, reply_markup=main_menu())

# --- Menu Callback Handler ---
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        await query.edit_message_text(WELCOME, reply_markup=main_menu())

    elif data == "get_task":
        user = query.from_user
        dm_url = f"https://t.me/CHUNKLA47?text=Hi%20Admin,%20I%20want%20to%20create%20a%20Gmail%20account!%20My%20User%20ID:%20{user.id}"
        
        task_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Contact Admin to Get Account", url=dm_url)],
            [InlineKeyboardButton("📸 Submit Screenshot", callback_data="start_submit_screenshot")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ])

        msg = (
            "📌 *HOW TO GET YOUR GMAIL TASK*\n\n"
            "1. Click the button below to contact Admin directly.\n"
            "2. Admin will provide you with the target First Name, Last Name, Email, Year of Birth, and Password.\n"
            "3. Create the account using those exact details.\n"
            "4. Once created, return here and tap '📸 Submit Screenshot' to submit your proof!"
        )
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=task_keyboard)

    elif data == "how_it_works":
        await query.edit_message_text(HOW_IT_WORKS, reply_markup=back_main())

    elif data == "payment_info":
        await query.edit_message_text(PAYMENT_INFO, reply_markup=back_main())

    elif data == "requirements":
        await query.edit_message_text(REQUIREMENTS, reply_markup=back_main())

    elif data == "faq":
        await query.edit_message_text("❓ FREQUENTLY ASKED QUESTIONS\n\nChoose a question below 👇", reply_markup=faq_menu())

    elif data in FAQ_ANSWERS:
        await query.edit_message_text(FAQ_ANSWERS[data], reply_markup=faq_back())

    elif data == "support":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Contact Support Admin", url=SUPPORT_URL)],
            [InlineKeyboardButton("📢 Official Channel", url=CHANNEL_URL)],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ])
        await query.edit_message_text(
            f"👤 CONTACT SUPPORT\n\nNeed help?\nContact our support admin:\n{SUPPORT_USERNAME}\n\nOfficial channel:\n{CHANNEL_URL}",
            reply_markup=keyboard,
        )

# --- Screenshot Submission Flow ---
async def start_screenshot_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "📸 *SUBMIT ACCOUNT SCREENSHOT*\n\n"
        "Please upload a photo/screenshot showing the Gmail account you created.",
        parse_mode="Markdown",
    )
    return WAITING_SCREENSHOT

async def receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    photo_id = update.message.photo[-1].file_id

    if ADMIN_CHAT_ID:
        try:
            admin_caption = (
                f"🚨 *NEW SCREENSHOT SUBMISSION*\n\n"
                f"👤 **User:** @{user.username or 'No Username'} (ID: `{user.id}`)\n"
                f"Is this the correct Gmail account based on the provided info?"
            )
            admin_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"adm_approve_{user.id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"adm_reject_{user.id}"),
                ]
            ])
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=photo_id,
                caption=admin_caption,
                parse_mode="Markdown",
                reply_markup=admin_keyboard,
            )
        except Exception as e:
            print(f"Failed to forward screenshot to admin: {e}")

    await update.message.reply_text(
        "✅ *Screenshot received successfully!*\n\n"
        "Your submission is now under review by the Admin. You will receive a notification here once verified.",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END

# --- Admin Decision Handler ---
async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    action = parts[1]
    target_user_id = int(parts[2])

    if action == "approve":
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n✅ *STATUS: APPROVED*\nUser notified to enter payment details.",
            parse_mode="Markdown",
        )

        method_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Telebirr", callback_data=f"user_method_Telebirr_{target_user_id}")],
            [InlineKeyboardButton("M-Pesa", callback_data=f"user_method_M-Pesa_{target_user_id}")],
            [InlineKeyboardButton("Commercial Bank of Ethiopia (CBE)", callback_data=f"user_method_CBE_{target_user_id}")],
        ])

        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=(
                    "🎉 *ACCOUNT APPROVED!*\n\n"
                    "You have successfully created the account based on the provided details! "
                    "You will receive **10 ETB** within 3 days.\n\n"
                    "💳 Please select your payment method below:"
                ),
                parse_mode="Markdown",
                reply_markup=method_keyboard,
            )
        except Exception as e:
            print(f"Failed to notify user {target_user_id}: {e}")

        return ConversationHandler.END

    elif action == "reject":
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n❌ *STATUS: REJECTED*",
            parse_mode="Markdown",
        )

        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=(
                    "❌ *SUBMISSION REJECTED*\n\n"
                    "You haven't created the account based on the provided information.\n\n"
                    "Please contact Admin if you need help or try creating the account correctly."
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            print(f"Failed to notify user {target_user_id}: {e}")

        return ConversationHandler.END

# --- Payment Collection Flow ---
async def select_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    method = parts[2]
    context.user_data["payment_method"] = method

    await query.edit_message_text(
        f"📱 *ENTER YOUR {method.upper()} DETAILS*\n\n"
        f"Please reply to this message with your phone number or account number for **{method}**:",
        parse_mode="Markdown",
    )
    return WAITING_PAYMENT_DETAILS

async def receive_payment_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_details = update.message.text
    method = context.user_data.get("payment_method", "Payment Method")
    user = update.message.from_user

    if ADMIN_CHAT_ID:
        try:
            admin_msg = (
                f"💳 *PAYMENT DETAILS SUBMITTED*\n\n"
                f"👤 **User:** @{user.username or 'No Username'} (ID: `{user.id}`)\n"
                f"🏦 **Method:** {method}\n"
                f"🔢 **Details:** `{user_details}`\n\n"
                f"📸 **Next Step:** Reply to this user with their payout receipt photo once transferred."
            )
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_msg,
                parse_mode="Markdown",
            )
        except Exception as e:
            print(f"Failed to send payment details to admin: {e}")

    await update.message.reply_text(
        "🎉 *Payment details submitted!*\n\n"
        "Your payment is being processed. A payment receipt will be sent directly to this chat once the transfer is complete.\n\n"
        "Thank you for participating with MailPay 🇪🇹!",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END

# --- Admin Receipt Delivery Flow ---
async def receive_admin_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_user_id = context.user_data.get("pending_receipt_user")

    if not target_user_id:
        await update.message.reply_text("⚠️ No user session found to attach this receipt to.")
        return ConversationHandler.END

    photo_file_id = update.message.photo[-1].file_id

    try:
        receipt_caption = (
            "🎉 *GREAT NEWS! PAYMENT SENT!*\n\n"
            "Your payment of **10 ETB** has been transferred.\n\n"
            "📄 Attached above is your official payment transfer receipt.\n\n"
            "Thank you for working with MailPay 🇪🇹!"
        )
        await context.bot.send_photo(
            chat_id=target_user_id,
            photo=photo_file_id,
            caption=receipt_caption,
            parse_mode="Markdown",
        )
        await update.message.reply_text(
            f"✅ *Receipt successfully sent to user (ID: `{target_user_id}`)!*",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to deliver receipt to user: {e}")

    context.user_data.pop("pending_receipt_user", None)
    return ConversationHandler.END

# --- Main Entry Point ---
if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()

    screenshot_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_screenshot_submission, pattern="^start_submit_screenshot$")],
        states={
            WAITING_SCREENSHOT: [MessageHandler(filters.PHOTO, receive_screenshot)],
        },
        fallbacks=[],
    )

    payment_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(select_payment_method, pattern="^user_method_")],
        states={
            WAITING_PAYMENT_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_payment_details)],
        },
        fallbacks=[],
    )

    admin_receipt_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_decision, pattern="^adm_")],
        states={
            WAITING_RECEIPT_PHOTO: [MessageHandler(filters.PHOTO, receive_admin_receipt)],
        },
        fallbacks=[],
    )

    app.add_handler(screenshot_conv)
    app.add_handler(payment_conv)
    app.add_handler(admin_receipt_conv)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(buttons))

    print("MailPay Ethiopia proxy bot is running...")
    app.run_polling()
