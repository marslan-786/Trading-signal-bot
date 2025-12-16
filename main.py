import asyncio
import time
import json
import random
import math  # ٹرینڈ کو اسٹیبل کرنے کے لیے
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.request import HTTPXRequest
from telegram.error import BadRequest, TimedOut, NetworkError
import motor.motor_asyncio

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
DEFAULT_OWNER_ID = 8167904992
BOT_TOKEN = "8487438477:AAH6IbeGJnPXEvhGpb4TSAdJmzC0fXaa0Og"
MONGO_URL = "mongodb://mongo:AEvrikOWlrmJCQrDTQgfGtqLlwhwLuAA@crossover.proxy.rlwy.net:29609"
BANNER_IMAGE_URL = "https://i.imgur.com/8QS1M4A.png" 

# --- DEFAULT LOGIC ---
DEFAULT_LOGIC_CONFIG = {
    "ema_short": 50, "ema_long": 200,
    "rsi_period": 14,
    "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
    "call_rsi_min": 40, "call_rsi_max": 55,
    "put_rsi_min": 45, "put_rsi_max": 60
}

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
# 🧠 STABLE TRADE BRAIN
# ==========================================
async def get_logic_settings():
    settings = await settings_collection.find_one({"type": "logic"})
    if not settings:
        await settings_collection.insert_one({"type": "logic", **DEFAULT_LOGIC_CONFIG})
        return DEFAULT_LOGIC_CONFIG
    return settings

def calculate_signal(prices, config):
    # 1. اگر ڈیٹا کم ہے تو کچھ نہ کہیں
    if len(prices) < config['ema_long']: return "WAIT ⏳"

    # 2. انڈیکیٹرز کا حساب
    ema_short = sum(prices[-config['ema_short']:]) / config['ema_short']
    ema_long = sum(prices[-config['ema_long']:]) / config['ema_long']
    
    gains, losses = [], []
    for i in range(-config['rsi_period'], 0):
        change = prices[i] - prices[i-1]
        if change > 0: gains.append(change); losses.append(0)
        else: gains.append(0); losses.append(abs(change))
    avg_gain = sum(gains) / len(gains) if gains else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss != 0 else 50
    
    short_ema = sum(prices[-config['macd_fast']:]) / config['macd_fast']
    long_ema = sum(prices[-config['macd_slow']:]) / config['macd_slow']
    macd = short_ema - long_ema

    # 3. اسٹیبل فیصلہ (Trend Bias)
    # ہم صرف تب فیصلہ بدلیں گے جب ٹرینڈ واضح ہو۔
    # چھوٹے RSI کے جھٹکوں کو نظر انداز کریں گے۔
    
    signal = "HOLD 😐" # ڈیفالٹ

    # STRONG UPTREND (CALL)
    # اگر 50 EMA اوپر ہے اور 200 EMA نیچے ہے (واضح ٹرینڈ)
    if ema_short > ema_long:
        # RSI چیک کریں (کیا یہ سیف زون میں ہے؟)
        if config['call_rsi_min'] < rsi < config['call_rsi_max']:
             if macd > 0:
                 signal = "CALL 🟢"
    
    # STRONG DOWNTREND (PUT)
    elif ema_short < ema_long:
        # RSI چیک کریں
        if config['put_rsi_min'] < rsi < config['put_rsi_max']:
            if macd < 0:
                signal = "PUT 🔴"
        
    return signal

def get_progress_bar():
    now = datetime.now()
    seconds = now.second
    # خوبصورت بار
    total_blocks = 12
    filled_blocks = int((seconds / 60) * total_blocks)
    
    # ⬛️ = Empty, 🟩 = Filled
    bar = "🟩" * filled_blocks + "▫️" * (total_blocks - filled_blocks)
    return bar, 60 - seconds

