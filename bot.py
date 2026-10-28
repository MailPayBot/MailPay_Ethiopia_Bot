import asyncio
import base64
import csv
import html
import io
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from telegram import (
    BotCommand,
    BotCommandScopeChat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    WebAppInfo,
)
from telegram.error import BadRequest, RetryAfter
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

# --- Conversation States ---
(
    WAITING_SCREENSHOT,
    WAITING_PAYMENT_DETAILS,
    WAITING_RECEIPT_PHOTO,
    WAITING_ADMIN_REPLY,
    WAITING_ADMIN_SEARCH,
    WAITING_BROADCAST,
) = range(6)
WAITING_WITHDRAW_AMOUNT = 6
WAITING_WITHDRAW_METHOD = 7
WAITING_WITHDRAW_NAME = 8
WAITING_WITHDRAW_ACCOUNT = 9

PAY_PER_ACCOUNT = 10                      # ETB paid for each verified account
EAT = timezone(timedelta(hours=3))        # Ethiopian time, used for dates in the admin panel

# --- Contact-through-the-bot settings ---
ACK_WINDOW = 30 * 60     # seconds: full auto-reply at most once per 30 min per user
TASK_COOLDOWN = 5 * 60   # seconds: stops users spamming the "Get Gmail Task" request

# --- Admin Telegram Configuration ---
# --- Admin Telegram User ID ---
ADMIN_CHAT_ID = 982922116
SUPPORT_USERNAME = "@CHUNKLA47"
SUPPORT_URL = "https://t.me/CHUNKLA47"
CHANNEL_URL = "https://t.me/MailPayEt"
WEBSITE_URL = "https://mailpayet.github.io/MailPayET/"

# --- User Language Storage ---
# Stores { user_id: "en" | "am" }
USER_LANG = {}

def get_lang(user_id: int) -> str:
    return USER_LANG.get(user_id, "en")

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

# =====================================================================
# DATABASE
# Uses Postgres when DATABASE_URL is set (recommended on Render, e.g. a free
# Neon database). Otherwise it falls back to a local SQLite file, which is fine
# on your own computer / a server with a disk, but is WIPED on Render's free plan.
# =====================================================================
DATABASE_URL = os.getenv("DATABASE_URL")
SQLITE_PATH = os.getenv("SQLITE_PATH", "mailpay.db")
USE_PG = bool(DATABASE_URL)

if USE_PG:
    try:
        import psycopg2
    except ImportError:
        raise ImportError("DATABASE_URL is set, but psycopg2 is missing. Add 'psycopg2-binary' to requirements.txt")
else:
    import sqlite3


def _connect():
    if USE_PG:
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(SQLITE_PATH, timeout=15)


def _run(sql, params=(), mode="exec"):
    """Runs one SQL statement. mode: 'exec' (no result), 'one' (dict or None), 'all' (list of dicts)."""
    if USE_PG:
        sql = sql.replace("?", "%s")
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        result = None
        if mode in ("one", "all") and cur.description is not None:
            cols = [d[0] for d in cur.description]
            if mode == "one":
                row = cur.fetchone()
                result = dict(zip(cols, row)) if row else None
            else:
                result = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.commit()
        return result
    finally:
        conn.close()


async def db(sql, params=(), mode="exec"):
    # runs in a worker thread so a slow database never freezes the bot
    return await asyncio.to_thread(_run, sql, params, mode)


