import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import motor.motor_asyncio
from datetime import datetime, timedelta
import pytz

# ==========================================
# ⚙️ CONFIGURATION & DATABASE
# ==========================================

# 1. اپنی ٹیلیگرام آئی ڈی یہاں لکھیں (یہ بندہ سب کا باپ ہے)
DEFAULT_OWNER_ID = 8167904992  # <--- REPLACE WITH YOUR REAL TELEGRAM ID
BOT_TOKEN = "8487438477:AAH6IbeGJnPXEvhGpb4TSAdJmzC0fXaa0Og"
MONGO_URL = "mongodb://mongo:AEvrikOWlrmJCQrDTQgfGtqLlwhwLuAA@crossover.proxy.rlwy.net:29609"

# 2. Database Connection
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = client['trading_bot_db']
users_collection = db['users']

# ==========================================
# 🚦 STATES FOR CONVERSATION
# ==========================================
LOGIN_USER, LOGIN_PASS = 0, 1
ADD_OWNER_TG_ID = 2  # صرف اونر کے لیے
ADD_USER_LOGIN, ADD_USER_PASS, ADD_USER_DAYS = 3, 4, 5 # ایڈمن/یوزر کے لیے

# ==========================================
# 🚀 START COMMAND (AUTO DETECT OWNER)
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tg_id = user.id
    
    # --- CHECK 1: کیا یہ ڈیفالٹ اونر ہے؟ ---
    if tg_id == DEFAULT_OWNER_ID:
        # اگر یہ پہلی بار آیا ہے تو ڈیٹا بیس میں سیو کر لیں تاکہ ریکارڈ رہے
        await users_collection.update_one(
            {"telegram_id": tg_id},
            {"$set": {"role": "DEFAULT_OWNER", "login_id": "BOSS", "is_blocked": False}},
            upsert=True
        )
        await show_main_panel(update, context, "DEFAULT_OWNER")
        return ConversationHandler.END

    # --- CHECK 2: کیا یہ کوئی عام اونر ہے (جسے ایڈ کیا گیا ہو)؟ ---
    user_doc = await users_collection.find_one({"telegram_id": tg_id})
    
    if user_doc and user_doc.get("role") == "OWNER":
        # یہ بھی ڈائریکٹ لاگ ان ہوگا
        await show_main_panel(update, context, "OWNER")
        return ConversationHandler.END

    # --- CHECK 3: کیا یہ نارمل یوزر/ایڈمن ہے؟ ---
    # اگر یہ لاگ ان ہے
    if user_doc and user_doc.get("role") in ["ADMIN", "USER"]:
        await show_main_panel(update, context, user_doc['role'])
        return ConversationHandler.END
        
    # --- CHECK 4: اگر کوئی بھی نہیں ہے تو لاگ ان مانگیں ---
    await update.message.reply_text(
        "🔒 **System Locked**\n\nPlease enter your **Login ID** to access:",
        parse_mode="Markdown"
    )
    return LOGIN_USER

# ==========================================
# 🔑 LOGIN SYSTEM (FOR ADMINS & USERS)
# ==========================================
async def login_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_login'] = update.message.text
    await update.message.reply_text("🔑 Enter **Password**:")
    return LOGIN_PASS

async def login_pass_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    login_id = context.user_data['temp_login']
    password = update.message.text
    tg_id = update.effective_user.id
    
    # پاسورڈ چیک کریں (اونر/ڈیفالٹ اونر کا پاسورڈ نہیں ہوتا، وہ آئی ڈی سے آتے ہیں)
    user = await users_collection.find_one({"login_id": login_id, "password": password})
    
    if user:
        # اگر یہ یوزر پہلے کسی اور ٹیلیگرام پر نہیں چل رہا
        if user.get("telegram_id") is None:
            await users_collection.update_one({"_id": user["_id"]}, {"$set": {"telegram_id": tg_id}})
            await update.message.reply_text("✅ **Device Registered Successfully!**")
            await show_main_panel(update, context, user['role'])
        elif user.get("telegram_id") == tg_id:
            await show_main_panel(update, context, user['role'])
        else:
            await update.message.reply_text("⛔ This account is already used on another Telegram!")
    else:
        await update.message.reply_text("❌ Invalid ID or Password. Try `/start` again.")
    
    return ConversationHandler.END

