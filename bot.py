import os
import sys
import time
import logging
import sqlite3
import random
import string
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import Telegram
try:
    import telebot
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    logger.error("Telegram module not installed!")
    sys.exit(1)

# ============ CONFIG ============
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]
RENDER_URL = os.getenv("RENDER_URL", "https://your-app.onrender.com")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN not set!")
    sys.exit(1)

# ============ DATABASE ============
DB_PATH = "/data/bot_data.db"
if not os.path.exists("/data"):
    os.makedirs("/data", exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            phone TEXT,
            referral_code TEXT UNIQUE,
            referred_by INTEGER,
            referal_count INTEGER DEFAULT 0,
            joined_date TIMESTAMP,
            is_admin INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            timestamp TIMESTAMP,
            status TEXT DEFAULT 'pending'
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            timestamp TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('referral_required', '2'))
    
    for admin_id in ADMIN_IDS:
        c.execute('''
            INSERT OR REPLACE INTO users (user_id, username, is_admin, verified, joined_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (admin_id, "admin", 1, 1, datetime.now()))
    
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at: {DB_PATH}")

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def add_user(user_id, username, referral_code, referred_by=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    is_admin = 1 if user_id in ADMIN_IDS else 0
    verified = 1 if is_admin else 0
    c.execute('''
        INSERT OR IGNORE INTO users (user_id, username, referral_code, referred_by, joined_date, is_admin, verified)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, username, referral_code, referred_by, datetime.now(), is_admin, verified))
    conn.commit()
    conn.close()
    return is_admin

def update_user_phone(user_id, phone):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET phone = ? WHERE user_id = ?', (phone, user_id))
    conn.commit()
    conn.close()

