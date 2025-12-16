import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import motor.motor_asyncio
from datetime import datetime, timedelta
import pytz

# ==========================================
# ⚙️ CONFIGURATION & DATABASE
# ==========================================

# اپنی اصلی آئی ڈی اور ٹوکن یہاں لکھیں
DEFAULT_OWNER_ID = 8167904992
BOT_TOKEN = "8487438477:AAH6IbeGJnPXEvhGpb4TSAdJmzC0fXaa0Og"
MONGO_URL = "mongodb://mongo:AEvrikOWlrmJCQrDTQgfGtqLlwhwLuAA@crossover.proxy.rlwy.net:29609"

# امیج کا لنک (فائل اپلوڈ کا جھنجھٹ ختم)
# آپ اسے اپنی مرضی کے لنک سے بدل سکتے ہیں (imgur یا telegram link)
BANNER_IMAGE_URL = "https://i.imgur.com/8QS1M4A.png" 

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = client['trading_bot_db']
users_collection = db['users']

# ==========================================
# 🚦 STATES FOR CONVERSATION
# ==========================================
LOGIN_USER, LOGIN_PASS = 0, 1
ADD_OWNER_TG_ID = 2

# ==========================================
# 🚀 START COMMAND
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tg_id = user.id
    
    # Check Default Owner
    if tg_id == DEFAULT_OWNER_ID:
        await users_collection.update_one(
            {"telegram_id": tg_id},
            {"$set": {"role": "DEFAULT_OWNER", "login_id": "BOSS", "is_blocked": False}},
            upsert=True
        )
        await show_main_panel(update, context, "DEFAULT_OWNER")
        return ConversationHandler.END

    # Check Database
    user_doc = await users_collection.find_one({"telegram_id": tg_id})
    if user_doc:
        role = user_doc.get("role", "USER")
        await show_main_panel(update, context, role)
        return ConversationHandler.END
        
    # Login Required
    await update.message.reply_text("🔒 System Locked\n\nPlease enter your Login ID to access:")
    return LOGIN_USER

# ==========================================
# 🔑 LOGIN SYSTEM
# ==========================================
async def login_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_login'] = update.message.text
    await update.message.reply_text("🔑 Enter Password:")
    return LOGIN_PASS

async def login_pass_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    login_id = context.user_data['temp_login']
    password = update.message.text
    tg_id = update.effective_user.id
    
    user = await users_collection.find_one({"login_id": login_id, "password": password})
    
    if user:
        if user.get("telegram_id") is None:
            await users_collection.update_one({"_id": user["_id"]}, {"$set": {"telegram_id": tg_id}})
            await update.message.reply_text("✅ Device Registered Successfully!")
            await show_main_panel(update, context, user['role'])
        elif user.get("telegram_id") == tg_id:
            await show_main_panel(update, context, user['role'])
        else:
            await update.message.reply_text("⛔ Account already used on another Telegram!")
    else:
        await update.message.reply_text("❌ Invalid ID or Password.")
    
    return ConversationHandler.END