def init_db():
    pk = "SERIAL PRIMARY KEY" if USE_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    _run("""CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        lang TEXT DEFAULT 'en',
        first_seen BIGINT,
        last_seen BIGINT)""")
    _run(f"""CREATE TABLE IF NOT EXISTS submissions (
        id {pk},
        user_id BIGINT NOT NULL,
        photo_id TEXT,
        status TEXT DEFAULT 'pending',
        payout_status TEXT DEFAULT 'none',
        method TEXT,
        payment_details TEXT,
        amount INTEGER DEFAULT {PAY_PER_ACCOUNT},
        created_at BIGINT,
        decided_at BIGINT,
        paid_at BIGINT)""")
    _run("CREATE INDEX IF NOT EXISTS idx_sub_status ON submissions (status, payout_status)")

    # Shared tables used by both the Telegram bot and the Mini App.
    if USE_PG:
        _run("""CREATE TABLE IF NOT EXISTS public.mp_wallet_accounts (
            user_id BIGINT PRIMARY KEY,
            welcome_bonus_granted BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        _run("""CREATE TABLE IF NOT EXISTS public.mp_wallet_ledger (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, amount INTEGER NOT NULL,
            entry_type TEXT NOT NULL, reference TEXT NOT NULL UNIQUE,
            available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        _run("""CREATE TABLE IF NOT EXISTS public.mp_tasks (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'requested'
              CHECK (status IN ('requested','assigned','submitted','approved','rejected','expired')),
            instructions TEXT, reward_etb INTEGER NOT NULL DEFAULT 0 CHECK (reward_etb >= 0),
            assigned_at TIMESTAMPTZ, expires_at TIMESTAMPTZ,
            evidence_text TEXT, evidence_image_data TEXT,
            requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), submitted_at TIMESTAMPTZ, decided_at TIMESTAMPTZ,
            telegram_username TEXT, telegram_first_name TEXT, telegram_last_name TEXT,
            request_source TEXT NOT NULL DEFAULT 'miniapp')""")
        _run("""CREATE TABLE IF NOT EXISTS public.mp_withdrawals (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
            amount INTEGER NOT NULL CHECK (amount >= 50), method TEXT NOT NULL, payment_details TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','paid','rejected')),
            requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), decided_at TIMESTAMPTZ, admin_note TEXT,
            receipt_image_data TEXT, payment_account_name TEXT, payment_account_number TEXT,
            custom_payment_method TEXT, request_source TEXT NOT NULL DEFAULT 'miniapp')""")
        _run("ALTER TABLE public.mp_tasks ADD COLUMN IF NOT EXISTS telegram_username TEXT")
        _run("ALTER TABLE public.mp_tasks ADD COLUMN IF NOT EXISTS telegram_first_name TEXT")
        _run("ALTER TABLE public.mp_tasks ADD COLUMN IF NOT EXISTS telegram_last_name TEXT")
        _run("ALTER TABLE public.mp_tasks ADD COLUMN IF NOT EXISTS request_source TEXT NOT NULL DEFAULT 'miniapp'")
        _run("ALTER TABLE public.mp_withdrawals ADD COLUMN IF NOT EXISTS request_source TEXT NOT NULL DEFAULT 'miniapp'")
        _run("CREATE INDEX IF NOT EXISTS mp_tasks_user_idx ON public.mp_tasks(user_id, requested_at DESC)")
        _run("CREATE INDEX IF NOT EXISTS mp_tasks_status_idx ON public.mp_tasks(status, requested_at)")
        _run("CREATE INDEX IF NOT EXISTS mp_ledger_user_idx ON public.mp_wallet_ledger(user_id, available_at)")
        _run("CREATE INDEX IF NOT EXISTS mp_withdrawals_user_idx ON public.mp_withdrawals(user_id, requested_at DESC)")


# ---- Shared MailPay ET task and wallet services ----
async def ensure_shared_wallet(user_id):
    if not USE_PG:
        return
    await db("""
        WITH new_account AS (
            INSERT INTO public.mp_wallet_accounts (user_id)
            VALUES (?) ON CONFLICT (user_id) DO NOTHING RETURNING user_id
        ),
        new_bonus AS (
            INSERT INTO public.mp_wallet_ledger (user_id, amount, entry_type, reference, available_at)
            SELECT user_id, 10, 'welcome_bonus', 'welcome:' || user_id::text, NOW()
            FROM new_account ON CONFLICT (reference) DO NOTHING RETURNING user_id
        )
        UPDATE public.mp_wallet_accounts SET welcome_bonus_granted = TRUE
        WHERE user_id IN (SELECT user_id FROM new_bonus)
    """, (user_id,))

async def get_shared_wallet(user_id):
    if not USE_PG:
        raise RuntimeError("The shared wallet requires the connected MailPay ET database.")
    await ensure_shared_wallet(user_id)
    row = await db("""
        SELECT
          COALESCE((SELECT SUM(amount) FROM public.mp_wallet_ledger WHERE user_id = ? AND available_at <= NOW()), 0)::INTEGER AS total_earned,
          COALESCE((SELECT SUM(amount) FROM public.mp_wallet_ledger WHERE user_id = ? AND available_at > NOW()), 0)::INTEGER AS pending_rewards,
          COALESCE((SELECT SUM(amount) FROM public.mp_withdrawals WHERE user_id = ? AND status = 'pending'), 0)::INTEGER AS pending_withdrawals,
          GREATEST(0,
            COALESCE((SELECT SUM(amount) FROM public.mp_wallet_ledger WHERE user_id = ? AND available_at <= NOW()), 0)
            - COALESCE((SELECT SUM(amount) FROM public.mp_withdrawals WHERE user_id = ? AND status IN ('pending','paid')), 0)
          )::INTEGER AS available
    """, (user_id, user_id, user_id, user_id, user_id), "one")
    return row or {"available": 0, "total_earned": 0, "pending_rewards": 0, "pending_withdrawals": 0}

def _create_shared_task_request(user):
    if not USE_PG:
        raise RuntimeError("The shared task system requires the connected MailPay ET database.")
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SELECT pg_advisory_xact_lock(%s::bigint)", (int(user.id),))
        cur.execute("""UPDATE public.mp_tasks SET status='expired'
                       WHERE user_id=%s AND status='assigned' AND expires_at IS NOT NULL AND expires_at<=NOW()""", (int(user.id),))
        cur.execute("""SELECT id,status FROM public.mp_tasks
                       WHERE user_id=%s AND status IN ('requested','assigned','submitted')
                       ORDER BY requested_at DESC LIMIT 1""", (int(user.id),))
        active = cur.fetchone()
        if active:
            conn.commit()
            return {"created": False, "id": active[0], "status": active[1]}
        cur.execute("""INSERT INTO public.mp_tasks
                       (user_id,telegram_username,telegram_first_name,telegram_last_name,request_source)
                       VALUES (%s,%s,%s,%s,'telegram_bot') RETURNING id,status""",
                    (int(user.id), user.username, user.first_name, user.last_name))
        row = cur.fetchone()
        conn.commit()
        return {"created": True, "id": row[0], "status": row[1]}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

async def list_shared_tasks(user_id, limit=8):
    if not USE_PG:
        raise RuntimeError("The shared task system requires the connected MailPay ET database.")
    await db("""UPDATE public.mp_tasks SET status='expired'
                WHERE user_id=? AND status='assigned' AND expires_at IS NOT NULL AND expires_at<=NOW()""", (user_id,))
    return await db("""SELECT id,status,instructions,reward_etb,
                        to_char(requested_at AT TIME ZONE 'Africa/Addis_Ababa','YYYY-MM-DD HH24:MI') AS requested_local,
                        to_char(expires_at AT TIME ZONE 'Africa/Addis_Ababa','YYYY-MM-DD HH24:MI') AS expires_local
                     FROM public.mp_tasks WHERE user_id=? ORDER BY requested_at DESC LIMIT ?""", (user_id,limit), "all")

def _create_shared_withdrawal(user_id, amount, method, account_name, account_number):
    if not USE_PG:
        raise RuntimeError("The shared wallet requires the connected MailPay ET database.")
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("INSERT INTO public.mp_wallet_accounts(user_id) VALUES(%s) ON CONFLICT(user_id) DO NOTHING", (user_id,))
        cur.execute("SELECT user_id FROM public.mp_wallet_accounts WHERE user_id=%s FOR UPDATE", (user_id,))
        cur.execute("""SELECT COALESCE((SELECT SUM(amount) FROM public.mp_wallet_ledger WHERE user_id=%s AND available_at<=NOW()),0)
                       - COALESCE((SELECT SUM(amount) FROM public.mp_withdrawals WHERE user_id=%s AND status IN ('pending','paid')),0)""", (user_id,user_id))
        available = int(cur.fetchone()[0] or 0)
        if available < 50:
            conn.rollback()
            return {"error":"Your available balance is below the 50 ETB minimum."}
        if amount > available:
            conn.rollback()
            return {"error":"The withdrawal amount exceeds your available balance."}
        details = f"Account name: {account_name}\nAccount number: {account_number}"
        cur.execute("""INSERT INTO public.mp_withdrawals
                       (user_id,amount,method,payment_details,payment_account_name,payment_account_number,request_source)
                       VALUES(%s,%s,%s,%s,%s,%s,'telegram_bot') RETURNING id,amount,method,status""",
                    (user_id,amount,method,details,account_name,account_number))
        row = cur.fetchone()
        conn.commit()
        return {"id":row[0],"amount":row[1],"method":row[2],"status":row[3]}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- small helpers used by the admin panel ---
def fmt_time(ts):
    if not ts:
        return "-"
    return datetime.fromtimestamp(int(ts), tz=EAT).strftime("%d %b %H:%M")


def ago(ts):
    seconds = max(0, int(time.time()) - int(ts or 0))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def short(text, n=18):
    text = str(text or "")
    return text if len(text) <= n else text[: n - 1] + "…"


def display_name(row):
    if row.get("full_name"):
        return row["full_name"]
    if row.get("username"):
        return "@" + row["username"]
    return str(row.get("user_id"))


def user_link(user_id, name):
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


def username_html(row):
    return f"@{html.escape(row['username'])}" if row.get("username") else "no username"


async def get_submission(sub_id):
    return await db(
        "SELECT s.*, u.username, u.full_name, u.lang FROM submissions s "
        "LEFT JOIN users u ON u.user_id = s.user_id WHERE s.id = ?",
        (sub_id,), "one",
    )


async def set_lang(user_id, lang):
    USER_LANG[user_id] = lang
    try:
        await db("UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id))
    except Exception as e:
        print(f"Failed to save language: {e}")


_SEEN = {}


async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Runs before every other handler: remembers who has used the bot."""
    user = update.effective_user
    if not user or user.is_bot:
        return
    now = int(time.time())
    name = user.full_name or ""
    cached = _SEEN.get(user.id)
    if cached and cached[0] == user.username and cached[1] == name and now - cached[2] < 600:
        return
    try:
        await db(
            "INSERT INTO users (user_id, username, full_name, lang, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (user_id) DO UPDATE SET username = excluded.username, "
            "full_name = excluded.full_name, last_seen = excluded.last_seen",
            (user.id, user.username, name, get_lang(user.id), now, now),
        )
        _SEEN[user.id] = (user.username, name, now)
        if USE_PG:
            try:
                await ensure_shared_wallet(user.id)
            except Exception as wallet_error:
                print(f"Failed to initialize shared wallet for {user.id}: {wallet_error}")
    except Exception as e:
        print(f"Failed to track user: {e}")


# --- Multilingual Text Content ---
# NOTE: messages sent with parse_mode="Markdown" use *single stars* for bold.
TEXTS = {
    "en": {
        "welcome": "👋 Welcome to MailPay 🇪🇹\n\nLooking for a simple way to earn?\n\nWe provide the information you need to participate in our Gmail account service.\n\nChoose an option below 👇",
        "how_it_works": (
            "📚 HOW IT WORKS\n\n"
            "1️⃣ Tap '➕ Get Gmail Task' to contact our Admin for your account details.\n"
            "2️⃣ Create the Gmail account using the exact details given by the Admin.\n"
            "3️⃣ Tap '📸 Submit Screenshot' to upload proof of the created account.\n"
            "4️⃣ Once verified by Admin, you earn 10 ETB per verified account!\n"
            "5️⃣ Enter your payment details (Telebirr, M-Pesa, or CBE) to receive your payout and receipt.\n\n"
            "📱 HOW TO REMOVE THE ACCOUNT FROM YOUR DEVICE:\n"
            "After submitting, you can safely remove the account:\n"
            "1. Go to Settings\n"
            "2. Scroll down and tap Accounts and Backup\n"
            "3. Click Manage Accounts\n"
            "4. Select the account to remove\n"
            "5. Click Remove Account below the selected account\n\n"
            "💰 Payment: 10 ETB × number of verified accounts."
        ),
        "payment_info": (
            "💰 PAYMENT INFO\n\n"
            "You will receive:\n"
            "10 ETB 💵 for each Gmail account successfully verified.\n\n"
            "📊 Example:\n"
            "• 1 verified account = 10 ETB\n"
            "• 5 verified accounts = 50 ETB\n"
            "• 10 verified accounts = 100 ETB\n\n"
            "⏳ VERIFICATION\n"
            "Verification and payout receipts are processed within 3 days after submission.\n\n"
            "🇪🇹 AVAILABLE PAYMENT METHODS\n"
            "• Telebirr\n"
            "• M-Pesa (Safaricom users)\n"
            "• Commercial Bank of Ethiopia (CBE)"
        ),
        "requirements": (
            "📋 REQUIREMENTS & PAYMENT RULES\n\n"
            "• Follow the exact credentials given by the Admin.\n"
            "• Make sure your payment details are completely accurate before submitting.\n"
            "• MailPay is not responsible for transfers sent to incorrect account numbers provided by users."
        ),
        "task_info": (
            "📌 *HOW TO GET YOUR GMAIL TASK*\n\n"
            "1. Click the button below to contact Admin directly.\n"
            "2. Admin will provide you with the target First Name, Last Name, Email, Year of Birth, and Password.\n"
            "3. Create the account using those exact details.\n"
            "4. Once created, return here and tap '📸 Submit Screenshot' to submit your proof!"
        ),
        "remove_guide": (
            "📱 *HOW TO REMOVE AN ACCOUNT FROM YOUR DEVICE*\n\n"
            "1. Go to Settings\n"
            "2. Scroll down and tap Accounts and Backup\n"
            "3. Click Manage Accounts\n"
            "4. Select the account to remove\n"
            "5. Click Remove Account below the selected account"
        ),
        "prompt_screenshot": "📸 *SUBMIT ACCOUNT SCREENSHOT*\n\nPlease upload a photo/screenshot showing the Gmail account you created.\n\n(Send /cancel to go back.)",
        "screenshot_wrong_input": "⚠️ Please send a *photo/screenshot* of the Gmail account you created.\n\nSend /cancel to go back to the menu.",
        "screenshot_received": "✅ *Screenshot received successfully!*\n\nYour submission is now under review by the Admin. You will receive a notification here once verified.",
        "approved_msg": "🎉 *ACCOUNT APPROVED!*\n\nYou have successfully created the account based on the provided details! You will receive *10 ETB* within 3 days.\n\n💳 Please select your payment method below:",
        "rejected_msg": "❌ *SUBMISSION REJECTED*\n\nYou haven't created the account based on the provided information.\n\nPlease contact Admin if you need help or try creating the account correctly.",
        "prompt_payment": "📱 *ENTER YOUR {method} DETAILS*\n\nPlease reply to this message with your phone number or account number for *{method}*:",
        "payment_received": "🎉 *Payment details submitted!*\n\nYour payment is being processed. A payment receipt will be sent directly to this chat once the transfer is complete.\n\nThank you for participating with MailPay 🇪🇹!",
        "receipt_delivered": "🎉 *GREAT NEWS! PAYMENT SENT!*\n\nYour payment of *10 ETB* has been transferred.\n\n📄 Attached above is your official payment transfer receipt.\n\nThank you for working with MailPay 🇪🇹!",
        "cancelled": "✅ Cancelled. Back to the main menu 👇",
        "contact_prompt": "✉️ *CONTACT ADMIN*\n\nType your message below and send it (text, photo or voice note).\nThe Admin will reply to you right here in this chat.",
        "contact_ack": "✅ *Message received!*\n\nThank you for contacting MailPay. The Admin has been notified and will reply to you here as soon as possible.",
        "contact_sent_short": "✅ Sent to Admin.",
        "payment_sent": "🎉 *PAYMENT SENT!*\n\nYour payment of *10 ETB* has been transferred to your account.\n\nThank you for working with MailPay 🇪🇹!",
        "payment_unavailable": "⚠️ This payment request is no longer available.",
        "contact_failed": "⚠️ Sorry, your message could not be delivered. Please try again later or contact {support} directly.",
        "task_request_sent": "✅ *Request sent!*\n\nThe Admin has been notified and will send your account details (name, email, year of birth, password) here in this chat shortly.\n\nOnce you have created the account, tap '📸 Submit Screenshot'.",
        "task_already": "⏳ You already sent a request a moment ago. Please wait for the Admin to reply.",
        "admin_reply_header": "💬 *Message from Admin* 👇",
        "support_text": "👤 CONTACT SUPPORT\n\nNeed help? Tap the button below to message the Admin right here in the bot.\n\nChannel: {channel}",
        "btn_reply_admin": "💬 Reply to Admin",
        "btn_contact_support": "💬 Message the Admin",
        "btn_get_task": "➕ Get Gmail Task",
        "btn_submit_ss": "📸 Submit Screenshot",
        "btn_how": "📚 How It Works",
        "btn_pay": "💰 Payment Info",
        "btn_req": "📋 Requirements & Rules",
        "btn_faq": "❓ FAQ",
        "btn_channel": "📢 Official Channel",
        "btn_web": "🌐 Visit Website",
        "btn_support": "👤 Contact Support",
        "btn_lang": "🌐 Switch Language / ቋንቋ ቀይር",
        "btn_back": "🔙 Back to Main Menu",
        "btn_contact_admin": "💬 Contact Admin to Get Account",
    },
    "am": {
        "welcome": "👋 እንኳን ወደ MailPay 🇪🇹 በደህና መጡ!\n\nቀላል ገቢ ማግኘት ይፈልጋሉ?\n\nበእኛ የጂሜይል (Gmail) አካውንት አገልግሎት ለመሳተፍ የሚያስፈልጉትን መረጃዎች እናቀርባለን።\n\nከታች አንዱን አማራጭ ይምረጡ 👇",
        "how_it_works": (
            "📚 እንዴት እንደሚሰራ\n\n"
            "1️⃣ የአካውንት መረጃ ከAdmin ለማግኘት '➕ Get Gmail Task' የሚለውን ይጫኑ።\n"
            "2️⃣ Admin የሰጠዎትን ትክክለኛ መረጃ በመጠቀም የጂሜይል (Gmail) አካውንት ይክፈቱ።\n"
            "3️⃣ አካውንቱን መክፈትዎን ለማረጋገጥ '📸 Submit Screenshot' በማለት ፎቶ ይላኩ።\n"
            "4️⃣ በAdmin ከተረጋገጠ በኋላ ለእያንዳንዱ ከተረጋገጠ አካውንት 10 ብር ያገኛሉ!\n"
            "5️⃣ ክፍያዎን እና ደረሰኝዎን ለመቀበል የክፍያ መረጃዎን (Telebirr, M-Pesa, ወይም CBE) ያስገቡ።\n\n"
            "📱 አካውንቱን ከስልክዎ ላይ እንዴት ማጥፋት እንደሚችሉ:\n"
            "አካውንቱን ከላኩ በኋላ በቀላሉ ከስልክዎ ማጥፋት ይችላሉ:\n"
            "1. ወደ Settings ይግቡ\n"
            "2. ወደ ታች ወርደው Accounts and Backup የሚለውን ይጫኑ\n"
            "3. Manage Accounts የሚለውን ይጫኑ\n"
            "4. ማጥፋት የሚፈልጉትን አካውንት ይምረጡ\n"
            "5. ከስሩ Remove Account የሚለውን ይጫኑ\n\n"
            "💰 ክፍያ: 10 ETB × ከተረጋገጡ አካውንቶች ብዛት።"
        ),
        "payment_info": (
            "💰 የክፍያ መረጃ\n\n"
            "የሚያገኙት ክፍያ:\n"
            "በተሳካ ሁኔታ ለተረጋገጠ ለእያንዳንዱ የጂሜይል አካውንት 10 ETB 💵 ያገኛሉ።\n\n"
            "📊 ምሳሌ:\n"
            "• 1 የተረጋገጠ አካውንት = 10 ETB\n"
            "• 5 የተረጋገጡ አካውንቶች = 50 ETB\n"
            "• 10 የተረጋገጡ አካውንቶች = 100 ETB\n\n"
            "⏳ ማረጋገጫ\n"
            "ማረጋገጫ እና የክፍያ ደረሰኝ ከተላከበት ቀን ጀምሮ በ3 ቀናት ውስጥ ይከናወናል።\n\n"
            "🇪🇹 የሚሰሩ የክፍያ አማራጮች\n"
            "• ቴሌብር (Telebirr)\n"
            "• M-Pesa (ለSafaricom ተጠቃሚዎች)\n"
            "• የኢትዮጵያ ንግድ ባንክ (CBE)"
        ),
        "requirements": (
            "📋 መስፈርቶች እና የክፍያ ደንቦች\n\n"
            "• በAdmin የተሰጠዎትን ትክክለኛ መረጃ ብቻ ይጠቀሙ።\n"
            "• ከመርካትዎ በፊት የክፍያ መረጃዎ ትክክል መሆኑን ያረጋግጡ።\n"
            "• ተጠቃሚዎች በተሳሳተ ቁጥር ለላኩት ክፍያ MailPay ሀላፊነት አይወስድም።"
        ),
        "task_info": (
            "📌 *የጂሜይል ስራ እንዴት እንደሚገኝ*\n\n"
            "1. Adminን በቀጥታ ለማግኘት ከታች ያለውን ቁልፍ ይጫኑ።\n"
            "2. Admin የመጀመሪያ ስም፣ የቤተሰብ ስም፣ ኢሜይል፣ የልደት ዘመን እና የይለፍ ቃል ይሰጥዎታል።\n"
            "3. እነዚያኑ ትክክለኛ መረጃዎች በመጠቀም አካውንቱን ይክፈቱ።\n"
            "4. እንደጨረሱ ወደዚህ ተመልሰው '📸 Submit Screenshot' በማለት ማረጋገጫ ይላኩ!"
        ),
        "remove_guide": (
            "📱 *አካውንት ከስልክ ላይ እንዴት እንደሚያጠፉ*\n\n"
            "1. ወደ Settings ይግቡ\n"
            "2. Accounts and Backup የሚለውን ይጫኑ\n"
            "3. Manage Accounts የሚለውን ይጫኑ\n"
            "4. ማጥፋት የሚፈልጉትን አካውንት ይምረጡ\n"
            "5. Remove Account የሚለውን ይጫኑ"
        ),
        "prompt_screenshot": "📸 *የአካውንት ስክሪንሾት (Screenshot) ይላኩ*\n\nእባክዎ የከፈቱትን የጂሜይል አካውንት የሚያሳይ ፎቶ/ስክሪንሾት እዚህ ይላኩ።\n\n(ለመመለስ /cancel ይላኩ።)",
        "screenshot_wrong_input": "⚠️ እባክዎ የከፈቱትን የጂሜይል አካውንት የሚያሳይ *ፎቶ/ስክሪንሾት* ይላኩ።\n\nወደ ዋና ማውጫ ለመመለስ /cancel ይላኩ።",
        "screenshot_received": "✅ *ስክሪንሾቱ በተሳካ ሁኔታ ደርሷል!*\n\nመረጃዎ አሁን በAdmin እየተገመገመ ነው። ሲረጋገጥ እዚህ መልእክት ይደርስዎታል።",
        "approved_msg": "🎉 *አካውንቱ ተፀድቋል!*\n\nበተሰጠው መረጃ መሰረት አካውንቱን በተሳካ ሁኔታ ፈጥረዋል! በ3 ቀናት ውስጥ *10 ETB* ይደርስዎታል።\n\n💳 እባክዎ ከታች የክፍያ የተቀባይነት አማራጭዎን ይምረጡ:",
        "rejected_msg": "❌ *አካውንቱ አልተቀበለም*\n\nበተሰጠው መረጃ መሰረት አካውንቱን አልፈጠሩም።\n\nእባክዎ እርዳታ ካስፈለገዎት Adminን ያናግሩ ወይም እንደገና በትክክል ይክፈቱ።",
        "prompt_payment": "📱 *የ{method} መረጃዎን ያስገቡ*\n\nእባክዎ ለ*{method}* የሚሆን የስልክ ቁጥር ወይም የባንክ ሂሳብ ቁጥር ይላኩ:",
        "payment_received": "🎉 *የክፍያ መረጃዎ ደርሷል!*\n\nክፍያዎ በመሰራት ላይ ነው። ክፍያው እንደተጠናቀቀ የክፍያ ደረሰኝ በቀጥታ እዚህ ይላክልዎታል።\n\nከ MailPay 🇪🇹 ጋር ስለሰሩ እናመሰግናለን!",
        "receipt_delivered": "🎉 *መልካም ዜና! ክፍያዎ ተላከ!*\n\nየ *10 ETB* ክፍያዎ ተላክል።\n\n📄 ይፋዊ የክፍያ ደረሰኝዎ ከላይ ተያይዟል።\n\nከ MailPay 🇪🇹 ጋር ስለሰሩ እናመሰግናለን!",
        "cancelled": "✅ ተሰርዟል። ወደ ዋና ማውጫ ተመልሰዋል 👇",
        "contact_prompt": "✉️ *Adminን ያናግሩ*\n\nመልእክትዎን (ጽሑፍ፣ ፎቶ ወይም የድምጽ መልእክት) ከታች ይጻፉና ይላኩ።\nAdmin እዚሁ ቻት ውስጥ መልስ ይሰጥዎታል።",
        "contact_ack": "✅ *መልእክትዎ ደርሷል!*\n\nMailPayን ስላናገሩ እናመሰግናለን። Admin ተነግሮታል፤ በተቻለ ፍጥነት እዚሁ መልስ ይሰጥዎታል።",
        "contact_sent_short": "✅ ለAdmin ተልኳል።",
        "payment_sent": "🎉 *ክፍያዎ ተላከ!*\n\nየ *10 ETB* ክፍያዎ ወደ ሂሳብዎ ተልኳል።\n\nከ MailPay 🇪🇹 ጋር ስለሰሩ እናመሰግናለን!",
        "payment_unavailable": "⚠️ ይህ የክፍያ ጥያቄ አሁን አይገኝም።",
        "contact_failed": "⚠️ ይቅርታ፣ መልእክትዎ አልደረሰም። እባክዎ ቆይተው እንደገና ይሞክሩ ወይም {support}ን በቀጥታ ያናግሩ።",
        "task_request_sent": "✅ *ጥያቄዎ ተልኳል!*\n\nAdmin ተነግሮታል፤ የአካውንት መረጃዎን (ስም፣ ኢሜይል፣ የልደት ዘመን፣ የይለፍ ቃል) በቅርቡ እዚሁ ቻት ይልክልዎታል።\n\nአካውንቱን ከከፈቱ በኋላ '📸 Submit Screenshot' ይጫኑ።",
        "task_already": "⏳ ጥያቄ ልከዋል። እባክዎ Admin እስኪመልስ ይጠብቁ።",
        "admin_reply_header": "💬 *ከAdmin የመጣ መልእክት* 👇",
        "support_text": "👤 እገዛ ለማግኘት\n\nእርዳታ ይፈልጋሉ? ከታች ያለውን ቁልፍ ተጭነው Adminን እዚሁ ቦት ውስጥ ያናግሩ።\n\nቻናል: {channel}",
        "btn_reply_admin": "💬 ለAdmin መልስ ስጥ",
        "btn_contact_support": "💬 Adminን ያናግሩ",
        "btn_get_task": "➕ Get Gmail Task / ስራ አግኝ",
        "btn_submit_ss": "📸 Submit Screenshot / ስክሪንሾት ላክ",
        "btn_how": "📚 How It Works / እንዴት እንደሚሰራ",
        "btn_pay": "💰 Payment Info / የክፍያ መረጃ",
        "btn_req": "📋 Requirements / ደንቦች",
        "btn_faq": "❓ FAQ / ጥያቄዎች",
        "btn_channel": "📢 Official Channel / ቻናል",
        "btn_web": "🌐 Visit Website / ዌብሳይት",
        "btn_support": "👤 Contact Support / እገዛ",
        "btn_lang": "🌐 Switch Language / ቋንቋ ቀይር",
        "btn_back": "🔙 Back to Main Menu / ተመለስ",
        "btn_contact_admin": "💬 Contact Admin / Admin ያናግሩ",
    }
}

FAQ_ANSWERS = {
    "en": {
        "faq_earn": "💰 HOW MUCH DO I EARN?\nYou receive 10 ETB for each verified Gmail account.",
        "faq_paid": "⏱ WHEN WILL I GET PAID?\nVerification and payout occur within 3 days of submission.",
        "faq_submit": "📨 HOW DO I SUBMIT AN ACCOUNT?\nContact Admin for details, then use '📸 Submit Screenshot' to submit proof.",
        "faq_remove": "📱 HOW TO REMOVE AN ACCOUNT FROM YOUR DEVICE:\n1. Go to Settings\n2. Scroll down and tap Accounts and Backup\n3. Click Manage Accounts\n4. Select the account to remove\n5. Click Remove Account below the selected account.",
        "faq_methods": "💳 WHICH PAYMENT METHODS ARE AVAILABLE?\nTelebirr, M-Pesa, or Commercial Bank of Ethiopia (CBE).",
    },
    "am": {
        "faq_earn": "💰 ምን ያህል አገኛለሁ?\nለእያንዳንዱ ከተረጋገጠ የጂሜይል አካውንት 10 ETB ያገኛሉ።",
        "faq_paid": "⏱ መቼ ነው ክፍያ የምቀበለው?\nማረጋገጫ እና ክፍያ በ3 ቀናት ውስጥ ይከናወናል።",
        "faq_submit": "📨 አካውንት እንዴት ነው የምልከው?\nመረጃ ከAdmin የተቀበሉ፣ ከዚያ '📸 Submit Screenshot' በማለት ይላኩ።",
        "faq_remove": "📱 አካውንት ከስልክ ላይ እንዴት ይወጣል:\n1. ወደ Settings ይግቡ\n2. Accounts and Backup የሚለውን ይጫኑ\n3. Manage Accounts የሚለውን ይጫኑ\n4. ማጥፋት የሚፈልጉትን አካውንት ይምረጡ\n5. Remove Account የሚለውን ይጫኑ",
        "faq_methods": "💳 የትኞቹ የክፍያ አማራጮች አሉ?\nቴሌብር (Telebirr)፣ M-Pesa ወይም የኢትዮጵያ ንግድ ባንክ (CBE)።",
    }
}

# --- Keyboards ---
def main_menu(lang="en"):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t["btn_get_task"], callback_data="get_task")],
        [
            InlineKeyboardButton("💰 My balance" if lang == "en" else "💰 ቀሪ ሂሳቤ", callback_data="wallet_view"),
            InlineKeyboardButton("📋 My tasks" if lang == "en" else "📋 ተግባሮቼ", callback_data="task_history"),
        ],
        [
            InlineKeyboardButton(t["btn_how"], callback_data="how_it_works"),
            InlineKeyboardButton(t["btn_pay"], callback_data="payment_info"),
        ],
        [
            InlineKeyboardButton(t["btn_req"], callback_data="requirements"),
            InlineKeyboardButton(t["btn_faq"], callback_data="faq"),
        ],
        [
            InlineKeyboardButton(t["btn_channel"], url=CHANNEL_URL),
            InlineKeyboardButton(t["btn_web"], url=WEBSITE_URL),
        ],
        [InlineKeyboardButton("ⓕ Facebook", url="https://web.facebook.com/share/p/1MN18PyRa2/")],
        [InlineKeyboardButton("📸 Instagram", url="https://www.instagram.com/reel/DeFXtuQlZjo/?utm_source=ig_web_copy_link&stkn=MzRlODBiNWFlZA==")],
        [InlineKeyboardButton("🟢 WhatsApp", url="https://wa.me/message/4AGHRHT64MI4K1")],
        [InlineKeyboardButton("♪ TikTok", url="https://vm.tiktok.com/ZS9Aveo3qnhSJ-gMcyh/")],
        [InlineKeyboardButton(t["btn_lang"], callback_data="toggle_language")],
        [InlineKeyboardButton(t["btn_support"], callback_data="support")],
    ])

def back_main(lang="en"):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t["btn_back"], callback_data="main_menu")]
    ])

def faq_heading(lang="en"):
    if lang == "en":
        return "❓ FREQUENTLY ASKED QUESTIONS\n\nChoose a question below 👇"
    return "❓ ተደጋግመው የሚጠየቁ ጥያቄዎች\n\nከታች ይምረጡ 👇"

def faq_menu(lang="en"):
    is_am = lang == "am"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 How much do I earn?" if not is_am else "💰 ምን ያህል አገኛለሁ?", callback_data="faq_earn")],
        [InlineKeyboardButton("⏱ When will I get paid?" if not is_am else "⏱ መቼ ነው ክፍያ የምቀበለው?", callback_data="faq_paid")],
        [InlineKeyboardButton("📨 How do I submit an account?" if not is_am else "📨 አካውንት እንዴት ልላክ?", callback_data="faq_submit")],
        [InlineKeyboardButton("📱 How to remove account from device?" if not is_am else "📱 አካውንት ከስልክ እንዴት ላጥፋ?", callback_data="faq_remove")],
        [InlineKeyboardButton("💳 Available payment methods?" if not is_am else "💳 የክፍያ አማራጮች?", callback_data="faq_methods")],
        [InlineKeyboardButton(TEXTS[lang]["btn_back"], callback_data="main_menu")],
    ])

def faq_back(lang="en"):
    is_am = lang == "am"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to FAQ" if not is_am else "🔙 ወደ ጥያቄዎች ተመለስ", callback_data="faq")],
        [InlineKeyboardButton("🏠 Main Menu" if not is_am else "🏠 ዋና ማውጫ", callback_data="main_menu")],
    ])

def task_keyboard(lang, user_id=None):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Request a task" if lang == "en" else "📝 ተግባር ይጠይቁ", callback_data="request_task")],
        [InlineKeyboardButton(t["btn_submit_ss"], callback_data="start_submit_screenshot")],
        [InlineKeyboardButton("📋 My tasks" if lang == "en" else "📋 ተግባሮቼ", callback_data="task_history")],
        [InlineKeyboardButton(t["btn_back"], callback_data="main_menu")],
    ])

def wallet_keyboard(lang="en"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Withdraw" if lang == "en" else "💸 ገንዘብ አውጣ", callback_data="wallet_withdraw")],
        [InlineKeyboardButton("📑 My withdrawals" if lang == "en" else "📑 የማውጣት ታሪክ", callback_data="withdrawal_history")],
        [InlineKeyboardButton("📋 My tasks" if lang == "en" else "📋 ተግባሮቼ", callback_data="task_history")],
        [InlineKeyboardButton("🏠 Main menu" if lang == "en" else "🏠 ዋና ማውጫ", callback_data="main_menu")],
    ])

def task_history_keyboard(lang="en"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Request a task" if lang == "en" else "📝 ተግባር ይጠይቁ", callback_data="get_task")],
        [InlineKeyboardButton("💰 My balance" if lang == "en" else "💰 ቀሪ ሂሳቤ", callback_data="wallet_view")],
        [InlineKeyboardButton("🔄 Refresh tasks" if lang == "en" else "🔄 ተግባሮችን አድስ", callback_data="task_history_refresh")],
        [InlineKeyboardButton("🏠 Main menu" if lang == "en" else "🏠 ዋና ማውጫ", callback_data="main_menu")],
    ])

async def wallet_message(user_id, lang="en"):
    wallet = await get_shared_wallet(user_id)
    if lang == "am":
        return ("💰 የMAILPAY ET የኪስ ቦርሳ\n\n"
                f"የሚገኝ ሂሳብ: {wallet['available']} ETB\n"
                f"ጠቅላላ ገቢ: {wallet['total_earned']} ETB\n"
                f"በጊዜ ገደብ ላይ ያለ ሽልማት: {wallet['pending_rewards']} ETB\n"
                f"በሂደት ላይ ያለ የማውጣት ጥያቄ: {wallet['pending_withdrawals']} ETB\n\n"
                "አንድ ጊዜ ብቻ 10 ETB የእንኳን ደህና መጡ ቦነስ ይሰጣል። ይህ ሂሳብ በBot እና Mini App መካከል የጋራ ነው።\n"
                "ዝቅተኛ የማውጣት መጠን: 50 ETB")
    return ("💰 MAILPAY ET WALLET\n\n"
            f"Available balance: {wallet['available']} ETB\n"
            f"Total earned: {wallet['total_earned']} ETB\n"
            f"Pending rewards (72-hour hold): {wallet['pending_rewards']} ETB\n"
            f"Pending withdrawals: {wallet['pending_withdrawals']} ETB\n\n"
            "🎁 New customers receive a one-time 10 ETB welcome bonus. Your wallet is shared by the Bot and Mini App.\n"
            "Minimum withdrawal: 50 ETB")

async def task_history_message(user_id, lang="en"):
    items = await list_shared_tasks(user_id)
    title = "📋 YOUR MAILPAY ET TASKS" if lang == "en" else "📋 የMAILPAY ET ተግባሮችዎ"
    if not items:
        return title + ("\n\nYou have no task requests yet." if lang == "en" else "\n\nእስካሁን የተግባር ጥያቄ የለዎትም።")
    lines = [title]
    for item in items:
        line = f"\n\n#{item['id']} · {str(item['status']).upper()} · Requested {item.get('requested_local') or 'recently'}"
        if item.get("instructions"):
            line += f"\nInstructions: {item['instructions'][:700]}"
            if item.get("expires_local") and item["status"] == "assigned":
                line += f"\nDeadline (EAT): {item['expires_local']}"
            line += f"\nReward: {item.get('reward_etb', 0)} ETB"
        lines.append(line)
    return "\n".join(lines)

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    try:
        await update.message.reply_text(await wallet_message(update.effective_user.id, lang), reply_markup=wallet_keyboard(lang))
    except Exception as e:
        print(f"Wallet lookup failed: {e}")
        await update.message.reply_text("The shared wallet is temporarily unavailable. Please try again later.")

async def cmd_my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    try:
        await update.message.reply_text(await task_history_message(update.effective_user.id, lang), reply_markup=task_history_keyboard(lang))
    except Exception as e:
        print(f"Task history lookup failed: {e}")
        await update.message.reply_text("Your shared task history is temporarily unavailable. Please try again later.")

async def withdrawal_history_message(user_id, lang="en"):
    if not USE_PG:
        raise RuntimeError("The shared withdrawal history requires the connected database.")
    rows = await db("""
        SELECT id, amount, method, status,
               to_char(requested_at AT TIME ZONE 'Africa/Addis_Ababa', 'YYYY-MM-DD HH24:MI') AS requested_local,
               admin_note
        FROM public.mp_withdrawals
        WHERE user_id = ?
        ORDER BY requested_at DESC LIMIT 10
    """, (user_id,), "all")
    title = "📑 YOUR WITHDRAWALS" if lang == "en" else "📑 የማውጣት ታሪክዎ"
    if not rows:
        return title + ("\n\nYou have no withdrawal requests yet." if lang == "en" else "\n\nእስካሁን የማውጣት ጥያቄ የለዎትም።")
    lines = [title]
    for row in rows:
        line = f"\n\nWithdrawal #{row['id']} · {row['amount']} ETB\nMethod: {row['method']}\nStatus: {str(row['status']).upper()}\nRequested: {row.get('requested_local') or 'recently'}"
        if row.get("admin_note"):
            line += f"\nAdmin note: {row['admin_note'][:250]}"
        lines.append(line)
    return "\n".join(lines)

async def cmd_withdrawal_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    try:
        await update.message.reply_text(await withdrawal_history_message(update.effective_user.id, lang), reply_markup=wallet_keyboard(lang))
    except Exception as e:
        print(f"Withdrawal history lookup failed: {e}")
        await update.message.reply_text("Your withdrawal history is temporarily unavailable. Please try again later.")


# ---- Shared wallet withdrawals ----
async def start_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        user = query.from_user
        target = query.message
    else:
        user = update.effective_user
        target = update.message
    lang = get_lang(user.id)
    if not USE_PG:
        await target.reply_text("The shared withdrawal system is temporarily unavailable. Please contact support.")
        return ConversationHandler.END
    try:
        wallet = await get_shared_wallet(user.id)
    except Exception as e:
        print(f"Could not start withdrawal: {e}")
        await target.reply_text("Could not load your shared balance. Please try again later.")
        return ConversationHandler.END
    if int(wallet["available"]) < 50:
        await target.reply_text(
            f"Your available balance is {wallet['available']} ETB. The minimum withdrawal is 50 ETB.",
            reply_markup=wallet_keyboard(lang),
        )
        return ConversationHandler.END
    for key in ("withdraw_amount", "withdraw_method", "withdraw_account_name"):
        context.user_data.pop(key, None)
    await target.reply_text(
        f"💸 WITHDRAW FROM MAILPAY ET\n\nAvailable balance: {wallet['available']} ETB\nMinimum withdrawal: 50 ETB\n\nEnter the whole ETB amount you want to withdraw, or /cancel to stop."
    )
    return WAITING_WITHDRAW_AMOUNT

async def receive_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = (update.message.text or "").strip()
    if not raw.isdigit():
        await update.message.reply_text("Please enter a whole number, such as 50.")
        return WAITING_WITHDRAW_AMOUNT
    amount = int(raw)
    try:
        wallet = await get_shared_wallet(update.effective_user.id)
    except Exception as e:
        print(f"Could not validate withdrawal amount: {e}")
        await update.message.reply_text("Could not check your balance. Please try again later.")
        return ConversationHandler.END
    if amount < 50:
        await update.message.reply_text("The minimum withdrawal is 50 ETB. Enter another amount.")
        return WAITING_WITHDRAW_AMOUNT
    if amount > int(wallet["available"]):
        await update.message.reply_text(f"Your available balance is {wallet['available']} ETB. Enter an amount no higher than your balance.")
        return WAITING_WITHDRAW_AMOUNT
    context.user_data["withdraw_amount"] = amount
    await update.message.reply_text(
        f"Choose a payout method for {amount} ETB:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Telebirr", callback_data="withdraw_method_Telebirr")],
            [InlineKeyboardButton("M-Pesa", callback_data="withdraw_method_M-Pesa")],
            [InlineKeyboardButton("Commercial Bank of Ethiopia (CBE)", callback_data="withdraw_method_CBE")],
        ]),
    )
    return WAITING_WITHDRAW_METHOD

async def receive_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.replace("withdraw_method_", "", 1)
    if method not in ("Telebirr", "M-Pesa", "CBE"):
        await query.message.reply_text("Please choose Telebirr, M-Pesa, or CBE.")
        return WAITING_WITHDRAW_METHOD
    context.user_data["withdraw_method"] = method
    await query.message.reply_text(f"Enter the full account name for {method}.")
    return WAITING_WITHDRAW_NAME

async def receive_withdraw_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if not name or len(name) > 160:
        await update.message.reply_text("Enter a valid full account name (up to 160 characters).")
        return WAITING_WITHDRAW_NAME
    context.user_data["withdraw_account_name"] = name
    await update.message.reply_text("Now enter the Telebirr, M-Pesa, or CBE account number.")
    return WAITING_WITHDRAW_ACCOUNT

async def receive_withdraw_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    account_number = (update.message.text or "").strip()
    if not account_number or len(account_number) > 100:
        await update.message.reply_text("Enter a valid account number (up to 100 characters).")
        return WAITING_WITHDRAW_ACCOUNT
    user = update.effective_user
    amount = int(context.user_data.get("withdraw_amount") or 0)
    method = context.user_data.get("withdraw_method")
    name = context.user_data.get("withdraw_account_name")
    if not amount or method not in ("Telebirr", "M-Pesa", "CBE") or not name:
        await update.message.reply_text("Your withdrawal details expired. Please start again from My balance.")
        return ConversationHandler.END
    try:
        result = await asyncio.to_thread(_create_shared_withdrawal, user.id, amount, method, name, account_number)
        if result.get("error"):
            await update.message.reply_text(result["error"], reply_markup=wallet_keyboard(get_lang(user.id)))
            return ConversationHandler.END
    except Exception as e:
        print(f"Shared withdrawal request failed: {e}")
        await update.message.reply_text("Could not save your withdrawal request. Please try again later.")
        return ConversationHandler.END

    for key in ("withdraw_amount", "withdraw_method", "withdraw_account_name"):
        context.user_data.pop(key, None)
    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(f"💸 NEW SHARED WITHDRAWAL #{result['id']}\n\n"
                      f"Customer: {user.full_name} (@{user.username or 'no username'})\n"
                      f"Telegram ID: {user.id}\nAmount: {result['amount']} ETB\nMethod: {method}\n"
                      f"Account name: {name}\nAccount number: {account_number}\n\n"
                      "Review it in the unified MailPay ET admin panel."),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Open unified admin panel", web_app=WebAppInfo(url="https://mailpay-et-miniapp.onrender.com/admin"))
                ]]),
            )
        except Exception as e:
            print(f"Withdrawal saved but admin notification failed: {e}")
    await update.message.reply_text(
        f"✅ Withdrawal request #{result['id']} for {amount} ETB was submitted. Your balance is now shared across the bot and Mini App. Check your withdrawal status in the Mini App or contact support.",
        reply_markup=main_menu(get_lang(user.id)),
    )
    return ConversationHandler.END


def support_content(lang):
    t = TEXTS[lang]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t["btn_contact_support"], callback_data="contact_admin")],
        [InlineKeyboardButton("📢 Official Channel", url=CHANNEL_URL)],
        [InlineKeyboardButton(t["btn_back"], callback_data="main_menu")],
    ])
    text = t["support_text"].format(channel=CHANNEL_URL)
    return text, keyboard

# --- Core Command Handlers ---
async def send_main_menu_after_keyboard_cleanup(message, lang, text=None):
    """Clear any legacy persistent reply keyboard, then send the current inline menu."""
    await message.reply_text(
        "✅ Menu refreshed.",
        reply_markup=ReplyKeyboardRemove(),
    )
    # Telegram keyboard removal and inline keyboards use different markup types,
    # so send the actual menu as a separate message.
    return await message.reply_text(
        text or TEXTS[lang]["welcome"],
        reply_markup=main_menu(lang),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    await send_main_menu_after_keyboard_cleanup(update.message, lang)


async def set_language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_lang = get_lang(user_id)
    new_lang = "am" if current_lang == "en" else "en"
    await set_lang(user_id, new_lang)
    msg = "🌐 Language changed to English!" if new_lang == "en" else "🌐 ቋንቋ ወደ አማርኛ ተቀይሯል!"
    await send_main_menu_after_keyboard_cleanup(update.message, new_lang, text=msg)

# --- Typed Slash Commands (/howitworks, /payment, /requirements, ...) ---
def make_text_command(text_key):
    """Builds a command handler that replies with TEXTS[lang][text_key]."""
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        lang = get_lang(update.effective_user.id)
        await update.message.reply_text(TEXTS[lang][text_key], reply_markup=back_main(lang))
    return handler

cmd_how = make_text_command("how_it_works")
cmd_payment = make_text_command("payment_info")
cmd_requirements = make_text_command("requirements")

async def cmd_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    await update.message.reply_text(
        TEXTS[lang]["task_info"],
        parse_mode="Markdown",
        reply_markup=task_keyboard(lang, user_id),
    )

async def cmd_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    await update.message.reply_text(faq_heading(lang), reply_markup=faq_menu(lang))

async def cmd_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    text, keyboard = support_content(lang)
    await update.message.reply_text(text, reply_markup=keyboard)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel - leaves any screenshot / payment / receipt step and shows the menu."""
    lang = get_lang(update.effective_user.id)
    for key in ("pending_receipt_sub", "reply_target", "broadcast"):
        context.user_data.pop(key, None)
    await update.message.reply_text(TEXTS[lang]["cancelled"], reply_markup=main_menu(lang))
    return ConversationHandler.END

async def start_and_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start while inside a conversation step - reset and show the menu."""
    await start(update, context)
    return ConversationHandler.END

# --- Menu Callback Handler ---
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    lang = get_lang(user_id)
    t = TEXTS[lang]

    if data == "main_menu":
        await query.edit_message_text(t["welcome"], reply_markup=main_menu(lang))

    elif data == "toggle_language":
        new_lang = "am" if lang == "en" else "en"
        await set_lang(user_id, new_lang)
        new_t = TEXTS[new_lang]
        await query.edit_message_text(new_t["welcome"], reply_markup=main_menu(new_lang))

    elif data == "get_task":
        await query.edit_message_text(
            t["task_info"],
            parse_mode="Markdown",
            reply_markup=task_keyboard(lang, user_id),
        )

    elif data == "wallet_view":
        try:
            await query.edit_message_text(await wallet_message(user_id, lang), reply_markup=wallet_keyboard(lang))
        except Exception as e:
            print(f"Wallet view failed: {e}")
            await query.edit_message_text("The shared wallet is temporarily unavailable. Please try again later.", reply_markup=back_main(lang))

    elif data == "withdrawal_history":
        try:
            await query.edit_message_text(await withdrawal_history_message(user_id, lang), reply_markup=wallet_keyboard(lang))
        except Exception as e:
            print(f"Withdrawal history view failed: {e}")
            await query.edit_message_text("Your withdrawal history is temporarily unavailable. Please try again later.", reply_markup=wallet_keyboard(lang))

    elif data in ("task_history", "task_history_refresh"):
        try:
            await query.edit_message_text(await task_history_message(user_id, lang), reply_markup=task_history_keyboard(lang))
        except Exception as e:
            print(f"Shared task history failed: {e}")
            await query.edit_message_text("Your shared task history is temporarily unavailable. Please try again later.", reply_markup=back_main(lang))

    elif data == "how_it_works":
        await query.edit_message_text(t["how_it_works"], reply_markup=back_main(lang))

    elif data == "payment_info":
        await query.edit_message_text(t["payment_info"], reply_markup=back_main(lang))

    elif data == "requirements":
        await query.edit_message_text(t["requirements"], reply_markup=back_main(lang))

    elif data == "faq":
        await query.edit_message_text(faq_heading(lang), reply_markup=faq_menu(lang))

    elif data in FAQ_ANSWERS[lang]:
        await query.edit_message_text(FAQ_ANSWERS[lang][data], reply_markup=faq_back(lang))

    elif data == "support":
        text, keyboard = support_content(lang)
        await query.edit_message_text(text, reply_markup=keyboard)

# --- Screenshot Submission Flow ---
async def start_screenshot_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Works both from the inline button and from the /submit command."""
    user_id = update.effective_user.id
    lang = get_lang(user_id)

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(TEXTS[lang]["prompt_screenshot"], parse_mode="Markdown")
    else:
        await update.message.reply_text(TEXTS[lang]["prompt_screenshot"], parse_mode="Markdown")
    return WAITING_SCREENSHOT

async def screenshot_wrong_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    await update.message.reply_text(TEXTS[lang]["screenshot_wrong_input"], parse_mode="Markdown")
    return WAITING_SCREENSHOT

async def receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    lang = get_lang(user.id)
    photo_id = update.message.photo[-1].file_id
    now = int(time.time())

    # Submit evidence against the shared assigned task so the Mini App and bot
    # show one status, one screenshot and one reward.
    if USE_PG:
        try:
            task = await db(
                "SELECT id FROM public.mp_tasks WHERE user_id = ? AND status = 'assigned' "
                "AND expires_at > NOW() ORDER BY assigned_at DESC LIMIT 1",
                (user.id,), "one",
            )
            if not task:
                await update.message.reply_text(
                    "You don't have an assigned task awaiting proof. Request a task first, then submit your screenshot after the admin assigns it.",
                    reply_markup=task_keyboard(lang, user.id),
                )
                return ConversationHandler.END

            telegram_file = await update.message.photo[-1].get_file()
            image_bytes = bytes(await telegram_file.download_as_bytearray())
            if len(image_bytes) > 3000000:
                await update.message.reply_text("That screenshot is larger than 3 MB. Please send a smaller image.")
                return ConversationHandler.END
            image_data = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
            updated = await db(
                "UPDATE public.mp_tasks SET status='submitted', evidence_image_data=?, submitted_at=NOW() "
                "WHERE id=? AND user_id=? AND status='assigned' AND expires_at>NOW() RETURNING id",
                (image_data, task["id"], user.id), "one",
            )
            if not updated:
                await update.message.reply_text("This task has expired or was already submitted. Check My tasks for the latest status.")
                return ConversationHandler.END

            if ADMIN_CHAT_ID:
                try:
                    await context.bot.send_photo(
                        chat_id=ADMIN_CHAT_ID,
                        photo=photo_id,
                        caption=(f"📥 MAILPAY ET — TASK #{task['id']} EVIDENCE SUBMITTED\n"
                                 f"Customer: {user.full_name}\nTelegram ID: {user.id}\n"
                                 "Evidence is also saved in the unified admin dashboard."),
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("Open unified admin panel", web_app=WebAppInfo(url="https://mailpay-et-miniapp.onrender.com/admin"))
                        ]]),
                    )
                except Exception as notify_error:
                    print(f"Could not notify admin about shared task evidence: {notify_error}")

            await update.message.reply_text(
                f"✅ Screenshot received for task #{task['id']}. Your task is now under review. Check My tasks or the Mini App for updates.",
                reply_markup=main_menu(lang),
            )
            return ConversationHandler.END
        except Exception as e:
            print(f"Failed to save shared task evidence: {e}")
            await update.message.reply_text("Could not submit your screenshot to the shared task system. Please try again or contact support.")
            return ConversationHandler.END

    await update.message.reply_text("The shared task system is not connected. Please contact support.")
    return ConversationHandler.END


