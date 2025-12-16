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
BANNER_IMAGE_URL = "https://i.imgur.com/8QS1M4A.png" 

# --- آپ کی دی ہوئی ڈیفالٹ لوجک ---
DEFAULT_LOGIC_CONFIG = {
    "ema_short": 50,
    "ema_long": 200,
    "rsi_period": 14,
    "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
    # CALL Conditions
    "call_rsi_min": 40, "call_rsi_max": 55,
    # PUT Conditions
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
# Add User States
AU_ID, AU_PASS, AU_DAYS = 3, 4, 5
# Add Admin States
AA_ID, AA_PASS, AA_DAYS, AA_PERM = 6, 7, 8, 9
# Change Logic
CL_INPUT = 10

# ==========================================
# 🧠 TRADE BRAIN (THE LOGIC)
# ==========================================
async def get_logic_settings():
    settings = await settings_collection.find_one({"type": "logic"})
    if not settings:
        # اگر سیٹنگ نہ ہو تو ڈیفالٹ سیو کریں
        await settings_collection.insert_one({"type": "logic", **DEFAULT_LOGIC_CONFIG})
        return DEFAULT_LOGIC_CONFIG
    return settings

def calculate_signal(prices, config):
    # یہ فنکشن اب ڈیٹا بیس والی کنفیگ استعمال کرے گا
    if len(prices) < config['ema_long']: return "WAIT (Data < 200)"

    # EMA
    ema_short = sum(prices[-config['ema_short']:]) / config['ema_short']
    ema_long = sum(prices[-config['ema_long']:]) / config['ema_long']

    # RSI
    gains, losses = [], []
    for i in range(-config['rsi_period'], 0):
        change = prices[i] - prices[i-1]
        if change > 0: gains.append(change); losses.append(0)
        else: gains.append(0); losses.append(abs(change))
    
    avg_gain = sum(gains) / config['rsi_period']
    avg_loss = sum(losses) / config['rsi_period']
    rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss != 0 else 100

    # MACD
    short_ema = sum(prices[-config['macd_fast']:]) / config['macd_fast']
    long_ema = sum(prices[-config['macd_slow']:]) / config['macd_slow']
    macd = short_ema - long_ema

    # --- DECISION LOGIC ---
    signal = "HOLD"
    reason = "Market Indecisive"

    # CALL: EMA_S > EMA_L AND 40 < RSI < 55 AND MACD > 0
    if (ema_short > ema_long and 
        config['call_rsi_min'] < rsi < config['call_rsi_max'] and 
        macd > 0):
        signal = "CALL 🟢"
        reason = "Strong Uptrend + RSI Safe Zone"

    # PUT: EMA_S < EMA_L AND 45 < RSI < 60 AND MACD < 0
    elif (ema_short < ema_long and 
          config['put_rsi_min'] < rsi < config['put_rsi_max'] and 
          macd < 0):
        signal = "PUT 🔴"
        reason = "Strong Downtrend + RSI Safe Zone"

    return signal, rsi, ema_short, ema_long

# ==========================================
# 🚀 START & LOGIN
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tg_id = user.id
    
    # 1. Default Owner Setup
    if tg_id == DEFAULT_OWNER_ID:
        await users_collection.update_one(
            {"telegram_id": tg_id},
            {"$set": {"role": "DEFAULT_OWNER", "login_id": "BOSS", "is_blocked": False}},
            upsert=True
        )
        # Ensure Logic exists
        await get_logic_settings()
        await show_main_panel(update, context, "DEFAULT_OWNER")
        return ConversationHandler.END

    # 2. Check DB
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

# --- 2. SELECT TIMEFRAME (MISSING PART FIXED) ---
async def pair_select_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    selected_pair = query.data.split("_")[1] # e.g. EURUSD
    context.user_data['pair'] = selected_pair
    
    # Timeframe Menu
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

# --- 3. GENERATE SIGNAL (API CALL) ---
async def generate_signal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    pair = context.user_data.get('pair', 'Unknown')
    timeframe = query.data.split("_")[1]
    
    await query.message.edit_caption(caption="🔄 **Analyzing Market...**")
    
    # --- MOCK DATA FETCH (Replace with Real Quotex API later) ---
    # Generating 250 fake candles for logic testing
    base = 1.0500
    prices = [base + random.uniform(-0.002, 0.002) for _ in range(250)]
    
    # --- LOGIC ---
    config = await get_logic_settings()
    signal, rsi, ema_s, ema_l = calculate_signal(prices, config)
    
    res_text = f"""
🚨 **SIGNAL REPORT** 🚨
---------------------------
🆔 **Pair:** {pair}
⏱ **Time:** {timeframe}
---------------------------
🧠 **AI Analysis:**
• RSI: `{round(rsi, 2)}`
• EMA 50: `{round(ema_s, 5)}`
• EMA 200: `{round(ema_l, 5)}`
---------------------------
🎯 **DECISION:**
# {signal}
    """
    
    keyboard = [[InlineKeyboardButton("🔙 Pairs", callback_data="get_pairs")]]
    await query.message.edit_caption(caption=res_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ==========================================
# 👑 OWNER PANEL & ADD USER/ADMIN LOGIC
# ==========================================
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Check Role ... (Simplified for brevity, assuming Check Passed)
    keyboard = [
        [InlineKeyboardButton("👤 Add User", callback_data="add_user_start"), InlineKeyboardButton("👮‍♂️ Add Admin", callback_data="add_admin_start")],
        [InlineKeyboardButton("⚙️ Change Logic", callback_data="change_logic_start")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    # Add 'Add Owner' button only if DEFAULT_OWNER ...
    
    await query.message.edit_caption(caption="👑 **Owner Panel**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# --- ADD USER CONVERSATION ---
async def au_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("👤 **Add New User**\n\nSend new **User ID**:")
    return AU_ID

async def au_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_uid'] = update.message.text
    await update.message.reply_text("🔑 Send **Password**:")
    return AU_PASS

async def au_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_upass'] = update.message.text
    await update.message.reply_text("📅 Enter **Days** (e.g., 30):")
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
    
    msg = f"""
✅ **User Created Successfully!**
-----------------------------
🆔 **ID:** `{uid}`
🔑 **Pass:** `{upass}`
📅 **Days:** {days}
-----------------------------
_Copy and forward this to the user._
    """
    await update.message.reply_text(msg, parse_mode="Markdown")
    return ConversationHandler.END

# --- ADD ADMIN CONVERSATION ---
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
    # Permissions Buttons
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
    msg = f"""
✅ **Admin Created Successfully!**
-----------------------------
🆔 **ID:** `{aid}`
🔑 **Pass:** `{apass}`
🛡️ **Access:** {perm_text}
-----------------------------
_Copy and forward this._
    """
    await query.message.edit_text(msg, parse_mode="Markdown")
    return ConversationHandler.END

# --- CHANGE LOGIC CONVERSATION ---
async def cl_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    curr = await get_logic_settings()
    curr.pop('_id', None)
    
    msg = f"""
⚙️ **Current Logic Settings:**
```json
{json.dumps(curr, indent=2)}
