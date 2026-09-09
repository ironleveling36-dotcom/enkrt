import os
import sys
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import random
import string
import time
import logging
from datetime import datetime
import sqlite3
import json
import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import config
try:
    from config import BOT_TOKEN, CHANNEL_ID, ADMIN_IDS, RENDER_URL
except ImportError:
    logger.error("Config file not found! Creating default config.")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    CHANNEL_ID = os.getenv("CHANNEL_ID", "")
    ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]
    RENDER_URL = os.getenv("RENDER_URL", "https://enkrt.onrender.com")

# Import database
try:
    import database as db
except ImportError:
    logger.error("Database module not found!")
    sys.exit(1)

# Import Lenskart
try:
    from lenskart import LenskartFakeDevice
except ImportError as e:
    logger.error(f"Lenskart module not found: {e}")
    # Create dummy class if missing
    class LenskartFakeDevice:
        def __init__(self, phone, phone_code="+91"):
            self.phone = phone
            self.brand = "test"
            self.model = "test"
        def create_session(self): return True
        def send_otp(self): return True
        def verify_otp(self, code): return True
        def me(self): return {}
        def claim_reward(self, steps=30000): return {"giftVoucher": "TEST-123"}

# Validate BOT_TOKEN
if not BOT_TOKEN:
    logger.error("BOT_TOKEN not set! Please set it in environment variables.")
    sys.exit(1)

# Initialize bot
try:
    bot = telebot.TeleBot(BOT_TOKEN)
    logger.info("Bot initialized successfully!")
except Exception as e:
    logger.error(f"Failed to initialize bot: {e}")
    sys.exit(1)

# Store active OTP sessions
otp_sessions = {}

# ============ Helper Functions ============

def generate_referral_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def is_admin(user_id):
    return user_id in ADMIN_IDS

def check_channel_membership(user_id):
    if not CHANNEL_ID:
        return True  # Skip if no channel set
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Channel check error: {e}")
        return False

def get_user_status(user_id):
    user = db.get_user(user_id)
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