# --- Shared admin message builders ---
def decision_keyboard(sub_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"adm_approve_{sub_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"adm_reject_{sub_id}"),
        ],
        [InlineKeyboardButton("📋 Panel", callback_data="adm_panel")],
    ])


def submission_caption(sub, note=""):
    text = (
        f"🚨 <b>SCREENSHOT #{sub['id']}</b>\n\n"
        f"👤 <b>User:</b> {user_link(sub['user_id'], display_name(sub))} ({username_html(sub)})\n"
        f"🆔 <b>ID:</b> <code>{sub['user_id']}</code>\n"
        f"🌐 <b>Lang:</b> {(sub.get('lang') or 'en').upper()}\n"
        f"🕒 <b>Sent:</b> {fmt_time(sub.get('created_at'))} (EAT)\n\n"
        f"Is this the correct Gmail account based on the provided info?"
    )
    if note:
        text += f"\n\n{note}"
    return text


def payout_text(sub):
    return (
        f"💸 <b>PAYOUT #{sub['id']}</b>\n\n"
        f"👤 <b>User:</b> {user_link(sub['user_id'], display_name(sub))} ({username_html(sub)})\n"
        f"🆔 <b>ID:</b> <code>{sub['user_id']}</code>\n"
        f"🏦 <b>Method:</b> {html.escape(sub.get('method') or '-')}\n"
        f"🔢 <b>Details:</b> <code>{html.escape(sub.get('payment_details') or '-')}</code>\n"
        f"💰 <b>Amount:</b> {sub.get('amount') or PAY_PER_ACCOUNT} ETB"
    )


