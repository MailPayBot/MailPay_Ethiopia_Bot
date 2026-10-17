import html
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
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
WAITING_SCREENSHOT, WAITING_PAYMENT_DETAILS, WAITING_RECEIPT_PHOTO, WAITING_ADMIN_REPLY = range(4)

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
        [InlineKeyboardButton(t["btn_submit_ss"], callback_data="start_submit_screenshot")],
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
        [InlineKeyboardButton(t["btn_contact_admin"], callback_data="request_task")],
        [InlineKeyboardButton(t["btn_submit_ss"], callback_data="start_submit_screenshot")],
        [InlineKeyboardButton(t["btn_back"], callback_data="main_menu")],
    ])

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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    await update.message.reply_text(TEXTS[lang]["welcome"], reply_markup=main_menu(lang))

async def set_language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_lang = get_lang(user_id)
    new_lang = "am" if current_lang == "en" else "en"
    USER_LANG[user_id] = new_lang
    msg = "🌐 Language changed to English!" if new_lang == "en" else "🌐 ቋንቋ ወደ አማርኛ ተቀይሯል!"
    await update.message.reply_text(msg, reply_markup=main_menu(new_lang))

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
    context.user_data.pop("pending_receipt_user", None)
    context.user_data.pop("reply_target", None)
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
        USER_LANG[user_id] = new_lang
        new_t = TEXTS[new_lang]
        await query.edit_message_text(new_t["welcome"], reply_markup=main_menu(new_lang))

    elif data == "get_task":
        await query.edit_message_text(
            t["task_info"],
            parse_mode="Markdown",
            reply_markup=task_keyboard(lang, user_id),
        )

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

    if ADMIN_CHAT_ID:
        try:
            # HTML mode so usernames containing "_" can't break the message
            username = html.escape(user.username) if user.username else "No Username"
            admin_caption = (
                f"🚨 <b>NEW SCREENSHOT SUBMISSION</b>\n\n"
                f"👤 <b>User:</b> @{username} (ID: <code>{user.id}</code>)\n"
                f"🌐 <b>Preferred Lang:</b> {lang.upper()}\n"
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
                parse_mode="HTML",
                reply_markup=admin_keyboard,
            )
        except Exception as e:
            print(f"Failed to forward screenshot to admin: {e}")

    await update.message.reply_text(
        TEXTS[lang]["screenshot_received"],
        parse_mode="Markdown",
        reply_markup=main_menu(lang),
    )
    return ConversationHandler.END

# --- Admin Decision Handler ---
async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    action = parts[1]
    target_user_id = int(parts[2])
    target_lang = get_lang(target_user_id)

    original_caption = query.message.caption_html or ""

    if action == "approve":
        await query.edit_message_caption(
            caption=f"{original_caption}\n\n✅ <b>STATUS: APPROVED</b>\nUser notified to enter payment details.",
            parse_mode="HTML",
        )

        method_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Telebirr", callback_data=f"user_method_Telebirr_{target_user_id}")],
            [InlineKeyboardButton("M-Pesa", callback_data=f"user_method_M-Pesa_{target_user_id}")],
            [InlineKeyboardButton("Commercial Bank of Ethiopia (CBE)", callback_data=f"user_method_CBE_{target_user_id}")],
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
        await query.edit_message_caption(
            caption=f"{original_caption}\n\n❌ <b>STATUS: REJECTED</b>",
            parse_mode="HTML",
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
    await query.answer()

    parts = query.data.split("_")
    method = parts[2]
    user_id = query.from_user.id
    lang = get_lang(user_id)

    context.user_data["payment_method"] = method

    await query.edit_message_text(
        TEXTS[lang]["prompt_payment"].format(method=method),
        parse_mode="Markdown",
    )
    return WAITING_PAYMENT_DETAILS

async def receive_payment_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_details = update.message.text
    method = context.user_data.get("payment_method", "Payment Method")
    user = update.message.from_user
    lang = get_lang(user.id)

    if ADMIN_CHAT_ID:
        try:
            username = html.escape(user.username) if user.username else "No Username"
            admin_msg = (
                f"💳 <b>PAYMENT DETAILS SUBMITTED</b>\n\n"
                f"👤 <b>User:</b> @{username} (ID: <code>{user.id}</code>)\n"
                f"🏦 <b>Method:</b> {html.escape(method)}\n"
                f"🔢 <b>Details:</b> <code>{html.escape(user_details)}</code>\n\n"
                f"📸 <b>Next Step:</b> Tap the button below to send the payout receipt photo once transferred."
            )
            receipt_btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("📸 Send Payment Receipt", callback_data=f"adm_receipt_{user.id}")]
            ])
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_msg,
                parse_mode="HTML",
                reply_markup=receipt_btn,
            )
        except Exception as e:
            print(f"Failed to send payment details to admin: {e}")

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

    parts = query.data.split("_")
    target_user_id = int(parts[2])
    context.user_data["pending_receipt_user"] = target_user_id

    await query.edit_message_text(
        f"📸 *SEND PAYMENT RECEIPT*\n\nPlease upload/send the transfer receipt photo now for User ID: `{target_user_id}`.",
        parse_mode="Markdown",
    )
    return WAITING_RECEIPT_PHOTO