# ==========================================
# 🚀 HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        if user.id == DEFAULT_OWNER_ID:
            await users_collection.update_one({"telegram_id": user.id}, {"$set": {"role": "DEFAULT_OWNER", "login_id": "BOSS"}}, upsert=True)
            await show_main_panel(update, context, "DEFAULT_OWNER")
            return ConversationHandler.END

        user_doc = await users_collection.find_one({"telegram_id": user.id})
        if user_doc:
            await show_main_panel(update, context, user_doc['role'])
            return ConversationHandler.END
            
        await update.message.reply_text("🔒 **System Locked**\nEnter Login ID:", parse_mode="Markdown")
        return LOGIN_USER
    except:
        await update.message.reply_text("⚠️ Restarting... Try /start again.")

async def login_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_login'] = update.message.text
    await update.message.reply_text("🔑 Enter Password:")
    return LOGIN_PASS

async def login_pass_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    login_id = context.user_data['temp_login']
    password = update.message.text
    user = await users_collection.find_one({"login_id": login_id, "password": password})
    if user:
        if not user.get("telegram_id") or user.get("telegram_id") == update.effective_user.id:
            await users_collection.update_one({"_id": user["_id"]}, {"$set": {"telegram_id": update.effective_user.id}})
            await show_main_panel(update, context, user['role'])
        else: await update.message.reply_text("⛔ Device Mismatch!")
    else: await update.message.reply_text("❌ Invalid Credentials")
    return ConversationHandler.END

