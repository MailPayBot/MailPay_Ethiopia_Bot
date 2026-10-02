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
)

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
        return  # Silence standard HTTP logs in Render output

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()
# --------------------------------

# Load variables from the .env file
load_dotenv()

# Read the token from the environment
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("Error: BOT_TOKEN is missing. Please check your .env file.")

# Official Links & Support Info
SUPPORT_USERNAME = "@CHUNKLA47"
SUPPORT_URL = "https://t.me/CHUNKLA47"
CHANNEL_URL = "https://t.me/MailPayEt"
WEBSITE_URL = "https://mailpayet.github.io/daneildays-gmail.com/"

# --- PREDEFINED GMAIL SLOTS ---
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
    """Auto-release slots if a user didn't complete within 20 minutes."""
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

4️⃣ Send evidence of creation to our support admin (@CHUNKLA47).

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
responsible for the mistake.

Always double-check your information
before submitting it."""

FAQ_ANSWERS = {
    "faq_earn": """💰 HOW MUCH DO I EARN?

You receive 10 ETB 💵 for each Gmail account
that is successfully verified.

📊 Example:
• 1 verified account = 10 ETB
• 5 verified accounts = 50 ETB
• 10 verified accounts = 100 ETB""",

    "faq_paid": """⏱ WHEN WILL I GET PAID?

We verify your submission within 3 days.

Once your account(s) are verified, we'll tell
you when to send your payment information.

Payment is made after the verification process.""",

    "faq_submit": """📨 HOW DO I SUBMIT AN ACCOUNT?

Tap '➕ Get Gmail Task' on the main menu.

Follow the details provided (Name, Email, Password, YOB) to create the account.

After successfully creating the account, contact @CHUNKLA47 with the screenshot/evidence.""",

    "faq_remove": """📱 HOW TO LOG OUT / REMOVE AN ACCOUNT FROM YOUR DEVICE

After creating and submitting a Gmail account, you can safely remove it from your device:

🤖 ANDROID:
1. Open your phone **Settings**.
2. Tap **Passwords & Accounts** (or **Users & Accounts**).
3. Select the Gmail account you want to remove.
4. Tap **Remove Account** and confirm.

🍎 IPHONE / IPAD:
1. Open phone **Settings**.
2. Tap **Mail** (or **Accounts**).
3. Tap **Accounts** -> Select the Gmail account.
4. Tap **Delete Account** -> **Delete from My iPhone**.

💻 COMPUTER / CHROME BROWSER:
1. Go to **google.com** or **gmail.com**.
2. Click your profile picture at the top right.
3. Click **Sign out** (or **Sign out of all accounts**).
4. Click **Remove an account** to clear it from the list.""",

    "faq_rejected": """❌ WHAT IF MY SUBMISSION ISN'T VERIFIED?

Only successfully verified accounts qualify
for payment.

If a submission does not meet the requirements,
it may not be verified or paid.

Make sure you follow the instructions provided
by the admin carefully.""",

    "faq_multiple": """🔢 CAN I SUBMIT MULTIPLE ACCOUNTS?

You can submit multiple accounts, provided
that each account follows the instructions
and requirements provided by the admin.

💰 Payment is calculated as:
10 ETB × number of verified accounts.""",

    "faq_methods": """💳 WHICH PAYMENT METHODS ARE AVAILABLE?

We currently make payments through digital
payment methods available in Ethiopia:

• Telebirr
• M-Pesa (for Safaricom users)
• Commercial Bank of Ethiopia (CBE)

We will tell you when to send your payment
information after your account(s) are approved.""",

    "faq_change": """🔄 CAN I CHANGE MY PAYMENT INFORMATION?

If you need to change your payment information,
contact support before sending your payment
information.

Always make sure the information you provide
is correct.""",

    "faq_missing": """😢 WHY HAVEN'T I RECEIVED MY PAYMENT?

First, remember that your submission must be
checked and verified.

Verification can take up to 3 days.

After approval, we'll tell you when to send
your payment information.

If the verification period has passed, contact
support for help.""",
}


def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Get Gmail Task", callback_data="get_task")
        ],
        [
            InlineKeyboardButton("📚 How It Works", callback_data="how_it_works"),
            InlineKeyboardButton("💰 Payment Info", callback_data="payment_info")
        ],
        [
            InlineKeyboardButton("📋 Requirements & Rules", callback_data="requirements"),
            InlineKeyboardButton("❓ FAQ", callback_data="faq")
        ],
        [
            InlineKeyboardButton("📢 Official Channel", url=CHANNEL_URL),
            InlineKeyboardButton("🌐 Visit Website", url=WEBSITE_URL)
        ],
        [
            InlineKeyboardButton("👤 Contact Support", callback_data="support")
        ],
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
    await update.message.reply_text(
        WELCOME,
        reply_markup=main_menu()
    )


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        await query.edit_message_text(
            WELCOME,
            reply_markup=main_menu()
        )

    elif data == "get_task":
        release_expired_slots()
        user_id = query.from_user.id
        assigned_slot_id = None

        # Check if user already holds an assigned slot
        for sid, slot in SLOTS.items():
            if slot["assigned_to"] == user_id and slot["status"] == "ASSIGNED":
                assigned_slot_id = sid
                break

        # If not, assign the first available slot
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
                reply_markup=back_main()
            )
            return

        slot_data = SLOTS[assigned_slot_id]

        task_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Submit Evidence to Support", url=SUPPORT_URL)],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
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
            f"Once created, send your verification evidence to support: {SUPPORT_USERNAME}"
        )

        await query.edit_message_text(
            task_msg,
            parse_mode="Markdown",
            reply_markup=task_keyboard
        )

    elif data == "how_it_works":
        await query.edit_message_text(
            HOW_IT_WORKS,
            reply_markup=back_main()
        )

    elif data == "payment_info":
        await query.edit_message_text(
            PAYMENT_INFO,
            reply_markup=back_main()
        )

    elif data == "requirements":
        await query.edit_message_text(
            REQUIREMENTS,
            reply_markup=back_main()
        )

    elif data == "faq":
        await query.edit_message_text(
            "❓ FREQUENTLY ASKED QUESTIONS\n\nChoose a question below 👇",
            reply_markup=faq_menu()
        )

    elif data in FAQ_ANSWERS:
        await query.edit_message_text(
            FAQ_ANSWERS[data],
            reply_markup=faq_back()
        )

    elif data == "support":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Contact Support Admin", url=SUPPORT_URL)],
            [InlineKeyboardButton("📢 Official Channel", url=CHANNEL_URL)],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ])

        await query.edit_message_text(
            f"""👤 CONTACT SUPPORT

Need help or have a question?

Contact our support admin:
{SUPPORT_USERNAME}

Or visit our official channel:
{CHANNEL_URL}

Tap a button below to proceed:""",
            reply_markup=keyboard,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        WELCOME,
        reply_markup=main_menu()
    )


if __name__ == "__main__":
    # Start background web server to pass Render port scan
    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(buttons))

    print("MailPay Ethiopia bot is running...")
    app.run_polling()