def payout_keyboard(sub_id, with_back=True):
    rows = [[
        InlineKeyboardButton("📸 Send Receipt", callback_data=f"adm_receipt_{sub_id}"),
        InlineKeyboardButton("✅ Mark Paid", callback_data=f"adm_markpaid_{sub_id}"),
    ]]
    if with_back:
        rows.append([InlineKeyboardButton("🔙 Payouts", callback_data="adm_payouts")])
    return InlineKeyboardMarkup(rows)


# --- Admin Decision Handler (Approve / Reject) ---
async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer()
        return

    parts = query.data.split("_")
    action = parts[1]
    sub_id = int(parts[2])
    sub = await get_submission(sub_id)

    if not sub:
        await query.answer("Submission not found.", show_alert=True)
        return
    if sub["status"] != "pending":
        await query.answer(f"Already {sub['status']}.", show_alert=True)
        return
    await query.answer()

    target_user_id = sub["user_id"]
    target_lang = get_lang(target_user_id)
    now = int(time.time())
    original_caption = query.message.caption_html or ""
    after_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏳ Pending list", callback_data="adm_pending"),
        InlineKeyboardButton("📋 Panel", callback_data="adm_panel"),
    ]])

    if action == "approve":
        await db("UPDATE submissions SET status = 'approved', decided_at = ? WHERE id = ?", (now, sub_id))
        await query.edit_message_caption(
            caption=f"{original_caption}\n\n✅ <b>STATUS: APPROVED</b>\nUser notified to enter payment details.",
            parse_mode="HTML",
            reply_markup=after_keyboard,
        )

        method_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Telebirr", callback_data=f"user_method_Telebirr_{sub_id}")],
            [InlineKeyboardButton("M-Pesa", callback_data=f"user_method_M-Pesa_{sub_id}")],
            [InlineKeyboardButton("Commercial Bank of Ethiopia (CBE)", callback_data=f"user_method_CBE_{sub_id}")],
        ])
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=TEXTS[target_lang]["approved_msg"],
                parse_mode="Markdown",
                reply_markup=method_keyboard,
            )
        except Exception as e:
            print(f"Failed to notify user {target_user_id}: {e}")

    elif action == "reject":
        await db("UPDATE submissions SET status = 'rejected', decided_at = ? WHERE id = ?", (now, sub_id))
        await query.edit_message_caption(
            caption=f"{original_caption}\n\n❌ <b>STATUS: REJECTED</b>",
            parse_mode="HTML",
            reply_markup=after_keyboard,
        )
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=TEXTS[target_lang]["rejected_msg"],
                parse_mode="Markdown",
            )
        except Exception as e:
            print(f"Failed to notify user {target_user_id}: {e}")


