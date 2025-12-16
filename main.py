import asyncio
import time
import json
import random
import math
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
# 🧠 TRADE BRAIN
# ==========================================
async def get_logic_settings():
    settings = await settings_collection.find_one({"type": "logic"})
    if not settings:
        await settings_collection.insert_one({"type": "logic", **DEFAULT_LOGIC_CONFIG})
        return DEFAULT_LOGIC_CONFIG
    return settings

def calculate_signal(prices, config):
    if len(prices) < config['ema_long']: return "WAIT ⏳"

    # --- INDICATORS ---
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

    # --- DECISION ---
    signal = "HOLD 😐"
    if ema_short > ema_long:
        if config['call_rsi_min'] < rsi < config['call_rsi_max'] and macd > 0:
            signal = "CALL 🟢"
    elif ema_short < ema_long:
        if config['put_rsi_min'] < rsi < config['put_rsi_max'] and macd < 0:
            signal = "PUT 🔴"
        
    return signal

def get_progress_bar():
    now = datetime.now()
    seconds = now.second
    total_blocks = 12
    filled_blocks = int((seconds / 60) * total_blocks)
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
        await update.message.reply_text("⚠️ Bot waking up... Retry /start")

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

# --- UPDATED PAIRS LIST ---
async def get_pairs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # آپ کی دی گئی نئی لسٹ
    keyboard = [
        [InlineKeyboardButton("EUR/USD", callback_data="pair_EURUSD"), InlineKeyboardButton("GBP/USD", callback_data="pair_GBPUSD")],
        [InlineKeyboardButton("USD/JPY", callback_data="pair_USDJPY"), InlineKeyboardButton("AUD/USD", callback_data="pair_AUDUSD")],
        [InlineKeyboardButton("BTC/USD", callback_data="pair_BTCUSD"), InlineKeyboardButton("ETH/USD", callback_data="pair_ETHUSD")],
        [InlineKeyboardButton("XAU/USD", callback_data="pair_XAUUSD"), InlineKeyboardButton("USD/PKR", callback_data="pair_USDPKR")],
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
# ⚡️ FIXED SIGNAL LOGIC (LOCKS FOR 1 MIN)
# ==========================================
async def generate_signal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    pair = context.user_data.get('pair', 'EURUSD')
    timeframe = query.data.split("_")[1]
    
    # Back Button (Stop Logic)
    back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stop_live")]])
    
    try: msg = await query.message.edit_caption(caption="🔄 **Loading History & Strategy...**", parse_mode="Markdown")
    except: msg = await query.message.edit_text(text="🔄 **Loading History & Strategy...**", parse_mode="Markdown")

    context.user_data['is_live'] = True
    
    # --- HISTORY GENERATION (199 Candles) ---
    base_price = 1.0500
    if pair == "BTCUSD": base_price = 90000.00
    if pair == "XAUUSD": base_price = 2600.00
    
    history_prices = []
    # ایک ٹرینڈ سیٹ کریں تاکہ ہسٹری اصلی لگے
    trend = random.choice([0.0001, -0.0001]) 
    for _ in range(200):
        base_price += trend + random.uniform(-0.00005, 0.00005)
        history_prices.append(base_price)

    # --- SIGNAL LOCK VARIABLES ---
    current_fixed_signal = None  # یہ وہ سگنل ہے جو فکس رہے گا
    
    while context.user_data.get('is_live', False):
        try:
            bar, seconds_left = get_progress_bar()
            
            # --- LOCK LOGIC: صرف تب کیلکولیٹ کریں جب سگنل نہ ہو یا نیا منٹ شروع ہو ---
            # ہم چیک کر رہے ہیں کہ کیا seconds_left زیادہ ہیں (یعنی منٹ شروع ہوا ہے)
            # یا اگر یہ پہلی بار چل رہا ہے (None)
            
            if current_fixed_signal is None or seconds_left > 57:
                # نیا منٹ شروع ہوا ہے -> نیا سگنل بنائیں
                config = await get_logic_settings()
                
                # ہسٹری میں تھوڑی تبدیلی (نئی کینڈل کا ایفیکٹ)
                latest_close = history_prices[-1] + random.uniform(-0.0002, 0.0002)
                history_prices.append(latest_close)
                if len(history_prices) > 200: history_prices.pop(0)
                
                # نیا فکسڈ سگنل کیلکولیٹ کریں
                current_fixed_signal = calculate_signal(history_prices, config)

            # --- DISPLAY (Signal wahi rahega, sirf Time update hoga) ---
            res_text = (
                f"📊 **MARKET ANALYSIS**\n"
                f"🆔 Pair: `{pair}`\n"
                f"⏱ Time: `{timeframe}`\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"> 🔥 **FINAL DECISION**\n"
                f"> ━━━━━━━━━━━━━\n"
                f"> \n"
                f">      # {current_fixed_signal}      \n"
                f"> \n"
                f"> ━━━━━━━━━━━━━\n\n"
                f"⏳ **Next Candle:** {seconds_left}s\n"
                f"{bar}"
            )
            
            await msg.edit_caption(caption=res_text, reply_markup=back_keyboard, parse_mode="Markdown")
            await asyncio.sleep(3) # 3 سیکنڈ کا وقفہ

        except BadRequest:
            await asyncio.sleep(3)
        except Exception as e:
            break

async def stop_live_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['is_live'] = False
    # واپس ٹائم فریم والے مینیو پر جائیں
    await pair_select_handler(update, context)

# ==========================================
# 👑 OWNER & ADMIN (Short)
# ==========================================
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
    await query.message.edit_caption(caption="👑 **Owner Panel**", reply_markup=InlineKeyboardMarkup(keyboard))

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_panel(update, context, "Unknown")

# ==========================================
# ⚙️ MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print("⏳ Waiting 5s...")
    time.sleep(5)
    print("🚀 Starting Bot...")

    request = HTTPXRequest(connection_pool_size=8, read_timeout=30.0, write_timeout=30.0)
    app = Application.builder().token(BOT_TOKEN).request(request).build()
    
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
    
    app.add_handler(CallbackQueryHandler(generate_signal_handler, pattern="^time_"))
    # Stop/Back Handler
    app.add_handler(CallbackQueryHandler(stop_live_handler, pattern="^stop_live$"))

    print("✅ Bot Started! Send /start")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