def increment_referrals(referrer_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET referal_count = referal_count + 1 WHERE user_id = ?', (referrer_id,))
    conn.commit()
    conn.close()

def add_referral(referrer_id, referred_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO referrals (referrer_id, referred_id, timestamp, status)
        VALUES (?, ?, ?, ?)
    ''', (referrer_id, referred_id, datetime.now(), 'completed'))
    conn.commit()
    conn.close()

def get_referrals(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT user_id, username, phone, referal_count, verified, is_admin, is_banned FROM users ORDER BY joined_date DESC')
    users = c.fetchall()
    conn.close()
    return users

def log_action(user_id, action, details=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO logs (user_id, action, details, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (user_id, action, details, datetime.now()))
    conn.commit()
    conn.close()

def get_logs(limit=50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?', (limit,))
    logs = c.fetchall()
    conn.close()
    return logs

def get_statistics():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    total = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    verified = c.execute('SELECT COUNT(*) FROM users WHERE verified = 1').fetchone()[0]
    total_refs = c.execute('SELECT SUM(referal_count) FROM users').fetchone()[0] or 0
    admins = c.execute('SELECT COUNT(*) FROM users WHERE is_admin = 1').fetchone()[0]
    conn.close()
    return {'total': total, 'verified': verified, 'referrals': total_refs, 'admins': admins}

def delete_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM referrals WHERE referrer_id = ? OR referred_id = ?', (user_id, user_id))
    conn.commit()
    conn.close()

def get_referral_requirement():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key = ?', ('referral_required',))
    result = c.fetchone()
    conn.close()
    if result:
        return int(result[0])
    return 2

def set_referral_requirement(value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ('referral_required', str(value)))
    conn.commit()
    conn.close()

def ban_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def verify_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET verified = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def unverify_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET verified = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# ============ LENSKART ============
# Import the original script directly
try:
    from lenskart import LenskartFakeDevice
    logger.info("Lenskart module imported successfully!")
except ImportError as e:
    logger.error(f"Lenskart module not found: {e}")
    # Fallback dummy class
    class LenskartFakeDevice:
        def __init__(self, phone, phone_code="+91"):
            self.phone = phone
            self.brand = "test"
            self.model = "test"
            self.udid = "test123"
            self.user_id = None
        def create_session(self):
            return True
        def send_otp(self):
            return {"isNewUser": True}
        def verify_otp(self, code):
            self.user_id = "123"
            return {"token": "test_token", "user_id": "123"}
        def me(self):
            return {"id": "123"}
        def claim_reward(self, steps=30000):
            # Return the same format as the original script
            return {"giftVoucher": "TEST-123", "tier": "Gold", "steps": 30000}

# ============ BOT ============
bot = telebot.TeleBot(BOT_TOKEN)
otp_sessions = {}

def generate_referral_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def is_admin(user_id):
    return user_id in ADMIN_IDS

def check_channel_membership(user_id):
    if not CHANNEL_ID:
        return True
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

def get_user_status(user_id):
    user = get_user(user_id)
    if not user:
        return None
    return {
        'user_id': user[0],
        'username': user[1],
        'phone': user[2],
        'referral_code': user[3],
        'referred_by': user[4],
        'referal_count': user[5],
        'joined_date': user[6],
        'is_admin': bool(user[7]),
        'is_banned': bool(user[8]),
        'verified': bool(user[9])
    }

def get_bot_username():
    try:
        return bot.get_me().username
    except:
        return "lenskartremixbot"

def is_user_eligible(user_id):
    user = get_user_status(user_id)
    if not user:
        return False
    if user['is_admin']:
        return True
    if user['is_banned']:
        return False
    req = get_referral_requirement()
    if req == 0:
        return True
    referrals = get_referrals(user_id)
    return referrals >= req

# ============ COMMANDS ============

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.username or str(user_id)
    
    user = get_user(user_id)
    if user and user[8] == 1:
        bot.send_message(user_id, "🚫 You are banned.")
        return
    
    ref_code = None
    if len(message.text.split()) > 1:
        ref_code = message.text.split()[1]
    
    if not user:
        referred_by = None
        if ref_code:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('SELECT user_id FROM users WHERE referral_code = ?', (ref_code,))
            result = c.fetchone()
            conn.close()
            if result:
                referred_by = result[0]
        
        is_admin_user = add_user(user_id, username, generate_referral_code(), referred_by)
        
        if referred_by and not is_admin_user:
            add_referral(referred_by, user_id)
            increment_referrals(referred_by)
            try:
                bot.send_message(referred_by, f"🎯 New referral! @{username or 'User'} joined.")
            except:
                pass
        
        log_action(user_id, "start", f"Referred by: {referred_by}")
    
    if not is_admin(user_id) and CHANNEL_ID and not check_channel_membership(user_id):
        markup = InlineKeyboardMarkup()
        channel_username = CHANNEL_ID.replace('-100', '')
        markup.add(InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{channel_username}"))
        markup.add(InlineKeyboardButton("🔄 Check Again", callback_data="check_membership"))
        bot.send_message(user_id, "🚫 Join our channel to use this bot!", reply_markup=markup)
        return
    
    show_main_menu(user_id)

def show_main_menu(user_id):
    user = get_user_status(user_id)
    if not user:
        bot.send_message(user_id, "❌ Error. Use /start again.")
        return
    
    referrals = get_referrals(user_id)
    req = get_referral_requirement()
    eligible = is_user_eligible(user_id)
    bot_username = get_bot_username()
    link = f"https://t.me/{bot_username}?start={user['referral_code']}"
    
    admin_badge = "👑 Admin" if user['is_admin'] else ""
    
    if user['is_admin']:
        status_text = "👑 **Admin Access** - Full Control"
    elif req == 0:
        status_text = "🟢 **Referral System OFF** - Everyone Has Access"
    elif eligible:
        status_text = "✅ **Access Granted**"
    else:
        status_text = f"🔒 **Locked** - Need {req} referrals (You have {referrals})"
    
    text = f"""
🎯 **Lenskart Frame Generator**

{admin_badge}
👤 User: @{user['username'] if user['username'] and not user['username'].isdigit() else 'User'}
📱 Phone: {user['phone'] or 'Not set'}
🔑 Code: `{user['referral_code']}`
👥 Referrals: {referrals}
📊 Required: {req if req > 0 else 'OFF'}

{status_text}

🔗 Share: `{link}`
"""
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📋 My Referrals", callback_data="my_referrals"),
        InlineKeyboardButton("🔗 Referral Link", callback_data="get_link")
    )
    
    if eligible:
        markup.add(InlineKeyboardButton("🏃 Start Generation", callback_data="start_gen"))
    else:
        markup.add(InlineKeyboardButton("🔓 Check Status", callback_data="check_status"))
    
    if is_admin(user_id):
        markup.add(InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel"))
    
    bot.send_message(user_id, text, reply_markup=markup, parse_mode='Markdown')

# ============ CALLBACKS ============

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    
    if not is_admin(user_id) and data != "check_membership" and CHANNEL_ID and not check_channel_membership(user_id):
        markup = InlineKeyboardMarkup()
        channel_username = CHANNEL_ID.replace('-100', '')
        markup.add(InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{channel_username}"))
        markup.add(InlineKeyboardButton("🔄 Check Again", callback_data="check_membership"))
        bot.edit_message_text(
            "🚫 Join channel first!",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup
        )
        return
    
    if data == "check_membership":
        if check_channel_membership(user_id):
            bot.edit_message_text("✅ Member!", chat_id=call.message.chat.id, message_id=call.message.message_id)
            show_main_menu(user_id)
        else:
            bot.answer_callback_query(call.id, "❌ Not a member!")
    
    elif data == "my_referrals":
        referrals = get_referrals(user_id)
        user = get_user_status(user_id)
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT u.user_id, u.username, r.timestamp 
            FROM referrals r
            JOIN users u ON r.referred_id = u.user_id
            WHERE r.referrer_id = ?
            ORDER BY r.timestamp DESC
        ''', (user_id,))
        ref_list = c.fetchall()
        conn.close()
        
        req = get_referral_requirement()
        text = f"👥 **Your Referrals: {referrals}**\n"
        text += f"📊 Required: {req if req > 0 else 'OFF'}\n\n"
        
        if ref_list:
            for i, (ref_user_id, ref_username, ts) in enumerate(ref_list, 1):
                display_name = ""
                if ref_username and not ref_username.isdigit():
                    display_name = f"@{ref_username}"
                else:
                    try:
                        chat = bot.get_chat(ref_user_id)
                        if chat.username:
                            display_name = f"@{chat.username}"
                        elif chat.first_name:
                            display_name = chat.first_name
                        else:
                            display_name = f"User {ref_user_id}"
                    except:
                        display_name = f"User {ref_user_id}"
                text += f"{i}. {display_name} - {ts[:16]}\n"
        else:
            text += "No referrals yet. Share your link!\n"
        
        bot_username = get_bot_username()
        link = f"https://t.me/{bot_username}?start={user['referral_code']}"
        text += f"\n🔗 Share: `{link}`"
        
        bot.edit_message_text(text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown')
    
    elif data == "get_link":
        user = get_user_status(user_id)
        bot_username = get_bot_username()
        link = f"https://t.me/{bot_username}?start={user['referral_code']}"
        req = get_referral_requirement()
        text = f"🔗 **Your Referral Link:**\n`{link}`\n\n"
        if req > 0:
            text += f"Share with friends! Need {req} referrals to unlock."
        else:
            text += "Referral system is OFF. Everyone has access!"
        bot.edit_message_text(text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown')
    
    elif data == "check_status":
        user = get_user_status(user_id)
        referrals = get_referrals(user_id)
        req = get_referral_requirement()
        
        if user['is_admin']:
            bot.edit_message_text("👑 **Admin** - Full access!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown')
            show_main_menu(user_id)
            return
        
        if req == 0:
            bot.edit_message_text("🟢 **Referral System OFF**\nEveryone has access!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id)
            verify_user(user_id)
            show_main_menu(user_id)
            return
        
        if referrals >= req:
            if not user['verified']:
                verify_user(user_id)
                log_action(user_id, "verified", f"Auto-verified with {referrals} referrals")
            bot.edit_message_text("✅ **ACCESS GRANTED!**",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown')
            show_main_menu(user_id)
        else:
            text = f"📊 **Status:** 🔒 Locked\n"
            text += f"👥 Referrals: {referrals}/{req}\n\n"
            text += f"Share your referral link to get {req} referrals!"
            bot.edit_message_text(text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id)
    
    elif data == "start_gen":
        if not is_user_eligible(user_id):
            bot.answer_callback_query(call.id, "❌ Not eligible! Check status.")
            return
        start_generation_flow(user_id)
    
    elif data == "admin_panel":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "⛔ Admin only!")
            return
        show_admin_panel(call.message, user_id)
    
    elif data == "back_to_menu":
        show_main_menu(user_id)
    
    elif data.startswith("admin_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "⛔ Admin only!")
            return
        handle_admin_actions(call)

# ============ GENERATION FLOW ============

def start_generation_flow(user_id):
    msg = bot.send_message(
        user_id,
        "📱 **Enter phone number**\nExample: `919876543210`\nType /cancel to cancel.",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_phone_input)

def process_phone_input(message):
    user_id = message.from_user.id
    
    if message.text == "/cancel":
        bot.send_message(user_id, "❌ Cancelled.")
        show_main_menu(user_id)
        return
    
    phone = message.text.strip()
    if not phone.isdigit() or len(phone) < 10:
        bot.send_message(user_id, "❌ Invalid. Try again or /cancel.")
        start_generation_flow(user_id)
        return
    
    update_user_phone(user_id, phone)
    log_action(user_id, "phone_set", phone)
    
    try:
        device = LenskartFakeDevice(phone)
        
        bot.send_message(user_id, "🔄 Creating session...")
        if not device.create_session():
            bot.send_message(user_id, "❌ Session creation failed.")
            show_main_menu(user_id)
            return
        
        bot.send_message(user_id, "📨 Sending OTP...")
        otp_result = device.send_otp()
        if not otp_result:
            bot.send_message(user_id, "❌ OTP send failed. Check phone number.")
            show_main_menu(user_id)
            return
        
        otp_sessions[user_id] = device
        
        msg = bot.send_message(user_id, f"✅ OTP sent to {phone}\nEnter 4-digit OTP:")
        bot.register_next_step_handler(msg, process_otp_input)
        
    except Exception as e:
        logger.error(f"Generation error: {e}")
        bot.send_message(user_id, f"❌ Error: {str(e)}")
        show_main_menu(user_id)

def process_otp_input(message):
    user_id = message.from_user.id
    otp = message.text.strip()
    
    if otp == "/cancel":
        bot.send_message(user_id, "❌ Cancelled.")
        otp_sessions.pop(user_id, None)
        show_main_menu(user_id)
        return
    
    if not otp.isdigit() or len(otp) != 4:
        bot.send_message(user_id, "❌ 4 digits only. Try again.")
        return
    
    device = otp_sessions.get(user_id)
    if not device:
        bot.send_message(user_id, "❌ Session expired. Start again.")
        show_main_menu(user_id)
        return
    
    bot.send_message(user_id, "🔄 Verifying OTP...")
    verify_result = device.verify_otp(otp)
    if not verify_result:
        bot.send_message(user_id, "❌ Wrong OTP. Try again.")
        otp_sessions.pop(user_id, None)
        show_main_menu(user_id)
        return
    
    bot.send_message(user_id, "🔄 Getting profile...")
    device.me()
    
    bot.send_message(user_id, "🏃 Claiming reward with 30,000 steps...")
    reward = device.claim_reward(steps=30000)
    
    # Check if reward was successful (matches original script's return format)
    if reward and reward.get('giftVoucher'):
        voucher = reward.get('giftVoucher')
        tier = reward.get('tier', 'N/A')
        steps = reward.get('steps', 30000)
        
        bot.send_message(
            user_id,
            f"🎉 **REWARD CLAIMED!**\n\n"
            f"🏆 Tier: {tier}\n"
            f"🎫 Voucher: `{voucher}`\n"
            f"📊 Steps: {steps}\n"
            f"📱 Device: {device.brand} {device.model}\n\n"
            f"✅ Reward saved to reward_{device.phone}.json",
            parse_mode='Markdown'
        )
        log_action(user_id, "reward_claimed", f"Voucher: {voucher}")
    else:
        # Check if reward returned a message
        if reward and reward.get('message'):
            error_msg = reward.get('message')
        else:
            error_msg = "No reward available or already claimed"
        
        bot.send_message(
            user_id,
            f"⚠️ **Reward Claim Failed**\n\n"
            f"Reason: {error_msg}\n\n"
            f"📱 Device: {device.brand} {device.model}\n"
            f"🆔 UDID: {device.udid[:8]}...\n\n"
            f"Try again with a different phone number.",
            parse_mode='Markdown'
        )
        log_action(user_id, "reward_failed", error_msg)
    
    otp_sessions.pop(user_id, None)
    show_main_menu(user_id)

# ============ ADMIN PANEL ============

def show_admin_panel(message, admin_id):
    stats = get_statistics()
    req = get_referral_requirement()
    req_status = "OFF" if req == 0 else str(req)
    
    text = f"""
⚙️ **Admin Panel**

📊 **Statistics:**
• Total Users: {stats['total']}
• Verified Users: {stats['verified']}
• Total Referrals: {stats['referrals']}
• Admins: {stats['admins']}

🔧 **Referral Requirement:** {req_status}

📌 **Admin Controls:**
• Set referral requirement (1, 2, 3, or 0 to OFF)
• View all users
• View logs
• Ban/Unban users
• Manually verify/unverify users
• Broadcast messages
• Reset all data
"""
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎯 Set Referral Req", callback_data="admin_set_req"),
        InlineKeyboardButton("📋 Users", callback_data="admin_users"),
        InlineKeyboardButton("📜 Logs", callback_data="admin_logs"),
        InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"),
        InlineKeyboardButton("🔓 Unban User", callback_data="admin_unban"),
        InlineKeyboardButton("✅ Verify User", callback_data="admin_verify"),
        InlineKeyboardButton("❌ Unverify User", callback_data="admin_unverify"),
        InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
        InlineKeyboardButton("🔄 Reset All", callback_data="admin_reset")
    )
    markup.add(InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu"))
    
    if isinstance(message, telebot.types.Message):
        bot.send_message(admin_id, text, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.edit_message_text(text,
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=markup,
            parse_mode='Markdown')

def handle_admin_actions(call):
    user_id = call.from_user.id
    action = call.data.replace("admin_", "")
    
    if action == "users":
        users = get_all_users()
        text = "📋 **All Users:**\n\n"
        for u in users[:30]:
            display_name = f"@{u[1]}" if u[1] and not u[1].isdigit() else f"ID: {u[0]}"
            admin_tag = " 👑" if u[5] else ""
            banned_tag = " 🚫" if u[6] else ""
            text += f"{display_name}{admin_tag}{banned_tag} | Ref: {u[3]} | {'✅' if u[4] else '❌'}\n"
        if len(users) > 30:
            text += f"\n... and {len(users)-30} more"
        bot.edit_message_text(text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown')
    
    elif action == "logs":
        logs = get_logs(30)
        text = "📜 **Recent Logs:**\n\n"
        for log in logs:
            text += f"{log[4][:16]} | {log[1]} | {log[2][:30]}\n"
        bot.edit_message_text(text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id)
    
    elif action == "set_req":
        markup = InlineKeyboardMarkup(row_width=4)
        markup.add(
            InlineKeyboardButton("0 (OFF)", callback_data="admin_setreq_0"),
            InlineKeyboardButton("1", callback_data="admin_setreq_1"),
            InlineKeyboardButton("2", callback_data="admin_setreq_2"),
            InlineKeyboardButton("3", callback_data="admin_setreq_3")
        )
        markup.add(InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
        bot.edit_message_text(
            "🎯 **Set Referral Requirement**\n\n"
            "Select how many referrals needed to access:\n"
            "• 0 = OFF (everyone gets access)\n"
            "• 1 = Need 1 referral\n"
            "• 2 = Need 2 referrals\n"
            "• 3 = Need 3 referrals",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup,
            parse_mode='Markdown'
        )
        bot.answer_callback_query(call.id)
    
    elif action.startswith("setreq_"):
        value = int(action.replace("setreq_", ""))
        set_referral_requirement(value)
        log_action(user_id, "set_referral_req", f"Set to {value}")
        
        text = f"✅ Referral requirement set to {value}."
        if value == 0:
            text += " Referral system is OFF. Everyone has access!"
        else:
            text += f" Users need {value} referral(s) to access."
        
        bot.edit_message_text(text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id)
        show_admin_panel(call.message, user_id)
        bot.answer_callback_query(call.id)
    
    elif action == "ban":
        bot.send_message(user_id, "🚫 Enter user ID to ban:")
        bot.register_next_step_handler(call.message, process_ban_user)
        bot.answer_callback_query(call.id)
    
    elif action == "unban":
        bot.send_message(user_id, "🔓 Enter user ID to unban:")
        bot.register_next_step_handler(call.message, process_unban_user)
        bot.answer_callback_query(call.id)
    
    elif action == "verify":
        bot.send_message(user_id, "✅ Enter user ID to verify:")
        bot.register_next_step_handler(call.message, process_verify_user)
        bot.answer_callback_query(call.id)
    
    elif action == "unverify":
        bot.send_message(user_id, "❌ Enter user ID to unverify:")
        bot.register_next_step_handler(call.message, process_unverify_user)
        bot.answer_callback_query(call.id)
    
    elif action == "broadcast":
        bot.send_message(user_id, "📢 Enter broadcast message:")
        bot.register_next_step_handler(call.message, process_broadcast)
        bot.answer_callback_query(call.id)
    
    elif action == "reset":
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("⚠️ CONFIRM RESET", callback_data="admin_confirm_reset"),
            InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")
        )
        bot.edit_message_text(
            "⚠️ **WARNING: This will DELETE ALL DATA!**\n"
            "This action cannot be undone.\n\n"
            "Click CONFIRM RESET to proceed.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup,
            parse_mode='Markdown'
        )
    
    elif action == "confirm_reset":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('DELETE FROM users WHERE is_admin = 0')
        c.execute('DELETE FROM referrals')
        c.execute('DELETE FROM logs')
        conn.commit()
        conn.close()
        log_action(user_id, "reset", "All data reset")
        bot.edit_message_text("🔄 **All data has been reset!**",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown')
        show_admin_panel(call.message, user_id)

# ============ ADMIN HELPER FUNCTIONS ============

def process_ban_user(message):
    admin_id = message.from_user.id
    try:
        user_id = int(message.text.strip())
        ban_user(user_id)
        log_action(admin_id, "banned", f"User {user_id}")
        bot.send_message(admin_id, f"✅ User {user_id} banned.")
    except:
        bot.send_message(admin_id, "❌ Invalid user ID.")

def process_unban_user(message):
    admin_id = message.from_user.id
    try:
        user_id = int(message.text.strip())
        unban_user(user_id)
        log_action(admin_id, "unbanned", f"User {user_id}")
        bot.send_message(admin_id, f"✅ User {user_id} unbanned.")
    except:
        bot.send_message(admin_id, "❌ Invalid user ID.")

def process_verify_user(message):
    admin_id = message.from_user.id
    try:
        user_id = int(message.text.strip())
        verify_user(user_id)
        log_action(admin_id, "verified", f"Manually verified {user_id}")
        bot.send_message(admin_id, f"✅ User {user_id} verified.")
    except:
        bot.send_message(admin_id, "❌ Invalid user ID.")

def process_unverify_user(message):
    admin_id = message.from_user.id
    try:
        user_id = int(message.text.strip())
        unverify_user(user_id)
        log_action(admin_id, "unverified", f"Manually unverified {user_id}")
        bot.send_message(admin_id, f"❌ User {user_id} unverified.")
    except:
        bot.send_message(admin_id, "❌ Invalid user ID.")

def process_broadcast(message):
    admin_id = message.from_user.id
    broadcast_text = message.text
    
    users = get_all_users()
    sent = 0
    for user in users:
        try:
            bot.send_message(user[0], f"📢 {broadcast_text}")
            sent += 1
