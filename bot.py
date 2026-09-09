import os
import sys
import time
import logging
import json
import sqlite3
import random
import string
from datetime import datetime
import requests

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
    
    # Grant admin rights to ADMIN_IDS
    for admin_id in ADMIN_IDS:
        c.execute('''
            INSERT OR REPLACE INTO users (user_id, username, is_admin, verified, joined_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (admin_id, "admin", 1, 1, datetime.now()))
    
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at: {DB_PATH}")
    logger.info(f"Admins: {ADMIN_IDS}")

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
    
    # Check if user is admin
    is_admin = 1 if user_id in ADMIN_IDS else 0
    verified = 1 if is_admin else 0  # Admins are automatically verified
    
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

def get_all_referrals():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT r.id, r.referrer_id, u1.username as referrer, r.referred_id, u2.username as referred, r.timestamp, r.status
        FROM referrals r
        LEFT JOIN users u1 ON r.referrer_id = u1.user_id
        LEFT JOIN users u2 ON r.referred_id = u2.user_id
        ORDER BY r.timestamp DESC
    ''')
    referrals = c.fetchall()
    conn.close()
    return referrals

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

# ============ LENSKART ============
try:
    from lenskart import LenskartFakeDevice
except ImportError:
    logger.warning("Lenskart module not found, using dummy")
    class LenskartFakeDevice:
        def __init__(self, phone, phone_code="+91"):
            self.phone = phone
            self.brand = "test"
            self.model = "test"
            self.udid = "test123"
        def create_session(self):
            return True
        def send_otp(self):
            return {"isNewUser": True}
        def verify_otp(self, code):
            return {"token": "test_token", "user_id": "123"}
        def me(self):
            return {"id": "123"}
        def claim_reward(self, steps=30000):
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