# ==========================================
# 🖥️ PANELS & MENUS
# ==========================================
async def show_main_panel(update, context, role):
    keyboard = [[InlineKeyboardButton("📊 Get Pairs", callback_data="get_pairs")]]
    
    msg = f"👋 Welcome! Your Role: {role}\nSelect an option below:"

    if role in ["DEFAULT_OWNER", "OWNER"]:
        keyboard.append([InlineKeyboardButton("👑 Owner Panel", callback_data="panel_owner")])
    elif role == "ADMIN":
        keyboard.append([InlineKeyboardButton("🛡️ Admin Panel", callback_data="panel_admin")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # تصویر بھیجنے کا محفوظ طریقہ
    chat_id = update.effective_chat.id
    
    # پرانا میسج ڈیلیٹ کریں تاکہ نیا صاف ستھرا آئے
    if update.callback_query:
        try:
            await update.callback_query.message.delete()
        except:
            pass

    await context.bot.send_photo(
        chat_id=chat_id, 
        photo=BANNER_IMAGE_URL, 
        caption=msg, 
        reply_markup=reply_markup
    )

# ==========================================
# 📊 GET PAIRS HANDLER (یہ مسنگ تھا)
# ==========================================
async def get_pairs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # لوڈنگ ختم کرنے کے لیے
    
    keyboard = [
        [InlineKeyboardButton("EUR/USD", callback_data="pair_EURUSD"), InlineKeyboardButton("GBP/USD", callback_data="pair_GBPUSD")],
        [InlineKeyboardButton("USD/JPY", callback_data="pair_USDJPY"), InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    
    # تصویر کے ساتھ ایڈٹ کریں
    try:
        await query.message.edit_caption(caption="📉 Select a Currency Pair to Analyze:", reply_markup=InlineKeyboardMarkup(keyboard))
    except:
        # اگر فوٹو ایکسپائر ہو جائے تو نیا میسج
        await query.message.delete()
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=BANNER_IMAGE_URL,
            caption="📉 Select a Currency Pair:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# ==========================================
# 👑 OWNER PANEL HANDLING
# ==========================================
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id == DEFAULT_OWNER_ID:
        role = "DEFAULT_OWNER"
    else:
        user = await users_collection.find_one({"telegram_id": user_id})
        role = user.get("role", "USER") if user else "USER"
    
    if role not in ["DEFAULT_OWNER", "OWNER"]:
        await query.answer("❌ Access Denied", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton("➕ Add User / Admin", callback_data="add_ua_start")],
        [InlineKeyboardButton("📋 User List", callback_data="list_users")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    
    if role == "DEFAULT_OWNER":
        keyboard.insert(0, [InlineKeyboardButton("➕ Add NEW OWNER", callback_data="add_owner_start")])

    try:
        await query.message.edit_caption(caption="👑 Owner Control Panel", reply_markup=InlineKeyboardMarkup(keyboard))
    except:
        await context.bot.send_message(chat_id=user_id, text="👑 Owner Control Panel", reply_markup=InlineKeyboardMarkup(keyboard))

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id == DEFAULT_OWNER_ID:
        role = "DEFAULT_OWNER"
    else:
        user = await users_collection.find_one({"telegram_id": user_id})
        role = user.get("role", "USER") if user else "USER"
        
    await show_main_panel(update, context, role)

# --- ADD OWNER ---
async def add_owner_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("👤 Send the Telegram ID of the new Owner:")
    return ADD_OWNER_TG_ID

async def add_owner_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_owner_id = int(update.message.text)
        await users_collection.insert_one({
            "telegram_id": new_owner_id,
            "role": "OWNER",
            "created_by": "DEFAULT_OWNER",
            "is_blocked": False
        })
        await update.message.reply_text(f"✅ Owner Added (ID: {new_owner_id}) successfully!")
    except ValueError:
        await update.message.reply_text("❌ Please send a valid numeric ID.")
    return ConversationHandler.END

# ==========================================
# ⚙️ MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LOGIN_USER: [MessageHandler(filters.TEXT, login_user_input)],
            LOGIN_PASS: [MessageHandler(filters.TEXT, login_pass_input)],
        },
        fallbacks=[]
    )
    
    add_owner_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_owner_start, pattern="^add_owner_start$")],
        states={ADD_OWNER_TG_ID: [MessageHandler(filters.TEXT, add_owner_save)]},
        fallbacks=[]
    )

    app.add_handler(login_conv)
    app.add_handler(add_owner_conv)
    
    # Callback Handlers
    app.add_handler(CallbackQueryHandler(owner_panel, pattern="^panel_owner$"))
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    
    # --- HERE IS THE FIX FOR "GET PAIRS" ---
    app.add_handler(CallbackQueryHandler(get_pairs_handler, pattern="^get_pairs$")) 

    print("Bot is Running on Railway...")
    
    # drop_pending_updates=True پرانے لٹکے ہوئے میسجز کو صاف کر دے گا
    app.run_polling(drop_pending_updates=True)