# --- Payment Collection Flow ---
async def select_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    lang = get_lang(user_id)

    parts = query.data.split("_")
    method = parts[2]
    try:
        sub_id = int(parts[3])
    except (IndexError, ValueError):
        sub_id = 0

    sub = await get_submission(sub_id) if sub_id else None
    if (
        not sub
        or sub["user_id"] != user_id
        or sub["status"] != "approved"
        or sub["payout_status"] not in ("none", "awaiting_details")
    ):
        await query.answer(TEXTS[lang]["payment_unavailable"], show_alert=True)
        return ConversationHandler.END

    await query.answer()
    await db("UPDATE submissions SET method = ?, payout_status = 'awaiting_details' WHERE id = ?", (method, sub_id))
    context.user_data["payment_method"] = method
    context.user_data["payment_sub"] = sub_id

    await query.edit_message_text(
        TEXTS[lang]["prompt_payment"].format(method=method),
        parse_mode="Markdown",
    )
    return WAITING_PAYMENT_DETAILS


async def receive_payment_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    lang = get_lang(user.id)
    details = (update.message.text or "").strip()[:200]
    method = context.user_data.get("payment_method", "Payment Method")
    sub_id = context.user_data.get("payment_sub")

    if not sub_id:
        await update.message.reply_text(TEXTS[lang]["payment_unavailable"], reply_markup=main_menu(lang))
        return ConversationHandler.END

    try:
        await db(
            "UPDATE submissions SET payment_details = ?, method = ?, payout_status = 'pending_payout' "
            "WHERE id = ? AND user_id = ?",
            (details, method, sub_id, user.id),
        )
        sub = await get_submission(sub_id)
        if ADMIN_CHAT_ID and sub:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=payout_text(sub),
                parse_mode="HTML",
                reply_markup=payout_keyboard(sub_id, with_back=False),
            )
    except Exception as e:
        print(f"Failed to save/send payment details: {e}")

    context.user_data.pop("payment_sub", None)
    await update.message.reply_text(
        TEXTS[lang]["payment_received"],
        parse_mode="Markdown",
        reply_markup=main_menu(lang),
    )
    return ConversationHandler.END