def get_referral_link(user_id, username=None):
    user = db.get_user(user_id)
    if not user:
        return None
    ref_code = user[3]
    if not ref_code:
        ref_code = generate_referral_code()
        conn = sqlite3.connect(db.DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET referral_code = ? WHERE user_id = ?', (ref_code, user_id))
        conn.commit()
        conn.close()
    
    if username:
        return f"https://t.me/{username}?start={ref_code}"
    return f"https://t.me/your_bot_username?start={ref_code}"

# ============ Command Handlers ============

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.username or str(user_id)
    
    try:
        # Check if user is banned
        user = db.get_user(user_id)
        if user and user[8] == 1:
            bot.send_message(user_id, "🚫 You are banned from using this bot.")
            return
        
        # Parse referral parameter
        ref_code = None
        if len(message.text.split()) > 1:
            ref_code = message.text.split()[1]
        
        # Add user to DB if new
        if not user:
            referred_by = None
            if ref_code:
                conn = sqlite3.connect(db.DB_PATH)
                c = conn.cursor()
                c.execute('SELECT user_id FROM users WHERE referral_code = ?', (ref_code,))
                result = c.fetchone()
                conn.close()
                if result:
                    referred_by = result[0]
            
            db.add_user(user_id, username, generate_referral_code(), referred_by)
            
            if referred_by:
                db.add_referral(referred_by, user_id)
                db.increment_referrals(referred_by)
                try:
                    bot.send_message(referred_by, f"🎯 New referral! {username} joined using your link.")
                except:
                    pass
            
            db.log_action(user_id, "start", f"Referred by: {referred_by}")
        
        # Check channel membership
        if CHANNEL_ID and not check_channel_membership(user_id):
            markup = InlineKeyboardMarkup()
            channel_username = CHANNEL_ID.replace('-100', '')
            markup.add(InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{channel_username}"))
            markup.add(InlineKeyboardButton("🔄 Check Again", callback_data="check_membership"))
            bot.send_message(
                user_id,
                "🚫 You must join our channel to use this bot!\n\n"
                "Click the button below to join, then click 'Check Again'.",
                reply_markup=markup
            )
            return
        
        # Main menu
        show_main_menu(user_id)
        
    except Exception as e:
        logger.error(f"Start command error: {e}")
        bot.send_message(user_id, f"❌ Error: {str(e)}")

def show_main_menu(user_id):
    try:
        user = get_user_status(user_id)
        if not user:
            bot.send_message(user_id, "❌ User not found. Please use /start again.")
            return
        
        referrals = db.get_referrals(user_id)
        verified = user['verified']
        
        text = f"""
🎯 **Lenskart Frame Generator**

👤 User: {user['username']}
📱 Phone: {user['phone'] or 'Not set'}
🔑 Referral Code: `{user['referral_code']}`
👥 Referrals: {referrals}
✅ Verified: {'Yes' if verified else 'No'}

**Status:** {'🔓 Active' if verified else '🔒 Locked'}
Need 2 referrals to unlock!
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
        
    except Exception as e:
        logger.error(f"Show main menu error: {e}")
        bot.send_message(user_id, f"❌ Error: {str(e)}")

# ============ Callback Handlers ============

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    
    try:
        # Check channel membership first (except for membership check itself)
        if data != "check_membership" and CHANNEL_ID and not check_channel_membership(user_id):
            markup = InlineKeyboardMarkup()
            channel_username = CHANNEL_ID.replace('-100', '')
            markup.add(InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{channel_username}"))
            markup.add(InlineKeyboardButton("🔄 Check Again", callback_data="check_membership"))
            bot.edit_message_text(
                "🚫 You must join our channel first!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=markup
            )
            return
        
        if data == "check_membership":
            if check_channel_membership(user_id):
                bot.edit_message_text(
                    "✅ You're a member! Redirecting...",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id
                )
                show_main_menu(user_id)
            else:
                bot.answer_callback_query(call.id, "❌ Still not a member. Please join first!")
        
        elif data == "my_referrals":
            referrals = db.get_referrals(user_id)
            user = get_user_status(user_id)
            
            conn = sqlite3.connect(db.DB_PATH)
            c = conn.cursor()
            c.execute('''
                SELECT u.username, r.timestamp 
                FROM referrals r
                JOIN users u ON r.referred_id = u.user_id
                WHERE r.referrer_id = ?
                ORDER BY r.timestamp DESC
            ''', (user_id,))
            ref_list = c.fetchall()
            conn.close()
            
            text = f"👥 **Your Referrals: {referrals}**\n\n"
            if ref_list:
                for i, (username, ts) in enumerate(ref_list, 1):
                    text += f"{i}. @{username or 'Unknown'} - {ts[:16]}\n"
            else:
                text += "No referrals yet. Share your link!"
            
            text += f"\n🔑 Code: `{user['referral_code']}`\n"
            text += f"Need 2 referrals to unlock: {referrals}/2"
            
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown'
            )
        
        elif data == "get_link":
            user = get_user_status(user_id)
            link = get_referral_link(user_id, call.from_user.username)
            if link:
                text = f"🔗 **Your Referral Link:**\n`{link}`\n\nShare this link with friends. After 2 join, you unlock!"
            else:
                text = "❌ Error generating link. Please contact admin."
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown'
            )
        
        elif data == "check_status":
            user = get_user_status(user_id)
            referrals = db.get_referrals(user_id)
            
            if referrals >= 2 and not user['verified']:
                conn = sqlite3.connect(db.DB_PATH)
                c = conn.cursor()
                c.execute('UPDATE users SET verified = 1 WHERE user_id = ?', (user_id,))
                conn.commit()
                conn.close()
                db.log_action(user_id, "verified", "Unlocked via referrals")
                bot.edit_message_text(
                    "✅ **Congratulations!** You've been unlocked!\n\n"
                    "You can now use the Lenskart Frame Generator.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    parse_mode='Markdown'
                )
                show_main_menu(user_id)
            else:
                if user['verified']:
                    status = "🔓 **Unlocked**"
                    status_msg = "You're verified!"
                else:
                    status = "🔒 **Locked**"
                    status_msg = "Keep sharing your link!"
                
                bot.edit_message_text(
                    f"📊 **Status:** {status}\n"
                    f"👥 Referrals: {referrals}/2\n\n"
                    f"{status_msg}",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    parse_mode='Markdown'
                )
        
        elif data == "start_gen":
            user = get_user_status(user_id)
            if not user['verified']:
                bot.answer_callback_query(call.id, "❌ You need 2 referrals first!")
                return
            
            start_generation_flow(user_id)
        
        elif data == "admin_panel":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "⛔ Admin only!")
                return
            show_admin_panel(call.message, user_id)
        
        elif data == "back_to_menu":
            show_main_menu(user_id)
            
    except Exception as e:
        logger.error(f"Callback error: {e}")
        bot.answer_callback_query(call.id, f"❌ Error: {str(e)[:50]}")

# ============ Generation Flow ============

def start_generation_flow(user_id):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu"))
    
    msg = bot.send_message(
        user_id,
        "📱 **Enter phone number with country code**\n"
        "Example: `919876543210`\n\n"
        "Type `/cancel` to cancel.",
        reply_markup=markup,
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
        bot.send_message(user_id, "❌ Invalid phone number. Try again or /cancel.")
        start_generation_flow(user_id)
        return
    
    db.update_user_phone(user_id, phone)
    db.log_action(user_id, "phone_set", phone)
    
    try:
        device = LenskartFakeDevice(phone)
        
        bot.send_message(user_id, "🔄 Creating session...")
        if not device.create_session():
            bot.send_message(user_id, "❌ Session creation failed. Try again later.")
            show_main_menu(user_id)
            return
        
        bot.send_message(user_id, "📨 Sending OTP...")
        otp_result = device.send_otp()
        if not otp_result:
            bot.send_message(user_id, "❌ OTP send failed. Check phone number.")
            show_main_menu(user_id)
            return
        
        otp_sessions[user_id] = device
        
        msg = bot.send_message(
            user_id,
            f"✅ OTP sent to {phone}\n\nEnter the OTP you received:",
        )
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
        bot.send_message(user_id, "❌ Invalid OTP (4 digits). Try again or /cancel.")
        return
    
    device = otp_sessions.get(user_id)
    if not device:
        bot.send_message(user_id, "❌ Session expired. Start again.")
        show_main_menu(user_id)
        return
    
    bot.send_message(user_id, "🔄 Verifying OTP...")
    verify_result = device.verify_otp(otp)
    if not verify_result:
        bot.send_message(user_id, "❌ OTP verification failed. Try again.")
        otp_sessions.pop(user_id, None)
        show_main_menu(user_id)
        return
    
    bot.send_message(user_id, "🔄 Getting profile...")
    device.me()
    
    bot.send_message(user_id, "🏃 Claiming reward with 30,000 steps...")
    reward = device.claim_reward(steps=30000)
    
    if reward and reward.get('giftVoucher'):
        bot.send_message(
            user_id,
            f"🎉 **SUCCESS!**\n\n"
            f"🏆 Tier: {reward.get('tier')}\n"
            f"🎫 Voucher: {reward.get('giftVoucher')}\n"
            f"📊 Steps: {reward.get('steps')}\n"
            f"📱 Device: {device.brand} {device.model}\n\n"
            f"✅ Reward saved to reward_{device.phone}.json",
            parse_mode='Markdown'
        )
        db.log_action(user_id, "reward_claimed", f"Voucher: {reward.get('giftVoucher')}")
    else:
        msg = reward.get('message', 'No reward unlocked') if reward else 'Failed'
        bot.send_message(user_id, f"⚠️ {msg}")
        db.log_action(user_id, "reward_failed", msg)
    
    otp_sessions.pop(user_id, None)
    show_main_menu(user_id)

# ============ Admin Panel ============

def show_admin_panel(message, admin_id):
    stats = db.get_statistics()
    text = f"""
⚙️ **Admin Panel**

📊 **Statistics:**
• Total Users: {stats['total']}
• Verified Users: {stats['verified']}
• Total Referrals: {stats['referrals']}

📌 **Options:**
"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📋 List Users", callback_data="admin_list_users"),
        InlineKeyboardButton("📜 View Logs", callback_data="admin_view_logs"),
        InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
        InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"),
        InlineKeyboardButton("🔓 Unban User", callback_data="admin_unban"),
        InlineKeyboardButton("📊 Export Data", callback_data="admin_export")
    )
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_menu"))
    
    if isinstance(message, telebot.types.Message):
        bot.send_message(admin_id, text, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.edit_message_text(
            text,
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=markup,
            parse_mode='Markdown'
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callback(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "⛔ Admin only!")
        return
    
    action = call.data.replace("admin_", "")
    
    if action == "list_users":
        users = db.get_all_users()
        text = "📋 **Users List:**\n\n"
        for u in users[:20]:
            text += f"ID: {u[0]} | @{u[1] or 'N/A'} | 📱{u[2] or 'N/A'} | Ref: {u[3]} | {'✅' if u[4] else '❌'}\n"
        if len(users) > 20:
            text += f"\n... and {len(users)-20} more"
        bot.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown'
        )
    
    elif action == "view_logs":
        logs = db.get_logs(20)
        text = "📜 **Recent Logs:**\n\n"
        for log in logs:
            text += f"{log[4][:16]} | {log[1]} | {log[2]}\n"
        bot.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown'
        )
    
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
    
    elif action == "export":
        export_data()
        bot.send_message(
            user_id,
            "📊 Data exported to `export_data.json`",
            parse_mode='Markdown'
        )

