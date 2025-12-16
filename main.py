import asyncio
import time
import json
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.request import HTTPXRequest
import motor.motor_asyncio

# ==========================================
# ⚙️ CONFIGURATION & DEFAULT LOGIC
# ==========================================
DEFAULT_OWNER_ID = 8167904992
BOT_TOKEN = "8487438477:AAH6IbeGJnPXEvhGpb4TSAdJmzC0fXaa0Og"
MONGO_URL = "mongodb://mongo:AEvrikOWlrmJCQrDTQgfGtqLlwhwLuAA@crossover.proxy.rlwy.net:29609"
BANNER_IMAGE_URL = "[https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQQZxNYQibx7vN--rZ9LVHiDbIYok3dWw4oz1-pNnPCLg&s=10](https://i.imgur.com/8QS1M4A.png)" 

# --- DEFAULT LOGIC ---
DEFAULT_LOGIC_CONFIG = {
    "ema_short": 50,
    "ema_long": 200,
    "rsi_period": 14,
    "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
    "call_rsi_min": 40, "call_rsi_max": 55,
    "put_rsi_min": 45, "put_rsi_max": 60
}

# Database Init
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = client['trading_bot_db']
users_collection = db['users']
settings_collection = db['settings']

# Conversation States
LOGIN_USER, LOGIN_PASS = 0, 1
ADD_OWNER_TG_ID = 2
AU_ID, AU_PASS, AU_DAYS = 3, 4, 5
AA_ID, AA_PASS, AA_DAYS, AA_PERM = 6, 7, 8, 9
CL_INPUT = 10

# ==========================================
# 🧠 TRADE BRAIN (THE LOGIC)
# ==========================================
async def get_logic_settings():
    settings = await settings_collection.find_one({"type": "logic"})
    if not settings:
        await settings_collection.insert_one({"type": "logic", **DEFAULT_LOGIC_CONFIG})
        return DEFAULT_LOGIC_CONFIG
    return settings

def calculate_signal(prices, config):
    if len(prices) < config['ema_long']: return "WAIT (Data < 200)", 0, 0, 0

    # EMA
    ema_short = sum(prices[-config['ema_short']:]) / config['ema_short']
    ema_long = sum(prices[-config['ema_long']:]) / config['ema_long']

    # RSI
    gains, losses = [], []
    for i in range(-config['rsi_period'], 0):
        change = prices[i] - prices[i-1]
        if change > 0: gains.append(change); losses.append(0)
        else: gains.append(0); losses.append(abs(change))
    
    avg_gain = sum(gains) / config['rsi_period'] if gains else 0
    avg_loss = sum(losses) / config['rsi_period'] if losses else 0
    
    if avg_loss == 0:
        rsi = 100
    else:
        rsi = 100 - (100 / (1 + avg_gain / avg_loss))

    # MACD
    short_ema = sum(prices[-config['macd_fast']:]) / config['macd_fast']
    long_ema = sum(prices[-config['macd_slow']:]) / config['macd_slow']
    macd = short_ema - long_ema

    # DECISION
    signal = "HOLD"
    
    if (ema_short > ema_long and 
        config['call_rsi_min'] < rsi < config['call_rsi_max'] and 
        macd > 0):
        signal = "CALL 🟢"
    elif (ema_short < ema_long and 
          config['put_rsi_min'] < rsi < config['put_rsi_max'] and 
          macd < 0):
        signal = "PUT 🔴"

    return signal, rsi, ema_short, ema_long

# ==========================================
# 🚀 START & LOGIN
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tg_id = user.id
    
    if tg_id == DEFAULT_OWNER_ID:
        await users_collection.update_one(
            {"telegram_id": tg_id},
            {"$set": {"role": "DEFAULT_OWNER", "login_id": "BOSS", "is_blocked": False}},
            upsert=True
        )
        await get_logic_settings()
        await show_main_panel(update, context, "DEFAULT_OWNER")
        return ConversationHandler.END

    user_doc = await users_collection.find_one({"telegram_id": tg_id})
    if user_doc:
        await show_main_panel(update, context, user_doc['role'])
        return ConversationHandler.END
        
    await update.message.reply_text("🔒 **System Locked**\nEnter Login ID:", parse_mode="Markdown")
    return LOGIN_USER

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
        if not user.get("telegram_id") or user.get("telegram_id") == tg_id:
            await users_collection.update_one({"_id": user["_id"]}, {"$set": {"telegram_id": tg_id}})
            await update.message.reply_text("✅ Login Success!")
            await show_main_panel(update, context, user['role'])
        else:
            await update.message.reply_text("⛔ ID used on another Telegram!")
    else:
        await update.message.reply_text("❌ Wrong Credentials.")
    return ConversationHandler.END