async def show_main_panel(update, context, role):
    keyboard = [[InlineKeyboardButton("📊 Get Pairs", callback_data="get_pairs")]]
    if role in ["DEFAULT_OWNER", "OWNER"]: keyboard.append([InlineKeyboardButton("👑 Owner Panel", callback_data="panel_owner")])
    elif role == "ADMIN": keyboard.append([InlineKeyboardButton("🛡️ Admin Panel", callback_data="panel_admin")])

    msg = f"👋 **Welcome Boss!**\nRole: `{role}`"
    chat_id = update.effective_chat.id
    if update.callback_query:
        try: await update.callback_query.message.delete()
        except: pass

    try: await context.bot.send_photo(chat_id=chat_id, photo=BANNER_IMAGE_URL, caption=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except: await context.bot.send_message(chat_id=chat_id, text=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def get_pairs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("EUR/USD", callback_data="pair_EURUSD"), InlineKeyboardButton("GBP/USD", callback_data="pair_GBPUSD")],
        [InlineKeyboardButton("USD/JPY", callback_data="pair_USDJPY"), InlineKeyboardButton("BTC/USD", callback_data="pair_BTCUSD")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    try: await query.message.edit_caption(caption="📉 **Select Market Pair:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except: await query.message.edit_text(text="📉 **Select Market Pair:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def pair_select_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['pair'] = query.data.split("_")[1]
    
    keyboard = [
        [InlineKeyboardButton("1 Min", callback_data="time_1m"), InlineKeyboardButton("5 Min", callback_data="time_5m")],
        [InlineKeyboardButton("15 Min", callback_data="time_15m"), InlineKeyboardButton("30 Min", callback_data="time_30m")],
        [InlineKeyboardButton("🔙 Back", callback_data="get_pairs")]
    ]
    try: await query.message.edit_caption(caption=f"📉 Pair: **{context.user_data['pair']}**\nSelect timeframe:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except: await query.message.edit_text(text=f"📉 Pair: **{context.user_data['pair']}**\nSelect timeframe:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ==========================================
# ⚡️ FINAL CARD STYLE SIGNAL
# ==========================================
async def generate_signal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    pair = context.user_data.get('pair', 'EURUSD')
    timeframe = query.data.split("_")[1]
    stop_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 STOP", callback_data="stop_live")]])
    
    try: msg = await query.message.edit_caption(caption="🔄 **Loading Strategy...**", parse_mode="Markdown")
    except: msg = await query.message.edit_text(text="🔄 **Loading Strategy...**", parse_mode="Markdown")

    context.user_data['is_live'] = True
    
    # ٹرینڈ ویو کے لیے ایک مصنوعی "Sine Wave" تاکہ ٹیسٹ میں سگنل بار بار نہ بدلے
    # اصلی API میں یہ کوڈ ہٹا دیا جائے گا کیونکہ وہاں اصلی قیمت ہوگی
    counter = 0 

    while context.user_data.get('is_live', False):
        try:
            # --- STABLE MOCK DATA ---
            # یہ کوڈ قیمت کو ایک سمت میں لے کر جائے گا تاکہ ٹرینڈ بنے
            counter += 1
            trend_direction = math.sin(counter / 10) # Smooth wave
            base_price = 1.0500 + (trend_direction * 0.0020)
            
            # 200 کینڈلز جنریٹ کریں (Trend Based)
            prices = [base_price + random.uniform(-0.0005, 0.0005) for _ in range(250)]
            
            # --- LOGIC ---
            config = await get_logic_settings()
            signal = calculate_signal(prices, config)
            
            # --- PROGRESS BAR ---
            bar, seconds_left = get_progress_bar()
            
            # --- CARD DESIGN (Quote Block) ---
            # سائیڈ لائن کے لیے '>' کا استعمال
            # AI Analysis کو ہٹا دیا گیا ہے
            
            res_text = (
                f"📊 **MARKET ANALYSIS**\n"
                f"🆔 Pair: `{pair}`\n"
                f"⏱ Time: `{timeframe}`\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"> 🔥 **FINAL DECISION**\n"
                f"> ━━━━━━━━━━━━━\n"
                f"> \n"
                f">      # {signal}      \n"
                f"> \n"
                f"> ━━━━━━━━━━━━━\n\n"
                f"⏳ **Closing in:** {seconds_left}s\n"
                f"{bar}"
            )
            
            await msg.edit_caption(caption=res_text, reply_markup=stop_keyboard, parse_mode="Markdown")
            await asyncio.sleep(3) # 3 سیکنڈ کا وقفہ
            
        except BadRequest:
            await asyncio.sleep(3)
            continue
        except Exception as e:
            break

async def stop_live_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🛑 Stopped!")
    context.user_data['is_live'] = False
    await get_pairs_handler(update, context)

# ==========================================
# 👑 OWNER & ADMIN (Simplified)
# ==========================================
# (میں نے پچھلے کوڈ کے کنورسیشن ہینڈلرز شامل کیے ہیں، یہ جگہ بچانے کے لیے شارٹ کر رہا ہوں)
# آپ کو مین فنکشن میں وہی کنورسیشن ہینڈلرز رکھنے ہوں گے جو پچھلی فائل میں تھے

async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # (Same as before)
    query = update.callback_query
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
    await query.message.edit_caption(caption="👑 **Owner Panel**", reply_markup=InlineKeyboardMarkup(keyboard))

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_panel(update, context, "Unknown")

# ==========================================
# ⚙️ MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print("⏳ Waiting 2s...")
    time.sleep(2)
    print("🚀 Starting Bot...")

    request = HTTPXRequest(connection_pool_size=8, read_timeout=30.0, write_timeout=30.0)
    app = Application.builder().token(BOT_TOKEN).request(request).build()
    
    # --- CONVERSATIONS ---
    # (Paste the AU_CONV, AA_CONV, CL_CONV here from previous code if needed)
    # For now, keeping Login only to show the Signal fix
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={LOGIN_USER: [MessageHandler(filters.TEXT, login_user_input)], LOGIN_PASS: [MessageHandler(filters.TEXT, login_pass_input)]},
        fallbacks=[]
    )
    app.add_handler(login_conv)
    
    app.add_handler(CallbackQueryHandler(owner_panel, pattern="^panel_owner$"))
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(get_pairs_handler, pattern="^get_pairs$"))
    app.add_handler(CallbackQueryHandler(pair_select_handler, pattern="^pair_")) 
    
    # LIVE SIGNAL
    app.add_handler(CallbackQueryHandler(generate_signal_handler, pattern="^time_"))
    app.add_handler(CallbackQueryHandler(stop_live_handler, pattern="^stop_live$"))

    print("✅ Bot Started! Send /start")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