# ============ COMMANDS ============

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.username or str(user_id)
    
    user = get_user(user_id)
    if user and user[8] == 1:
        bot.send_message(user_id, "🚫 You are banned.")
        return
    
    # Parse referral parameter
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
                referrer = get_user(referred_by)
                if referrer:
                    bot.send_message(referred_by, f"🎯 New referral! @{username or 'User'} joined.")
            except:
                pass
        
        log_action(user_id, "start", f"Referred by: {referred_by}, Admin: {is_admin_user}")
    
    # Channel check (skip for admins)
    if not is_admin(user_id) and CHANNEL_ID and not check_channel_membership(user_id):
        markup = InlineKeyboardMarkup()
        channel_username = CHANNEL_ID.replace('-100', '')
        markup.add(InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{channel_username}"))
        markup.add(InlineKeyboardButton("🔄 Check Again", callback_data="check_membership"))
        bot.send_message(
            user_id,
            "🚫 Join our channel to use this bot!",
            reply_markup=markup
        )
        return
    
    show_main_menu(user_id)

def show_main_menu(user_id):
    user = get_user_status(user_id)
    if not user:
        bot.send_message(user_id, "❌ Error. Use /start again.")
        return
    
    referrals = get_referrals(user_id)
    verified = user['verified'] or user['is_admin']  # Admin = verified
    bot_username = get_bot_username()
    link = f"https://t.me/{bot_username}?start={user['referral_code']}"
    
    admin_badge = "👑 Admin" if user['is_admin'] else ""
    
    text = f"""
🎯 **Lenskart Frame Generator**

{admin_badge}
👤 User: @{user['username'] if user['username'] and not user['username'].isdigit() else 'User'}
📱 Phone: {user['phone'] or 'Not set'}
🔑 Code: `{user['referral_code']}`
👥 Referrals: {referrals}
✅ Verified: {'Yes' if verified else 'No'}

{'🔓 Active' if verified else '🔒 Locked - Need 2 referrals'}

🔗 Share: `{link}`
"""
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📋 My Referrals", callback_data="my_referrals"),
        InlineKeyboardButton("🔗 Referral Link", callback_data="get_link")
    )
    if not verified:
        markup.add(InlineKeyboardButton("🔓 Check Status", callback_data="check_status"))
    else:
        markup.add(InlineKeyboardButton("🏃 Start Generation", callback_data="start_gen"))
    if is_admin(user_id):
        markup.add(InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel"))
    
    bot.send_message(user_id, text, reply_markup=markup, parse_mode='Markdown')

# ============ CALLBACKS ============

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    
    # Skip channel check for admins
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
            bot.edit_message_text("✅ Member!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id)
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
        
        text = f"👥 **Your Referrals: {referrals}**\n\n"
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
        text += f"\n🔑 Code: `{user['referral_code']}`"
        text += f"\n🔗 Share: `{link}`"
        text += f"\n📊 Progress: {referrals}/2"
        
        bot.edit_message_text(text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown')
    
    elif data == "get_link":
        user = get_user_status(user_id)
        bot_username = get_bot_username()
        link = f"https://t.me/{bot_username}?start={user['referral_code']}"
        text = f"🔗 **Your Referral Link:**\n`{link}`\n\nShare this link with friends. After 2 join, you unlock!"
        bot.edit_message_text(text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown')
    
    elif data == "check_status":
        user = get_user_status(user_id)
        referrals = get_referrals(user_id)
        
        # Admin bypass
        if user['is_admin']:
            bot.edit_message_text("👑 **Admin Access** - You're already verified!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown')
            show_main_menu(user_id)
            return
        
        if referrals >= 2 and not user['verified']:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('UPDATE users SET verified = 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
            log_action(user_id, "verified", "Unlocked")
            bot.edit_message_text("✅ **UNLOCKED!** Use the bot now.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown')
            show_main_menu(user_id)
        else:
            status = "🔓 Unlocked" if user['verified'] else "🔒 Locked"
            msg = f"📊 Status: {status}\n👥 Referrals: {referrals}/2"
            if referrals < 2:
                msg += f"\n\nShare your referral link to get more!"
            bot.edit_message_text(msg,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id)
    
    elif data == "start_gen":
        user = get_user_status(user_id)
        if not user['verified'] and not user['is_admin']:
            bot.answer_callback_query(call.id, "❌ Need 2 referrals!")
            return
        start_generation_flow(user_id)
    
    elif data == "admin_panel":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "⛔ Admin only!")
            return
        show_admin_panel(call.message, user_id)
    
    elif data == "back_to_menu":
        show_main_menu(user_id)
    
    # Admin panel callbacks
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
            bot.send_message(user_id, "❌ Session failed.")
            show_main_menu(user_id)
            return
        
        bot.send_message(user_id, "📨 Sending OTP...")
        if not device.send_otp():
            bot.send_message(user_id, "❌ OTP send failed.")
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
    if not device.verify_otp(otp):
        bot.send_message(user_id, "❌ Wrong OTP. Try again.")
        otp_sessions.pop(user_id, None)
        show_main_menu(user_id)
        return
    
    bot.send_message(user_id, "🔄 Getting profile...")
    device.me()
    
    bot.send_message(user_id, "🏃 Claiming reward...")
    reward = device.claim_reward(steps=30000)
    
    if reward and reward.get('giftVoucher'):
        bot.send_message(
            user_id,
            f"🎉 **SUCCESS!**\n\n"
            f"🏆 Tier: {reward.get('tier')}\n"
            f"🎫 Voucher: {reward.get('giftVoucher')}\n"
            f"📊 Steps: {reward.get('steps')}\n"
            f"📱 Device: {device.brand} {device.model}",
            parse_mode='Markdown'
        )
        log_action(user_id, "reward_claimed", f"Voucher: {reward.get('giftVoucher')}")
    else:
        msg = reward.get('message', 'No reward') if reward else 'Failed'
        bot.send_message(user_id, f"⚠️ {msg}")
        log_action(user_id, "reward_failed", msg)
    
    otp_sessions.pop(user_id, None)
    show_main_menu(user_id)

# ============ ADMIN PANEL ============

def show_admin_panel(message, admin_id):
    stats = get_statistics()
    text = f"""
⚙️ **Admin Panel**

📊 **Statistics:**
• Total Users: {stats['total']}
• Verified Users: {stats['verified']}
• Total Referrals: {stats['referrals']}
• Admins: {stats['admins']}

📌 **Admin Commands:**
• /users - List all users
• /referrals - View all referrals
• /logs - View recent logs
• /stats - View statistics
• /broadcast <msg> - Send broadcast
• /ban <user_id> - Ban user
• /unban <user_id> - Unban user
• /delete <user_id> - Delete user
• /export - Export all data
"""
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📋 Users", callback_data="admin_users"),
        InlineKeyboardButton("🔗 Referrals", callback_data="admin_referrals"),
        InlineKeyboardButton("📜 Logs", callback_data="admin_logs"),
        InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
        InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
        InlineKeyboardButton("🚫 Ban", callback_data="admin_ban"),
        InlineKeyboardButton("🔓 Unban", callback_data="admin_unban"),
        InlineKeyboardButton("🗑️ Delete", callback_data="admin_delete"),
        InlineKeyboardButton("📊 Export", callback_data="admin_export"),
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
    
    elif action == "referrals":
        refs = get_all_referrals()
        text = "🔗 **All Referrals:**\n\n"
        if refs:
            for r in refs[:30]:
                text += f"ID: {r[1]} → {r[3]} | {r[5][:16]}\n"
            if len(refs) > 30:
                text += f"\n... and {len(refs)-30} more"
        else:
            text += "No referrals yet."
        bot.edit_message_text(text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id)
    
    elif action == "logs":
        logs = get_logs(30)
        text = "📜 **Recent Logs:**\n\n"
        for log in logs:
            text += f"{log[4][:16]} | {log[1]} | {log[2][:30]}\n"
        bot.edit_message_text(text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id)
    
    elif action == "stats":
        stats = get_statistics()
        text = f"""
📊 **Detailed Statistics:**

👥 Total Users: {stats['total']}
✅ Verified Users: {stats['verified']}
🔗 Total Referrals: {stats['referrals']}
👑 Admins: {stats['admins']}
📱 Pending OTPs: {len(otp_sessions)}

📈 **Referral Progress:**
• Average referrals per user: {stats['referrals'] / max(stats['total'], 1):.2f}
• Verification rate: {(stats['verified'] / max(stats['total'], 1) * 100):.1f}%
"""
        bot.edit_message_text(text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown')
    
    elif action == "broadcast":
        bot.send_message(user_id, "📢 Enter broadcast message:")
        bot.register_next_step_handler(call.message, process_broadcast)
        bot.answer_callback_query(call.id)
    
    elif action == "ban":
        bot.send_message(user_id, "🚫 Enter user ID to ban:")
        bot.register_next_step_handler(call.message, process_ban_user)
        bot.answer_callback_query(call.id)
    
    elif action == "unban":
        bot.send_message(user_id, "🔓 Enter user ID to unban:")
        bot.register_next_step_handler(call.message, process_unban_user)
        bot.answer_callback_query(call.id)
    
    elif action == "delete":
        bot.send_message(user_id, "🗑️ Enter user ID to delete:")
        bot.register_next_step_handler(call.message, process_delete_user)
        bot.answer_callback_query(call.id)
    
    elif action == "export":
        data = {
            'users': get_all_users(),
            'referrals': get_all_referrals(),
            'stats': get_statistics(),
            'logs': get_logs(100),
            'exported_at': datetime.now().isoformat()
        }
        with open('export_data.json', 'w') as f:
            json.dump(data, f, default=str, indent=2)
        bot.send_message(user_id, "📊 Data exported to `export_data.json`", parse_mode='Markdown')
        bot.answer_callback_query(call.id)
    
    elif action == "reset":
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("⚠️ CONFIRM RESET", callback_data="admin_confirm_reset"),
            InlineKeyboardButton("❌ Cancel", callback_data="back_to_menu")
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

# ============ ADMIN COMMAND HANDLERS ============

@bot.message_handler(commands=['users'])
def cmd_users(message):
    if not is_admin(message.from_user.id):
        return
    users = get_all_users()
    text = "📋 Users:\n\n"
    for u in users[:20]:
        text += f"ID: {u[0]} | @{u[1] or 'N/A'} | {'👑' if u[5] else ''}\n"
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['referrals'])
def cmd_referrals(message):
    if not is_admin(message.from_user.id):
        return
    refs = get_all_referrals()
    text = "🔗 All Referrals:\n\n"
    for r in refs[:20]:
        text += f"{r[1]} → {r[3]} | {r[5][:16]}\n"
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['logs'])
def cmd_logs(message):
    if not is_admin(message.from_user.id):
        return
    logs = get_logs(20)
    text = "📜 Logs:\n\n"
    for log in logs:
        text += f"{log[4][:16]} | {log[1]} | {log[2]}\n"
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    if not is_admin(message.from_user.id):
        return
    stats = get_statistics()
    text = f"📊 Users: {stats['total']}\n✅ Verified: {stats['verified']}\n🔗 Referrals: {stats['referrals']}"
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    if not is_admin(message.from_user.id):
        return
    msg = message.text.replace('/broadcast', '').strip()
    if not msg:
        bot.send_message(message.chat.id, "Usage: /broadcast <message>")
        return
    users = get_all_users()
    sent = 0
    for u in users:
        try:
            bot.send_message(u[0], f"📢 {msg}")
            sent += 1
            time.sleep(0.05)
        except:
            pass
    bot.send_message(message.chat.id, f"✅ Sent to {sent} users.")

@bot.message_handler(commands=['ban'])
def cmd_ban(message):
    if not is_admin(message.from_user.id):
        return
    try:
        user_id = int(message.text.replace('/ban', '').strip())
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        log_action(message.from_user.id, "banned", f"User {user_id}")
        bot.send_message(message.chat.id, f"✅ User {user_id} banned.")
    except:
        bot.send_message(message.chat.id, "❌ Usage: /ban <user_id>")

@bot.message_handler(commands=['unban'])
def cmd_unban(message):
    if not is_admin(message.from_user.id):
        return
    try:
        user_id = int(message.text.replace('/unban', '').strip())
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        log_action(message.from_user.id, "unbanned", f"User {user_id}")
        bot.send_message(message.chat.id, f"✅ User {user_id} unbanned.")
    except:
        bot.send_message(message.chat.id, "❌ Usage: /unban <user_id>")

@bot.message_handler(commands=['delete'])
def cmd_delete(message):
    if not is_admin(message.from_user.id):
        return
    try:
        user_id = int(message.text.replace('/delete', '').strip())
        delete_user(user_id)
        log_action(message.from_user.id, "deleted", f"User {user_id}")
        bot.send_message(message.chat.id, f"✅ User {user_id} deleted.")
    except:
        bot.send_message(message.chat.id, "❌ Usage: /delete <user_id>")

@bot.message_handler(commands=['export'])
def cmd_export(message):
    if not is_admin(message.from_user.id):
        return
    data = {
        'users': get_all_users(),
        'referrals': get_all_referrals(),
        'stats': get_statistics(),
        'logs': get_logs(100)
    }
    with open('export_data.json', 'w') as f:
        json.dump(data, f, default=str, indent=2)
    bot.send_message(message.chat.id, "📊 Data exported to `export_data.json`",
