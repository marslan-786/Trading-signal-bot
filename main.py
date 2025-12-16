import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import motor.motor_asyncio
from datetime import datetime, timedelta
import pytz

# ==========================================
# ⚙️ CONFIGURATION & DATABASE
# ==========================================

DEFAULT_OWNER_ID = 8167904992  
BOT_TOKEN = "8487438477:AAH6IbeGJnPXEvhGpb4TSAdJmzC0fXaa0Og"
MONGO_URL = "mongodb://mongo:AEvrikOWlrmJCQrDTQgfGtqLlwhwLuAA@crossover.proxy.rlwy.net:29609"

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = client['trading_bot_db']
users_collection = db['users']

# ==========================================
# 🚦 STATES FOR CONVERSATION
# ==========================================
LOGIN_USER, LOGIN_PASS = 0, 1
ADD_OWNER_TG_ID = 2
ADD_USER_LOGIN, ADD_USER_PASS, ADD_USER_DAYS = 3, 4, 5

# ==========================================
# 🚀 START COMMAND
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tg_id = user.id
    
    # --- CHECK 1: DEFAULT OWNER ---
    if tg_id == DEFAULT_OWNER_ID:
        await users_collection.update_one(
            {"telegram_id": tg_id},
            {"$set": {"role": "DEFAULT_OWNER", "login_id": "BOSS", "is_blocked": False}},
            upsert=True
        )
        await show_main_panel(update, context, "DEFAULT_OWNER")
        return ConversationHandler.END

    # --- CHECK 2 & 3: DATABASE CHECK ---
    user_doc = await users_collection.find_one({"telegram_id": tg_id})
    
    if user_doc:
        role = user_doc.get("role", "USER")
        await show_main_panel(update, context, role)
        return ConversationHandler.END
        
    # --- CHECK 4: LOGIN REQUIRED ---
    await update.message.reply_text(
        "🔒 System Locked\n\nPlease enter your Login ID to access:"
    )
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
            await update.message.reply_text("⛔ This account is already used on another Telegram!")
    else:
        await update.message.reply_text("❌ Invalid ID or Password. Try /start again.")
    
    return ConversationHandler.END

# ==========================================
# 🖥️ PANELS & MENUS (FIXED ERROR HERE)
# ==========================================
async def show_main_panel(update, context, role):
    keyboard = [[InlineKeyboardButton("📊 Get Pairs", callback_data="get_pairs")]]
    
    # Simple text without complex Markdown to avoid errors
    msg = f"👋 Welcome! Your Role: {role}"

    if role in ["DEFAULT_OWNER", "OWNER"]:
        keyboard.append([InlineKeyboardButton("👑 Owner Panel", callback_data="panel_owner")])
    elif role == "ADMIN":
        keyboard.append([InlineKeyboardButton("🛡️ Admin Panel", callback_data="panel_admin")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        # Delete old message and send new one to avoid editing errors
        await update.callback_query.message.delete()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup)

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
        keyboard.insert(0, [InlineKeyboardButton("➕ Add NEW OWNER (By ID)", callback_data="add_owner_start")])

    # Using edit_message_text safely
    try:
        await query.message.edit_text("👑 Owner Control Panel", reply_markup=InlineKeyboardMarkup(keyboard))
    except:
        await query.message.delete()
        await context.bot.send_message(chat_id=user_id, text="👑 Owner Control Panel", reply_markup=InlineKeyboardMarkup(keyboard))

# --- BACK BUTTON HANDLER ---
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id == DEFAULT_OWNER_ID:
        role = "DEFAULT_OWNER"
    else:
        user = await users_collection.find_one({"telegram_id": user_id})
        role = user.get("role", "USER") if user else "USER"
        
    await show_main_panel(update, context, role)

# --- ADD OWNER LOGIC ---
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
# ⚙️ MAIN SETUP
# ==========================================
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    
    login_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LOGIN_USER: [MessageHandler(filters.TEXT, login_user_input)],
            LOGIN_PASS: [MessageHandler(filters.TEXT, login_pass_input)],
        },
        fallbacks=[]
    )
    
    add_owner_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_owner_start, pattern="^add_owner_start$")],
        states={
            ADD_OWNER_TG_ID: [MessageHandler(filters.TEXT, add_owner_save)]
        },
        fallbacks=[]
    )

    app.add_handler(login_handler)
    app.add_handler(add_owner_handler)
    
    app.add_handler(CallbackQueryHandler(owner_panel, pattern="^panel_owner$"))
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))

    print("Bot is Running on Railway...")
    app.run_polling()