# --- Admin Receipt Delivery Flow ---
async def start_receipt_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_CHAT_ID:
        return ConversationHandler.END

    sub_id = int(query.data.split("_")[2])
    sub = await get_submission(sub_id)
    if not sub:
        await query.message.reply_text("⚠️ Submission not found.")
        return ConversationHandler.END
    if sub["payout_status"] == "paid":
        await query.message.reply_text(f"ℹ️ Payout #{sub_id} is already marked as paid.")
        return ConversationHandler.END

    context.user_data["pending_receipt_sub"] = sub_id
    await query.message.reply_text(
        f"📸 SEND PAYMENT RECEIPT\n\nSend the transfer receipt photo now for payout #{sub_id} "
        f"(user ID {sub['user_id']}).\nSend /cancel to stop."
    )
    return WAITING_RECEIPT_PHOTO


async def receipt_wrong_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ Please send the receipt as a photo, or /cancel.")
    return WAITING_RECEIPT_PHOTO


async def receive_admin_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sub_id = context.user_data.get("pending_receipt_sub")
    sub = await get_submission(sub_id) if sub_id else None

    if not sub:
        await update.message.reply_text("⚠️ No payout selected to send this receipt for.")
        return ConversationHandler.END

    target_user_id = sub["user_id"]
    target_lang = get_lang(target_user_id)
    photo_file_id = update.message.photo[-1].file_id

    try:
        await context.bot.send_photo(
            chat_id=target_user_id,
            photo=photo_file_id,
            caption=TEXTS[target_lang]["receipt_delivered"],
            parse_mode="Markdown",
        )
        await db("UPDATE submissions SET payout_status = 'paid', paid_at = ? WHERE id = ?", (int(time.time()), sub_id))
        await update.message.reply_text(
            f"✅ Receipt delivered to user (ID: {target_user_id}). Payout #{sub_id} marked as paid.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💸 Payouts", callback_data="adm_payouts"),
                InlineKeyboardButton("📋 Panel", callback_data="adm_panel"),
            ]]),
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to deliver receipt to user: {e}")

    context.user_data.pop("pending_receipt_sub", None)
    return ConversationHandler.END


# =====================================================================
# ADMIN PANEL  (/admin - only works for ADMIN_CHAT_ID)
# =====================================================================
def panel_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Stats", callback_data="adm_stats"),
            InlineKeyboardButton("🔍 Find customer", callback_data="adm_find"),
        ],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="adm_bc"),
            InlineKeyboardButton("📤 Export CSV", callback_data="adm_export"),
        ],
        [
            InlineKeyboardButton(
                "💸 Unified Tasks & Payouts",
                web_app=WebAppInfo(
                    url="https://mailpay-et-miniapp.onrender.com/admin"
                ),
            ),
        ],
    ])


def back_to_panel():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Panel", callback_data="adm_panel")]])


def back_to_payouts():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💸 Payouts", callback_data="adm_payouts"),
        InlineKeyboardButton("📋 Panel", callback_data="adm_panel"),
    ]])


async def panel_text():
    pending = (await db("SELECT COUNT(*) AS n FROM submissions WHERE status = 'pending'", (), "one"))["n"]
    owed = await db(
        "SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total FROM submissions "
        "WHERE status = 'approved' AND payout_status = 'pending_payout'", (), "one",
    )
    return (
        "🛠 <b>ADMIN PANEL</b>\n\n"
        f"⏳ Pending screenshots: <b>{pending}</b>\n"
        f"💸 Payouts to send: <b>{owed['n']}</b> ({int(owed['total'])} ETB)\n\n"
        "Choose an option 👇"
    )


async def show(query, text, reply_markup=None):
    """Edits the current message, or sends a new one if it is a photo (photos can't be edited into text)."""
    msg = query.message
    try:
        if msg.photo or msg.document:
            await msg.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await msg.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await panel_text(), parse_mode="HTML", reply_markup=panel_keyboard())