async def receive_admin_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_user_id = context.user_data.get("pending_receipt_user")

    if not target_user_id:
        await update.message.reply_text("⚠️ No user session found to send this receipt to.")
        return ConversationHandler.END

    target_lang = get_lang(target_user_id)
    photo_file_id = update.message.photo[-1].file_id

    try:
        await context.bot.send_photo(
            chat_id=target_user_id,
            photo=photo_file_id,
            caption=TEXTS[target_lang]["receipt_delivered"],
            parse_mode="Markdown",
        )
        await update.message.reply_text(
            f"✅ *Receipt successfully delivered to user (ID: `{target_user_id}`)!*",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to deliver receipt to user: {e}")

    context.user_data.pop("pending_receipt_user", None)
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
    """One-tap 'Get Gmail Task' request: notifies the admin, who then replies from the bot."""
    query = update.callback_query
    user = query.from_user
    lang = get_lang(user.id)
    now = time.time()

    if now - context.user_data.get("last_task_request", 0) < TASK_COOLDOWN:
        await query.answer(TEXTS[lang]["task_already"], show_alert=True)
        return

    await query.answer()
    try:
        text = (
            user_header_html(user, lang, "🆕 <b>GMAIL TASK REQUEST</b>")
            + "\n\nThis user wants a Gmail task. Tap <b>Reply</b> to send the account details."
        )
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=text,
            parse_mode="HTML",
            reply_markup=admin_reply_keyboard(user.id),
        )
    except Exception as e:
        print(f"Failed to send task request to admin: {e}")
        await query.message.reply_text(TEXTS[lang]["contact_failed"].format(support=SUPPORT_USERNAME))
        return

    context.user_data["last_task_request"] = now
    after_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(TEXTS[lang]["btn_submit_ss"], callback_data="start_submit_screenshot")],
        [InlineKeyboardButton(TEXTS[lang]["btn_back"], callback_data="main_menu")],
    ])
    await query.edit_message_text(
        TEXTS[lang]["task_request_sent"],
        parse_mode="Markdown",
        reply_markup=after_keyboard,
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

# --- Telegram "/" command menu ---
async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "Open the main menu"),
        BotCommand("task", "Get a Gmail task"),
        BotCommand("submit", "Submit a screenshot"),
        BotCommand("howitworks", "How it works"),
        BotCommand("payment", "Payment info"),
        BotCommand("requirements", "Requirements & rules"),
        BotCommand("faq", "Frequently asked questions"),
        BotCommand("support", "Contact support"),
        BotCommand("contact", "Message the Admin"),
        BotCommand("language", "Switch language / ቋንቋ ቀይር"),
        BotCommand("cancel", "Cancel the current step"),
    ])

# --- Main Entry Point ---
if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    conversation_fallbacks = [
        CommandHandler("cancel", cancel),
        CommandHandler("start", start_and_end),
    ]

    # FIX: the old pattern was "^start_submit_screenshot\$" which looks for a literal "$"
    # character and never matched, so the Submit Screenshot button did nothing.
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

    receipt_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_receipt_upload, pattern="^adm_receipt_")],
        states={
            WAITING_RECEIPT_PHOTO: [MessageHandler(filters.PHOTO, receive_admin_receipt)],
        },
        fallbacks=conversation_fallbacks,
        allow_reentry=True,
    )

    admin_reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_admin_reply, pattern="^adm_reply_")],
        states={
            WAITING_ADMIN_REPLY: [MessageHandler(~filters.COMMAND, send_admin_reply)],
        },
        fallbacks=conversation_fallbacks,
        allow_reentry=True,
    )

    app.add_handler(screenshot_conv)
    app.add_handler(payment_conv)
    app.add_handler(receipt_conv)
    app.add_handler(admin_reply_conv)

    # Typed commands
    app.add_handler(CommandHandler(["start", "menu", "help"], start))
    app.add_handler(CommandHandler("language", set_language_cmd))
    app.add_handler(CommandHandler(["howitworks", "how"], cmd_how))
    app.add_handler(CommandHandler(["payment", "paymentinfo"], cmd_payment))
    # "requirments" is included because it's a very common typo
    app.add_handler(CommandHandler(["requirements", "requirement", "requirments", "rules"], cmd_requirements))
    app.add_handler(CommandHandler("faq", cmd_faq))
    app.add_handler(CommandHandler(["task", "gettask"], cmd_task))
    app.add_handler(CommandHandler("support", cmd_support))
    app.add_handler(CommandHandler("contact", contact_prompt))
    app.add_handler(CommandHandler("cancel", cancel))

    # Button callbacks
    app.add_handler(CallbackQueryHandler(request_task, pattern="^request_task$"))
    app.add_handler(CallbackQueryHandler(contact_prompt, pattern="^contact_admin$"))
    app.add_handler(CallbackQueryHandler(admin_decision, pattern="^adm_approve_|^adm_reject_"))
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
