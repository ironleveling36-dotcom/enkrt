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
    
    conn.commit()
    conn.close()
    logger.info("Database initialized at: " + DB_PATH)

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
    c.execute('''
        INSERT OR IGNORE INTO users (user_id, username, referral_code, referred_by, joined_date)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username, referral_code, referred_by, datetime.now()))
    conn.commit()
    conn.close()

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
    c.execute('SELECT user_id, username, phone, referal_count, verified FROM users ORDER BY joined_date DESC')
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
    conn.close()
    return {'total': total, 'verified': verified, 'referrals': total_refs}

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
        'is_admin': user[7],
        'is_banned': user[8],
        'verified': user[9]
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
        
        add_user(user_id, username, generate_referral_code(), referred_by)
        
        if referred_by:
            add_referral(referred_by, user_id)
            increment_referrals(referred_by)
            try:
                # Get referrer's username for notification
                referrer = get_user(referred_by)
                if referrer:
                    bot.send_message(referred_by, f"🎯 New referral! @{username or 'User'} joined using your link.")
            except:
                pass
        
        log_action(user_id, "start", f"Referred by: {referred_by}")
    
    if CHANNEL_ID and not check_channel_membership(user_id):
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
    verified = user['verified']
    bot_username = get_bot_username()
    link = f"https://t.me/{bot_username}?start={user['referral_code']}"
    
    text = f"""
🎯 **Lenskart Frame Generator**

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
        markup.add(InlineKeyboardButton("⚙️ Admin", callback_data="admin_panel"))
    
    bot.send_message(user_id, text, reply_markup=markup, parse_mode='Markdown')

# ============ CALLBACKS ============

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    
    if data != "check_membership" and CHANNEL_ID and not check_channel_membership(user_id):
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
                # Try to get the actual username from Telegram if stored username is numeric
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
        if not user['verified']:
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

# ============ ADMIN ============

def show_admin_panel(message, admin_id):
    stats = get_statistics()
    text = f"""
⚙️ **Admin Panel**

📊 Users: {stats['total']}
✅ Verified: {stats['verified']}
🔗 Referrals: {stats['referrals']}
"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📋 Users", callback_data="admin_list_users"),
        InlineKeyboardButton("📜 Logs", callback_data="admin_view_logs"),
        InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
        InlineKeyboardButton("🚫 Ban", callback_data="admin_ban"),
        InlineKeyboardButton("🔓 Unban", callback_data="admin_unban"),
        InlineKeyboardButton("📊 Export", callback_data="admin_export")
    )
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_menu"))
    
    if isinstance(message, telebot.types.Message):
        bot.send_message(admin_id, text, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.edit_message_text(text,
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=markup,
            parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callback(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔ Admin only!")
        return
    
    action = call.data.replace("admin_", "")
    
    if action == "list_users":
        users = get_all_users()
        text = "📋 **Users:**\n\n"
        for u in users[:20]:
            display_name = f"@{u[1]}" if u[1] and not u[1].isdigit() else f"ID: {u[0]}"
            text += f"{display_name} | Ref: {u[3]} | {'✅' if u[4] else '❌'}\n"
        if len(users) > 20:
            text += f"\n... and {len(users)-20} more"
        bot.edit_message_text(text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown')
    
    elif action == "view_logs":
        logs = get_logs(20)
        text = "📜 **Recent Logs:**\n\n"
        for log in logs:
            text += f"{log[4][:16]} | {log[1]} | {log[2]}\n"
        bot.edit_message_text(text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id)
    
    elif action == "broadcast":
        bot.send_message(user_id, "📢 Enter message:")
        bot.register_next_step_handler(call.message, process_broadcast)
        bot.answer_callback_query(call.id)
    
    elif action == "ban":
        bot.send_message(user_id, "🚫 Enter user ID:")
        bot.register_next_step_handler(call.message, process_ban_user)
        bot.answer_callback_query(call.id)
    
    elif action == "unban":
        bot.send_message(user_id, "🔓 Enter user ID:")
        bot.register_next_step_handler(call.message, process_unban_user)
        bot.answer_callback_query(call.id)
    
    elif action == "export":
        data = {
            'users': get_all_users(),
            'stats': get_statistics(),
            'logs': get_logs(100)
        }
        with open('export_data.json', 'w') as f:
            json.dump(data, f, default=str, indent=2)
        bot.send_message(user_id, "📊 Exported to `export_data.json`", parse_mode='Markdown')

def process_broadcast(message):
    admin_id = message.from_user.id
    text = message.text
    
    users = get_all_users()
    sent = 0
    for user in users:
        try:
            bot.send_message(user[0], f"📢 {text}")
            sent += 1
            time.sleep(0.05)
        except:
            pass
    
    bot.send_message(admin_id, f"✅ Sent to {sent} users.")
    log_action(admin_id, "broadcast", f"Sent to {sent}")

def process_ban_user(message):
    admin_id = message.from_user.id
    try:
        user_id = int(message.text.strip())
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        log_action(admin_id, "banned", f"User {user_id}")
        bot.send_message(admin_id, f"✅ User {user_id} banned.")
    except:
        bot.send_message(admin_id, "❌ Invalid ID.")

def process_unban_user(message):
    admin_id = message.from_user.id
    try:
        user_id = int(message.text.strip())
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        log_action(admin_id, "unbanned", f"User {user_id}")
        bot.send_message(admin_id, f"✅ User {user_id} unbanned.")
    except:
        bot.send_message(admin_id, "❌ Invalid ID.")

# ============ FLASK WEBHOOK SERVER ============

from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return 'OK', 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'Error', 500

@app.route('/health')
def health():
    try:
        stats = get_statistics()
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "users": stats['total'],
            "verified": stats['verified']
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/')
def index():
    return "🦾 Lenskart Bot is running!"

# ============ MAIN ============

if __name__ == "__main__":
    init_db()
    logger.info("Bot starting...")
    
    # Remove old webhook
    try:
        bot.remove_webhook()
        logger.info("Webhook removed")
    except Exception as e:
        logger.error(f"Webhook removal error: {e}")
    
    # Set webhook for production
    if "RENDER" in os.environ:
        webhook_url = f"{RENDER_URL}/webhook"
        try:
            result = bot.set_webhook(url=webhook_url)
            if result:
                logger.info(f"✅ Webhook set: {webhook_url}")
            else:
                logger.error("❌ Webhook set failed")
        except Exception as e:
            logger.error(f"Webhook error: {e}")
        
        port = int(os.environ.get("PORT", 5000))
        logger.info(f"Starting Flask on port {port}")
        app.run(host='0.0.0.0', port=port)
    else:
        # Local polling mode
        logger.info("Starting polling mode")
        bot.polling(none_stop=True, interval=0)