# ==========================================
# 🖥️ PANELS & NAVIGATION
# ==========================================
async def show_main_panel(update, context, role):
    keyboard = [[InlineKeyboardButton("📊 Get Pairs", callback_data="get_pairs")]]
    if role in ["DEFAULT_OWNER", "OWNER"]:
        keyboard.append([InlineKeyboardButton("👑 Owner Panel", callback_data="panel_owner")])
    elif role == "ADMIN":
        keyboard.append([InlineKeyboardButton("🛡️ Admin Panel", callback_data="panel_admin")])

    msg = f"👋 **Welcome Boss!**\nRole: `{role}`"
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        try: await update.callback_query.message.delete()
        except: pass
    
    await context.bot.send_photo(chat_id=update.effective_chat.id, photo=BANNER_IMAGE_URL, caption=msg, reply_markup=reply_markup, parse_mode="Markdown")

# --- 1. GET PAIRS ---
async def get_pairs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("EUR/USD", callback_data="pair_EURUSD"), InlineKeyboardButton("GBP/USD", callback_data="pair_GBPUSD")],
        [InlineKeyboardButton("USD/JPY", callback_data="pair_USDJPY"), InlineKeyboardButton("BTC/USD", callback_data="pair_BTCUSD")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    await query.message.edit_caption(caption="📉 **Select Market Pair:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# --- 2. SELECT TIMEFRAME ---
async def pair_select_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    selected_pair = query.data.split("_")[1]
    context.user_data['pair'] = selected_pair
    
    keyboard = [
        [InlineKeyboardButton("1 Min", callback_data="time_1m"), InlineKeyboardButton("5 Min", callback_data="time_5m")],
        [InlineKeyboardButton("15 Min", callback_data="time_15m"), InlineKeyboardButton("30 Min", callback_data="time_30m")],
        [InlineKeyboardButton("🔙 Back", callback_data="get_pairs")]
    ]
    await query.message.edit_caption(
        caption=f"📉 Pair: **{selected_pair}**\nNow select timeframe:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# --- 3. GENERATE SIGNAL ---
async def generate_signal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    pair = context.user_data.get('pair', 'Unknown')
    timeframe = query.data.split("_")[1]
    
    await query.message.edit_caption(caption="🔄 **Analyzing Market...**")
    
    # Fake Data for Demo (Quotex Logic integration point)
    base = 1.0500
    prices = [base + random.uniform(-0.002, 0.002) for _ in range(250)]
    
    config = await get_logic_settings()
    signal, rsi, ema_s, ema_l = calculate_signal(prices, config)
    
    res_text = (
        f"🚨 **SIGNAL REPORT** 🚨\n"
        f"---------------------------\n"
        f"🆔 **Pair:** {pair}\n"
        f"⏱ **Time:** {timeframe}\n"
        f"---------------------------\n"
        f"🧠 **AI Analysis:**\n"
        f"• RSI: `{round(rsi, 2)}`\n"
        f"• EMA 50: `{round(ema_s, 5)}`\n"
        f"• EMA 200: `{round(ema_l, 5)}`\n"
        f"---------------------------\n"
        f"🎯 **DECISION:**\n"
        f"# {signal}"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Pairs", callback_data="get_pairs")]]
    await query.message.edit_caption(caption=res_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ==========================================
# 👑 OWNER PANEL & ADD USER/ADMIN LOGIC
# ==========================================
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [
        [InlineKeyboardButton("👤 Add User", callback_data="add_user_start"), InlineKeyboardButton("👮‍♂️ Add Admin", callback_data="add_admin_start")],
        [InlineKeyboardButton("⚙️ Change Logic", callback_data="change_logic_start")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    if update.effective_user.id == DEFAULT_OWNER_ID:
        keyboard.insert(0, [InlineKeyboardButton("➕ Add NEW OWNER", callback_data="add_owner_start")])
    
    await query.message.edit_caption(caption="👑 **Owner Panel**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# --- ADD USER ---
async def au_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("👤 **Add New User**\n\nSend new **User ID**:")
    return AU_ID

async def au_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_uid'] = update.message.text
    await update.message.reply_text("🔑 Send **Password**:")
    return AU_PASS

async def au_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_upass'] = update.message.text
    await update.message.reply_text("📅 Enter **Days**:")
    return AU_DAYS

async def au_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = int(update.message.text)
    uid = context.user_data['new_uid']
    upass = context.user_data['new_upass']
    
    await users_collection.insert_one({
        "login_id": uid, "password": upass, "role": "USER",
        "expiry": datetime.now() + timedelta(days=days),
        "created_by": update.effective_user.id
    })
    
    msg = (
        f"✅ **User Created Successfully!**\n"
        f"-----------------------------\n"
        f"🆔 **ID:** `{uid}`\n"
        f"🔑 **Pass:** `{upass}`\n"
        f"📅 **Days:** {days}\n"
        f"-----------------------------\n"
        f"_Copy and forward this._"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return ConversationHandler.END

# --- ADD ADMIN ---
async def aa_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("👮‍♂️ **Add New Admin**\n\nSend new **Admin ID**:")
    return AA_ID

async def aa_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_aid'] = update.message.text
    await update.message.reply_text("🔑 Send **Password**:")
    return AA_PASS

async def aa_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_apass'] = update.message.text
    await update.message.reply_text("📅 Enter **Days**:")
    return AA_DAYS

async def aa_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_adays'] = int(update.message.text)
    keyboard = [
        [InlineKeyboardButton("Users Only", callback_data="perm_users"), InlineKeyboardButton("Users + Admins", callback_data="perm_full")]
    ]
    await update.message.reply_text("🛡️ **Select Permissions:**", reply_markup=InlineKeyboardMarkup(keyboard))
    return AA_PERM

async def aa_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    perm = query.data
    aid = context.user_data['new_aid']
    apass = context.user_data['new_apass']
    
    await users_collection.insert_one({
        "login_id": aid, "password": apass, "role": "ADMIN",
        "permissions": perm,
        "expiry": datetime.now() + timedelta(days=context.user_data['new_adays'])
    })
    
    perm_text = "Add Users Only" if perm == "perm_users" else "Full Admin Access"
    msg = (
        f"✅ **Admin Created Successfully!**\n"
        f"-----------------------------\n"
        f"🆔 **ID:** `{aid}`\n"
        f"🔑 **Pass:** `{apass}`\n"
        f"🛡️ **Access:** {perm_text}\n"
        f"-----------------------------\n"
        f"_Copy and forward this._"
    )
    await query.message.edit_text(msg, parse_mode="Markdown")
    return ConversationHandler.END

# --- CHANGE LOGIC (Syntax Error Fixed Here) ---
async def cl_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    curr = await get_logic_settings()
    curr.pop('_id', None)
    
    json_text = json.dumps(curr, indent=2)
    
    # I separated the string to avoid the syntax error
    msg = (
        f"⚙️ **Current Logic Settings:**\n"
        f"```json\n{json_text}\n```\n"
        f"To change, **Copy the JSON above**, edit values, and Send it back."
    )
    
    await update.callback_query.message.reply_text(msg, parse_mode="Markdown")
    return CL_INPUT

async def cl_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.replace("```json", "").replace("```", "").strip()
        new_logic = json.loads(text)
        await settings_collection.update_one({"type": "logic"}, {"$set": new_logic})
        await update.message.reply_text("✅ **Logic Updated!**", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    return ConversationHandler.END

# --- HELPERS ---
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_panel(update, context, "Unknown")
async def add_owner_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("Send ID:")
    return ADD_OWNER_TG_ID
async def add_owner_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await users_collection.insert_one({"telegram_id": int(update.message.text), "role": "OWNER"})
        await update.message.reply_text("✅ Owner Added")
    except: pass
    return ConversationHandler.END

# ==========================================
# ⚙️ MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print("⏳ Waiting 15s for old container to stop...")
    time.sleep(15)
    print("🚀 Starting Bot...")

    request = HTTPXRequest(connection_pool_size=8, read_timeout=30.0, write_timeout=30.0)
    app = Application.builder().token(BOT_TOKEN).request(request).build()
    
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={LOGIN_USER: [MessageHandler(filters.TEXT, login_user_input)], LOGIN_PASS: [MessageHandler(filters.TEXT, login_pass_input)]},
        fallbacks=[]
    )
    au_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(au_start, pattern="^add_user_start$")],
        states={AU_ID: [MessageHandler(filters.TEXT, au_id)], AU_PASS: [MessageHandler(filters.TEXT, au_pass)], AU_DAYS: [MessageHandler(filters.TEXT, au_final)]},
        fallbacks=[]
    )
    aa_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(aa_start, pattern="^add_admin_start$")],
        states={AA_ID: [MessageHandler(filters.TEXT, aa_id)], AA_PASS: [MessageHandler(filters.TEXT, aa_pass)], AA_DAYS: [MessageHandler(filters.TEXT, aa_days)], AA_PERM: [CallbackQueryHandler(aa_final, pattern="^perm_")]},
        fallbacks=[]
    )
    cl_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cl_start, pattern="^change_logic_start$")],
        states={CL_INPUT: [MessageHandler(filters.TEXT, cl_save)]},
        fallbacks=[]
    )
    ao_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_owner_start, pattern="^add_owner_start$")],
        states={ADD_OWNER_TG_ID: [MessageHandler(filters.TEXT, add_owner_save)]},
        fallbacks=[]
    )

    app.add_handler(login_conv)
    app.add_handler(au_conv)
    app.add_handler(aa_conv)
    app.add_handler(cl_conv)
    app.add_handler(ao_conv)
    
    app.add_handler(CallbackQueryHandler(owner_panel, pattern="^panel_owner$"))
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(get_pairs_handler, pattern="^get_pairs$"))
    app.add_handler(CallbackQueryHandler(pair_select_handler, pattern="^pair_")) 
    app.add_handler(CallbackQueryHandler(generate_signal_handler, pattern="^time_")) 

    print("✅ Bot Polling Started...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