async def admin_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles every simple admin-panel button."""
    query = update.callback_query
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer()
        return
    await query.answer()
    data = query.data

    # ---- main panel
    if data == "adm_panel":
        await show(query, await panel_text(), panel_keyboard())

    # ---- stats
    elif data == "adm_stats":
        total_users = (await db("SELECT COUNT(*) AS n FROM users WHERE user_id != ?", (ADMIN_CHAT_ID,), "one"))["n"]
        midnight = int(datetime.now(EAT).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        new_today = (await db(
            "SELECT COUNT(*) AS n FROM users WHERE user_id != ? AND first_seen >= ?", (ADMIN_CHAT_ID, midnight), "one"
        ))["n"]
        by_status = {
            r["status"]: r["n"]
            for r in await db("SELECT status, COUNT(*) AS n FROM submissions GROUP BY status", (), "all")
        }
        pay_rows = await db(
            "SELECT payout_status, COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total FROM submissions "
            "WHERE status = 'approved' GROUP BY payout_status", (), "all",
        )
        pay = {r["payout_status"]: (r["n"], int(r["total"])) for r in pay_rows}
        pending, approved, rejected = (by_status.get(k, 0) for k in ("pending", "approved", "rejected"))
        to_pay_n, to_pay_amt = pay.get("pending_payout", (0, 0))
        paid_n, paid_amt = pay.get("paid", (0, 0))
        waiting_n = pay.get("none", (0, 0))[0] + pay.get("awaiting_details", (0, 0))[0]
        text = (
            "📊 <b>STATS</b>\n\n"
            f"👥 Customers: <b>{total_users}</b> (+{new_today} today)\n\n"
            f"📸 Submissions: <b>{pending + approved + rejected}</b>\n"
            f"   ⏳ Pending: {pending}\n"
            f"   ✅ Approved: {approved}\n"
            f"   ❌ Rejected: {rejected}\n\n"
            "💸 <b>Payouts</b>\n"
            f"   To pay now: <b>{to_pay_n}</b> ({to_pay_amt} ETB)\n"
            f"   Waiting for customer's payment details: {waiting_n}\n"
            f"   Paid: <b>{paid_n}</b> ({paid_amt} ETB)"
        )
        await show(query, text, back_to_panel())

    # ---- pending screenshots
    elif data == "adm_pending":
        rows = await db(
            "SELECT s.id, s.created_at, s.user_id, u.username, u.full_name FROM submissions s "
            "LEFT JOIN users u ON u.user_id = s.user_id WHERE s.status = 'pending' ORDER BY s.id ASC LIMIT 15",
            (), "all",
        )
        if not rows:
            await show(query, "✅ <b>No pending screenshots.</b>", back_to_panel())
            return
        keyboard = [
            [InlineKeyboardButton(
                f"#{r['id']} · {short(display_name(r))} · {ago(r['created_at'])}",
                callback_data=f"adm_view_{r['id']}",
            )]
            for r in rows
        ]
        keyboard.append([InlineKeyboardButton("🔙 Panel", callback_data="adm_panel")])
        await show(
            query,
            f"⏳ <b>PENDING SCREENSHOTS</b> ({len(rows)})\n\nTap one to review it 👇",
            InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("adm_view_"):
        sub = await get_submission(int(data.split("_")[2]))
        if not sub:
            await show(query, "⚠️ Submission not found.", back_to_panel())
            return
        if sub["status"] == "pending":
            note, keyboard = "", decision_keyboard(sub["id"])
        else:
            note = f"Status: <b>{sub['status'].upper()}</b> · Payout: <b>{sub['payout_status']}</b>"
            keyboard = back_to_panel()
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=sub["photo_id"],
                caption=submission_caption(sub, note),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Could not load the screenshot: {e}")

    # ---- payouts
    elif data == "adm_payouts":
        rows = await db(
            "SELECT s.id, s.amount, s.method, s.user_id, u.username, u.full_name FROM submissions s "
            "LEFT JOIN users u ON u.user_id = s.user_id "
            "WHERE s.status = 'approved' AND s.payout_status = 'pending_payout' ORDER BY s.id ASC LIMIT 20",
            (), "all",
        )
        if not rows:
            await show(query, "✅ <b>No payouts waiting.</b>", back_to_panel())
            return
        total = sum(int(r["amount"] or PAY_PER_ACCOUNT) for r in rows)
        keyboard = [
            [InlineKeyboardButton(
                f"#{r['id']} · {r['amount']} ETB · {r['method']} · {short(display_name(r), 14)}",
                callback_data=f"adm_pay_{r['id']}",
            )]
            for r in rows
        ]
        keyboard.append([InlineKeyboardButton("🔙 Panel", callback_data="adm_panel")])
        await show(
            query,
            f"💸 <b>PAYOUTS TO SEND</b>\n\n{len(rows)} waiting · total <b>{total} ETB</b>\n\nTap one for the payment details 👇",
            InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("adm_pay_"):
        sub = await get_submission(int(data.split("_")[2]))
        if not sub:
            await show(query, "⚠️ Payout not found.", back_to_payouts())
            return
        text = payout_text(sub)
        if sub["payout_status"] == "paid":
            text += f"\n\n✅ Paid on {fmt_time(sub.get('paid_at'))}"
            await show(query, text, back_to_payouts())
        else:
            await show(query, text, payout_keyboard(sub["id"]))

    elif data.startswith("adm_markpaid_"):
        sub_id = int(data.split("_")[2])
        sub = await get_submission(sub_id)
        if not sub or sub["payout_status"] != "pending_payout":
            await show(query, "ℹ️ This payout is not waiting to be paid (already paid, or not found).", back_to_payouts())
            return
        await db("UPDATE submissions SET payout_status = 'paid', paid_at = ? WHERE id = ?", (int(time.time()), sub_id))
        note = ""
        try:
            await context.bot.send_message(
                chat_id=sub["user_id"],
                text=TEXTS[get_lang(sub["user_id"])]["payment_sent"],
                parse_mode="Markdown",
            )
        except Exception as e:
            note = f"\n⚠️ Could not notify the customer: {html.escape(str(e))}"
        await show(query, f"✅ Payout #{sub_id} marked as paid.{note}", back_to_payouts())

    # ---- export
    elif data == "adm_export":
        rows = await db(
            "SELECT s.id, s.user_id, u.username, u.full_name, s.status, s.payout_status, s.method, "
            "s.payment_details, s.amount, s.created_at, s.decided_at, s.paid_at FROM submissions s "
            "LEFT JOIN users u ON u.user_id = s.user_id ORDER BY s.id",
            (), "all",
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "user_id", "username", "name", "status", "payout_status", "method",
                         "payment_details", "amount_etb", "submitted", "decided", "paid"])
        for r in rows:
            writer.writerow([
                r["id"], r["user_id"], r["username"] or "", r["full_name"] or "", r["status"], r["payout_status"],
                r["method"] or "", r["payment_details"] or "", r["amount"],
                fmt_time(r["created_at"]), fmt_time(r["decided_at"]), fmt_time(r["paid_at"]),
            ])
        file_bytes = io.BytesIO(buffer.getvalue().encode("utf-8-sig"))  # utf-8-sig so Excel shows Amharic names
        await context.bot.send_document(
            chat_id=ADMIN_CHAT_ID,
            document=file_bytes,
            filename=f"mailpay_{datetime.now(EAT).strftime('%Y-%m-%d')}.csv",
            caption=f"📤 {len(rows)} submissions",
        )

    # ---- broadcast confirmation
    elif data == "adm_bc_cancel":
        context.user_data.pop("broadcast", None)
        await show(query, "❌ Broadcast cancelled.", back_to_panel())

    elif data == "adm_bc_confirm":
        source = context.user_data.pop("broadcast", None)
        if not source:
            await show(query, "⚠️ Nothing to send. Start again from the panel.", back_to_panel())
            return
        await show(query, "📢 Sending… I'll message you when it's finished.")
        # runs in the background so the bot keeps answering customers meanwhile
        context.application.create_task(run_broadcast(context.bot, source, query.message.chat_id))


async def run_broadcast(bot, source, report_chat_id):
    chat_id, message_id = source
    rows = await db("SELECT user_id FROM users WHERE user_id != ?", (ADMIN_CHAT_ID,), "all")
    sent = failed = 0
    for r in rows:
        uid = r["user_id"]
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=chat_id, message_id=message_id)
            sent += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.copy_message(chat_id=uid, from_chat_id=chat_id, message_id=message_id)
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1  # usually: the customer blocked the bot
        await asyncio.sleep(0.06)  # stays under Telegram's rate limit
    await bot.send_message(
        chat_id=report_chat_id,
        text=f"📢 Broadcast finished.\n✅ Delivered: {sent}\n❌ Failed (blocked the bot, etc.): {failed}",
        reply_markup=back_to_panel(),
    )


# ---- Find customer (conversation)
async def start_find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_CHAT_ID:
        return ConversationHandler.END
    await query.message.reply_text(
        "🔍 <b>FIND CUSTOMER</b>\n\nSend a user ID (numbers) or a @username.\nSend /cancel to stop.",
        parse_mode="HTML",
    )
    return WAITING_ADMIN_SEARCH


async def do_find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text.lstrip("-").isdigit():
        row = await db("SELECT * FROM users WHERE user_id = ?", (int(text),), "one")
    else:
        row = await db("SELECT * FROM users WHERE LOWER(username) = ?", (text.lstrip("@").lower(),), "one")

    if not row:
        await update.message.reply_text(
            "❌ Not found. A customer shows up here after their first message to the bot.\n"
            "Try again, or send /cancel."
        )
        return WAITING_ADMIN_SEARCH

    uid = row["user_id"]
    groups = await db(
        "SELECT status, payout_status, COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total FROM submissions "
        "WHERE user_id = ? GROUP BY status, payout_status", (uid,), "all",
    )
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    paid_total = 0
    for g in groups:
        counts[g["status"]] = counts.get(g["status"], 0) + g["n"]
        if g["payout_status"] == "paid":
            paid_total += int(g["total"])
    recent = await db(
        "SELECT id, status, payout_status, created_at FROM submissions WHERE user_id = ? ORDER BY id DESC LIMIT 8",
        (uid,), "all",
    )
    icons = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
    history = "\n".join(
        f"#{s['id']} · {fmt_time(s['created_at'])} · {icons.get(s['status'], '')} {s['status']}"
        + (f" · 💸 {s['payout_status']}" if s["status"] == "approved" else "")
        for s in recent
    ) or "No submissions yet."

    card = (
        f"👤 <b>{html.escape(display_name(row))}</b> ({username_html(row)})\n"
        f"🆔 <code>{uid}</code>\n"
        f"🌐 Language: {(row.get('lang') or 'en').upper()}\n"
        f"📅 First seen: {fmt_time(row.get('first_seen'))} · Last active: {ago(row.get('last_seen'))}\n\n"
        f"📸 Submissions: ⏳ {counts['pending']} · ✅ {counts['approved']} · ❌ {counts['rejected']}\n"
        f"💰 Paid so far: <b>{paid_total} ETB</b>\n\n"
        f"<b>Recent</b>\n{history}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Message this customer", callback_data=f"adm_reply_{uid}")],
        [InlineKeyboardButton("🔙 Panel", callback_data="adm_panel")],
    ])
    await update.message.reply_text(card, parse_mode="HTML", reply_markup=keyboard)
    return ConversationHandler.END


# ---- Broadcast (conversation)
async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_CHAT_ID:
        return ConversationHandler.END
    await query.message.reply_text(
        "📢 <b>BROADCAST</b>\n\nSend the announcement now (text or photo).\n"
        "I'll ask you to confirm before anything is sent.\nSend /cancel to stop.",
        parse_mode="HTML",
    )
    return WAITING_BROADCAST


async def receive_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    n = (await db("SELECT COUNT(*) AS n FROM users WHERE user_id != ?", (ADMIN_CHAT_ID,), "one"))["n"]
    if not n:
        await msg.reply_text("ℹ️ There are no customers yet.")
        return ConversationHandler.END
    context.user_data["broadcast"] = (msg.chat_id, msg.message_id)
    await msg.reply_text(
        f"📢 Send the message above to <b>{n}</b> customers?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Send now", callback_data="adm_bc_confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="adm_bc_cancel"),
        ]]),
    )
    return ConversationHandler.END


# --- Contact Admin Through the Bot ---
def admin_reply_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Reply", callback_data=f"adm_reply_{user_id}")]
    ])

def user_reply_keyboard(lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(TEXTS[lang]["btn_reply_admin"], callback_data="contact_admin")]
    ])

def user_header_html(user, lang, title):
    name = html.escape(user.full_name or "Unknown")
    username = f"@{html.escape(user.username)}" if user.username else "no username"
    return (
        f"{title}\n\n"
        f"👤 <b>User:</b> <a href=\"tg://user?id={user.id}\">{name}</a> ({username})\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"🌐 <b>Lang:</b> {lang.upper()}"
    )

async def contact_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Message the Admin' button or /contact - tells the user to type their message."""
    lang = get_lang(update.effective_user.id)
    if update.callback_query:
        await update.callback_query.answer()
        target = update.callback_query.message
    else:
        target = update.message
    await target.reply_text(
        TEXTS[lang]["contact_prompt"],
        parse_mode="Markdown",
        reply_markup=back_main(lang),
    )