# ==========================================
# 🖥️ PANELS & MENUS
# ==========================================
async def show_main_panel(update, context, role):
    keyboard = [[InlineKeyboardButton("📊 Get Pairs", callback_data="get_pairs")]]
    
    msg = f"👋 Welcome! Your Role: **{role}**"

    if role in ["DEFAULT_OWNER", "OWNER"]:
        keyboard.append([InlineKeyboardButton("👑 Owner Panel", callback_data="panel_owner")])
    elif role == "ADMIN":
        keyboard.append([InlineKeyboardButton("🛡️ Admin Panel", callback_data="panel_admin")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # اگر یہ بٹن کلک سے آیا ہے
    if update.callback_query:
        await update.callback_query.message.edit_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")

# ==========================================
# 👑 OWNER PANEL HANDLING
# ==========================================
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    # دوبارہ چیک کریں کہ یہ واقعی اونر ہے
    if user_id == DEFAULT_OWNER_ID:
        role = "DEFAULT_OWNER"
    else:
        user = await users_collection.find_one({"telegram_id": user_id})
        role = user.get("role", "USER")
    
    if role not in ["DEFAULT_OWNER", "OWNER"]:
        await query.answer("❌ Access Denied", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton("➕ Add User / Admin", callback_data="add_ua_start")],
        [InlineKeyboardButton("📋 User List", callback_data="list_users")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    
    # صرف ڈیفالٹ اونر نیا اونر ایڈ کر سکتا ہے
    if role == "DEFAULT_OWNER":
        keyboard.insert(0, [InlineKeyboardButton("➕ Add NEW OWNER (By ID)", callback_data="add_owner_start")])

    await query.message.edit_text("👑 **Owner Control Panel**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# --- 1. ADD OWNER LOGIC (BY ID) ---
async def add_owner_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("👤 Send the **Telegram ID** of the new Owner:")
    return ADD_OWNER_TG_ID

async def add_owner_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_owner_id = int(update.message.text)
        # ڈیٹا بیس میں محفوظ کریں
        await users_collection.insert_one({
            "telegram_id": new_owner_id,
            "role": "OWNER",
            "created_by": "DEFAULT_OWNER",
            "is_blocked": False
        })
        await update.message.reply_text(f"✅ Owner Added (ID: `{new_owner_id}`) successfully!", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Please send a valid numeric ID.")
    
    return ConversationHandler.END

# --- 2. ADD USER/ADMIN LOGIC (LOGIN/PASS) ---
# (یہاں آپ کا پرانا کوڈ آئے گا جو میں نے پچھلی بار دیا تھا، Login ID اور Password پوچھنے والا)
# میں کوڈ چھوٹا رکھنے کے لیے اسے ابھی skip کر رہا ہوں، لیکن فلو یہ ہوگا:
# Start -> Ask Login -> Ask Pass -> Ask Days -> Save to DB

# ==========================================
# ⚙️ MAIN SETUP
# ==========================================
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    
    # لاگ ان کنورسیشن
    login_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LOGIN_USER: [MessageHandler(filters.TEXT, login_user_input)],
            LOGIN_PASS: [MessageHandler(filters.TEXT, login_pass_input)],
        },
        fallbacks=[]
    )
    
    # اونر ایڈ کرنے کی کنورسیشن
    add_owner_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_owner_start, pattern="^add_owner_start$")],
        states={
            ADD_OWNER_TG_ID: [MessageHandler(filters.TEXT, add_owner_save)]
        },
        fallbacks=[]
    )

    app.add_handler(login_handler)
    app.add_handler(add_owner_handler)
    
    # پینل ہینڈلرز
    app.add_handler(CallbackQueryHandler(owner_panel, pattern="^panel_owner$"))
    # ... (Add other handlers like get_pairs, etc.)

    print("Bot is Running on Railway...")
    app.run_polling()