def process_broadcast(message):
    admin_id = message.from_user.id
    broadcast_text = message.text
    
    users = db.get_all_users()
    sent = 0
    for user in users:
        try:
            bot.send_message(user[0], f"📢 **Announcement:**\n\n{broadcast_text}", parse_mode='Markdown')
            sent += 1
            time.sleep(0.05)
        except:
            pass
    
    bot.send_message(admin_id, f"✅ Broadcast sent to {sent} users.")
    db.log_action(admin_id, "broadcast", f"Sent to {sent} users")

def process_ban_user(message):
    admin_id = message.from_user.id
    try:
        user_id = int(message.text.strip())
        conn = sqlite3.connect(db.DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        db.log_action(admin_id, "banned", f"User {user_id}")
        bot.send_message(admin_id, f"✅ User {user_id} banned.")
    except:
        bot.send_message(admin_id, "❌ Invalid user ID.")

def process_unban_user(message):
    admin_id = message.from_user.id
    try:
        user_id = int(message.text.strip())
        conn = sqlite3.connect(db.DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        db.log_action(admin_id, "unbanned", f"User {user_id}")
        bot.send_message(admin_id, f"✅ User {user_id} unbanned.")
    except:
        bot.send_message(admin_id, "❌ Invalid user ID.")

def export_data():
    data = {
        'users': db.get_all_users(),
        'stats': db.get_statistics(),
        'logs': db.get_logs(100)
    }
    with open('export_data.json', 'w') as f:
        json.dump(data, f, default=str, indent=2)

# ============ Flask Webhook Server ============

from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        json_data = request.get_json()
        update = telebot.types.Update.de_json(json_data)
        bot.process_new_updates([update])
        return 'OK', 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'Error', 500

@app.route('/health')
def health():
    try:
        stats = db.get_statistics()
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "users": stats['total'],
            "verified": stats['verified'],
            "webhook": "active"
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/')
def index():
    return "🦾 Lenskart Bot is running! Webhook is active."

@app.route('/setwebhook')
def set_webhook():
    """Helper endpoint to set webhook"""
    try:
        url = f"{RENDER_URL}/webhook"
        response = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            params={"url": url}
        )
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============ Start Server ============

if __name__ == "__main__":
    try:
        db.init_db()
        logger.info("Database initialized successfully!")
        
        # Remove existing webhook
        try:
            bot.remove_webhook()
            logger.info("Webhook removed")
        except Exception as e:
            logger.error(f"Webhook removal error: {e}")
        
        port = int(os.environ.get("PORT", 5000))
        logger.info(f"Starting Flask server on port {port}")
        logger.info(f"Webhook URL: {RENDER_URL}/webhook")
        logger.info(f"Health check: {RENDER_URL}/health")
        
        # Auto-set webhook
        try:
            webhook_url = f"{RENDER_URL}/webhook"
            result = bot.set_webhook(url=webhook_url)
            if result:
                logger.info(f"✅ Webhook set to: {webhook_url}")
            else:
                logger.error("❌ Failed to set webhook")
        except Exception as e:
            logger.error(f"Webhook set error: {e}")
        
        app.run(host='0.0.0.0', port=port)
        
    except Exception as e:
        logger.error(f"Startup error: {e}")
        sys.exit(1)