async def request_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create the same shared task request as the Mini App and notify the admin."""
    query = update.callback_query
    user = query.from_user
    lang = get_lang(user.id)
    await query.answer()

    if not USE_PG:
        await query.message.reply_text(
            "The shared task system is not connected. Please contact support.",
            reply_markup=main_menu(lang),
        )
        return

    try:
        await ensure_shared_wallet(user.id)
        result = await asyncio.to_thread(_create_shared_task_request, user)
    except Exception as e:
        print(f"Failed to create shared task request: {e}")
        await query.message.reply_text("Could not save your task request. Please try again later.")
        return

    if not result.get("created"):
        await query.message.reply_text(
            f"You already have active task #{result.get('id')} ({result.get('status')}). Check My tasks for instructions and status.",
            reply_markup=task_history_keyboard(lang),
        )
        return

    context.user_data["last_task_request"] = time.time()
    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(f"🆕 NEW SHARED MAILPAY ET TASK REQUEST #{result['id']}\n\n"
                      f"👤 {user.full_name} (@{user.username or 'no username'})\n"
                      f"🆔 Telegram ID: {user.id}\n\n"
                      "This request is stored in the unified database and appears in the web admin panel."),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Open unified admin panel", web_app=WebAppInfo(url="https://mailpay-et-miniapp.onrender.com/admin"))
                ]]),
            )
        except Exception as e:
            print(f"Task saved but admin message could not be sent: {e}")

    await query.edit_message_text(
        f"✅ Your task request #{result['id']} has been saved. The admin will assign your instructions here and in the Mini App.\n\nYou can check its status from My tasks.",
        reply_markup=task_history_keyboard(lang),
    )

async def receive_contact_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Any normal message a customer sends to the bot -> forwarded to the admin + auto-reply."""
    user = update.effective_user
    msg = update.message
    lang = get_lang(user.id)

    try:
        header = user_header_html(user, lang, "📩 <b>NEW MESSAGE FROM USER</b>")
        if msg.text:
            body = html.escape(msg.text[:3500])
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"{header}\n\n💬 {body}",
                parse_mode="HTML",
                reply_markup=admin_reply_keyboard(user.id),
            )
        else:
            # photos, voice notes, documents, etc.
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=header, parse_mode="HTML")
            await context.bot.copy_message(
                chat_id=ADMIN_CHAT_ID,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id,
                reply_markup=admin_reply_keyboard(user.id),
            )
    except Exception as e:
        print(f"Failed to forward user message to admin: {e}")
        await msg.reply_text(TEXTS[lang]["contact_failed"].format(support=SUPPORT_USERNAME))
        return

    # Full auto-reply the first time (or after a quiet period), short confirmation otherwise
    now = time.time()
    last_ack = context.user_data.get("last_ack", 0)
    context.user_data["last_ack"] = now
    if now - last_ack > ACK_WINDOW:
        await msg.reply_text(TEXTS[lang]["contact_ack"], parse_mode="Markdown", reply_markup=back_main(lang))
    else:
        await msg.reply_text(TEXTS[lang]["contact_sent_short"])

async def start_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin taps '✍️ Reply' under a user's message."""
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_CHAT_ID:
        return ConversationHandler.END

    target_user_id = int(query.data.split("_")[2])
    context.user_data["reply_target"] = target_user_id
    await query.message.reply_text(
        f"✍️ Type your reply for user ID {target_user_id} now (text, photo, voice...).\nSend /cancel to stop."
    )
    return WAITING_ADMIN_REPLY

async def send_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delivers the admin's next message to the user, with a Reply button for them."""
    target_user_id = context.user_data.pop("reply_target", None)
    if not target_user_id:
        await update.message.reply_text("⚠️ No user selected. Tap ✍️ Reply under a user's message first.")
        return ConversationHandler.END

    target_lang = get_lang(target_user_id)
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=TEXTS[target_lang]["admin_reply_header"],
            parse_mode="Markdown",
        )
        await context.bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
            reply_markup=user_reply_keyboard(target_lang),
        )
        await update.message.reply_text(f"✅ Reply delivered to user (ID: {target_user_id}).")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to deliver reply to user {target_user_id}: {e}")
    return ConversationHandler.END

# --- Error Handler (so problems show up in your logs instead of failing silently) ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error while handling an update: {context.error}")


# --- Startup: database + Telegram "/" command menu ---
async def post_init(application: Application):
    await asyncio.to_thread(init_db)
    rows = await db("SELECT user_id, lang FROM users", (), "all")
    for r in rows:
        USER_LANG[r["user_id"]] = r["lang"] or "en"
    print(f"Database ready ({'Postgres' if USE_PG else 'SQLite file: ' + SQLITE_PATH}) - {len(rows)} users loaded.")
    if not USE_PG:
        print("WARNING: DATABASE_URL is not set. On Render's free plan the SQLite file is deleted on every restart.")

    commands = [
        BotCommand("start", "Open the main menu"),
        BotCommand("task", "Get a Gmail task"),
        BotCommand("wallet", "View your shared balance"),
        BotCommand("mytasks", "View shared task history"),
        BotCommand("withdraw", "Request a withdrawal"),
        BotCommand("withdrawals", "View withdrawal history"),
        BotCommand("submit", "Submit a screenshot"),
        BotCommand("howitworks", "How it works"),
        BotCommand("payment", "Payment info"),
        BotCommand("requirements", "Requirements & rules"),
        BotCommand("faq", "Frequently asked questions"),
        BotCommand("support", "Contact support"),
        BotCommand("contact", "Message the Admin"),
        BotCommand("language", "Switch language / ቋንቋ ቀይር"),
        BotCommand("cancel", "Cancel the current step"),
    ]
    await application.bot.set_my_commands(commands)
    try:
        # the /admin command is only listed in the admin's own command menu
        await application.bot.set_my_commands(
            commands + [BotCommand("admin", "Open the admin panel")],
            scope=BotCommandScopeChat(chat_id=ADMIN_CHAT_ID),
        )
    except Exception as e:
        print(f"Could not set admin command menu (start the bot from the admin account first): {e}")


# --- Main Entry Point ---
if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    conversation_fallbacks = [
        CommandHandler("cancel", cancel),
        CommandHandler("start", start_and_end),
    ]

    screenshot_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_screenshot_submission, pattern="^start_submit_screenshot$"),
            CommandHandler("submit", start_screenshot_submission),
        ],
        states={
            WAITING_SCREENSHOT: [
                MessageHandler(filters.PHOTO, receive_screenshot),
                MessageHandler(~filters.PHOTO & ~filters.COMMAND, screenshot_wrong_input),
            ],
        },
        fallbacks=conversation_fallbacks,
        allow_reentry=True,
    )

    payment_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(select_payment_method, pattern="^user_method_")],
        states={
            WAITING_PAYMENT_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_payment_details)],
        },
        fallbacks=conversation_fallbacks,
        allow_reentry=True,
    )

    withdrawal_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_withdrawal, pattern="^wallet_withdraw$"),
            CommandHandler("withdraw", start_withdrawal),
        ],
        states={
            WAITING_WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_withdraw_amount)],
            WAITING_WITHDRAW_METHOD: [CallbackQueryHandler(receive_withdraw_method, pattern=r"^withdraw_method_(Telebirr|M-Pesa|CBE)$")],
            WAITING_WITHDRAW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_withdraw_name)],
            WAITING_WITHDRAW_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_withdraw_account)],
        },
        fallbacks=conversation_fallbacks,
        allow_reentry=True,
    )

    receipt_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_receipt_upload, pattern=r"^adm_receipt_\d+$")],
        states={
            WAITING_RECEIPT_PHOTO: [
                MessageHandler(filters.PHOTO, receive_admin_receipt),
                MessageHandler(~filters.PHOTO & ~filters.COMMAND, receipt_wrong_input),
            ],
        },
        fallbacks=conversation_fallbacks,
        allow_reentry=True,
    )

    admin_reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_admin_reply, pattern=r"^adm_reply_\d+$")],
        states={
            WAITING_ADMIN_REPLY: [MessageHandler(~filters.COMMAND, send_admin_reply)],
        },
        fallbacks=conversation_fallbacks,
        allow_reentry=True,
    )

    find_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_find, pattern="^adm_find$")],
        states={
            WAITING_ADMIN_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_find)],
        },
        fallbacks=conversation_fallbacks,
        allow_reentry=True,
    )

    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_broadcast, pattern="^adm_bc$")],
        states={
            WAITING_BROADCAST: [MessageHandler(~filters.COMMAND, receive_broadcast)],
        },
        fallbacks=conversation_fallbacks,
        allow_reentry=True,
    )

    # Runs first for every update: remembers who uses the bot
    app.add_handler(TypeHandler(Update, track_user), group=-1)

    app.add_handler(screenshot_conv)
    app.add_handler(payment_conv)
    app.add_handler(withdrawal_conv)
    app.add_handler(receipt_conv)
    app.add_handler(admin_reply_conv)
    app.add_handler(find_conv)
    app.add_handler(broadcast_conv)

    # Typed commands
    app.add_handler(CommandHandler(["start", "menu", "help"], start))
    app.add_handler(CommandHandler("language", set_language_cmd))
    app.add_handler(CommandHandler(["howitworks", "how"], cmd_how))
    app.add_handler(CommandHandler(["payment", "paymentinfo"], cmd_payment))
    # "requirments" is included because it's a very common typo
    app.add_handler(CommandHandler(["requirements", "requirement", "requirments", "rules"], cmd_requirements))
    app.add_handler(CommandHandler("faq", cmd_faq))
    app.add_handler(CommandHandler(["task", "gettask"], cmd_task))
    app.add_handler(CommandHandler("wallet", cmd_wallet))
    app.add_handler(CommandHandler("mytasks", cmd_my_tasks))
    app.add_handler(CommandHandler("withdrawals", cmd_withdrawal_history))
    app.add_handler(CommandHandler("support", cmd_support))
    app.add_handler(CommandHandler("contact", contact_prompt))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("admin", admin_cmd, filters=filters.User(user_id=ADMIN_CHAT_ID)))

    # Button callbacks
    app.add_handler(CallbackQueryHandler(request_task, pattern="^request_task$"))
    app.add_handler(CallbackQueryHandler(contact_prompt, pattern="^contact_admin$"))
    app.add_handler(CallbackQueryHandler(admin_decision, pattern=r"^adm_(approve|reject)_\d+$"))
    app.add_handler(CallbackQueryHandler(
        admin_router,
        pattern=r"^adm_(panel|stats|pending|payouts|export|bc_confirm|bc_cancel)$|^adm_(view|pay|markpaid)_\d+$",
    ))
    app.add_handler(CallbackQueryHandler(buttons))

    # Catch-all (must stay LAST): any normal private message from a customer goes to the admin.
    # The admin's own messages are excluded so they are never forwarded back to themselves.
    app.add_handler(MessageHandler(
        filters.UpdateType.MESSAGE
        & filters.ChatType.PRIVATE
        & ~filters.COMMAND
        & ~filters.StatusUpdate.ALL
        & ~filters.User(user_id=ADMIN_CHAT_ID),
        receive_contact_message,
    ))

    app.add_error_handler(error_handler)

    print("MailPay Ethiopia proxy bot is running...")
    app.run_polling()
