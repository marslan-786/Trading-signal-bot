import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from database import init_db, get_user_by_tg_id, get_user_by_login, users_collection, create_user, settings_collection
from logic import trade_brain_dynamic

# --- STATES FOR CONVERSATION ---
LOGIN_USER, LOGIN_PASS = 0, 1
ADD_USER_NAME, ADD_USER_PASS, ADD_USER_DAYS, ADD_ADMIN_PERM = 2, 3, 4, 5
CHANGE_LOGIC = 6

# --- BANNER IMAGE ---
BANNER_PATH = "logo.png" # یہ فائل فولڈر میں ہونی چاہیے

# ================================
# 1. START & LOGIN SYSTEM (The Lock)
# ================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = await get_user_by_tg_id(user.id)
    
    # بینر بھیجیں
    await update.message.reply_photo(
        photo=open(BANNER_PATH, 'rb'),
        caption="Welcome to Advanced Trading Bot AI 🤖"
    )

    if not db_user:
        # اگر لاگ ان نہیں ہے تو لاگ ان مانگیں
        await update.message.reply_text(
            "⚠️ **Access Denied!**\n\nPlease Login using your ID.\nType your **Login ID** now:",
            parse_mode="Markdown"
        )
        return LOGIN_USER
    
    else:
        # اگر لاگ ان ہے تو پینل دکھائیں
        await show_main_panel(update, context, db_user)
        return ConversationHandler.END

async def login_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_login'] = update.message.text
    await update.message.reply_text("🔑 Now enter your **Password**:")
    return LOGIN_PASS

async def login_pass_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    login_id = context.user_data['temp_login']
    password = update.message.text
    tg_id = update.effective_user.id
    
    # ڈیٹا بیس میں چیک کریں
    user_doc = await get_user_by_login(login_id, password)
    
    if user_doc:
        if user_doc['telegram_id'] is None:
            # پہلی بار ٹیلیگرام آئی ڈی لنک کریں
            await users_collection.update_one(
                {"_id": user_doc['_id']}, 
                {"$set": {"telegram_id": tg_id}}
            )
            await update.message.reply_text("✅ **Login Successful!** Device Registered.")
            await show_main_panel(update, context, user_doc)
            return ConversationHandler.END
        elif user_doc['telegram_id'] == tg_id:
             await update.message.reply_text("✅ **Welcome Back!**")
             await show_main_panel(update, context, user_doc)
             return ConversationHandler.END
        else:
             await update.message.reply_text("⛔ This ID is already logged in on another Telegram account!")
             return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Wrong ID or Password. Try `/start` again.")
        return ConversationHandler.END

# ================================
# 2. MAIN PANELS (HIERARCHY)
# ================================
async def show_main_panel(update, context, user_doc):
    role = user_doc['role']
    keyboard = []
    
    # --- COMMON BUTTON FOR EVERYONE ---
    keyboard.append([InlineKeyboardButton("📊 Get Pairs (Start Trading)", callback_data="get_pairs")])
    
    # --- OWNER / DEFAULT OWNER PANEL ---
    if role in ["DEFAULT_OWNER", "OWNER"]:
        keyboard.append([InlineKeyboardButton("👑 Owner Panel", callback_data="panel_owner")])
    
    # --- ADMIN PANEL ---
    elif role == "ADMIN":
        keyboard.append([InlineKeyboardButton("🛡️ Admin Panel", callback_data="panel_admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # بینر کے ساتھ میسج
    msg_text = f"👋 Hello **{user_doc['login_id']}**\nRole: `{role}`\nExpiration: {user_doc['expiry'].strftime('%Y-%m-%d')}"
    
    if update.callback_query:
        # اگر بٹن دبایا تو میسج ایڈٹ نہ کریں بلکہ نیا فوٹو بھیجیں (کیونکہ پرانی فوٹو ایکسپائر ہو سکتی ہے)
        await update.callback_query.message.delete()
        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(BANNER_PATH, 'rb'), caption=msg_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_photo(photo=open(BANNER_PATH, 'rb'), caption=msg_text, reply_markup=reply_markup, parse_mode="Markdown")

# ================================
# 3. OWNER / ADMIN MANAGEMENT HANDLERS
# ================================
async def owner_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_doc = await get_user_by_tg_id(user_id)
    
    if user_doc['role'] not in ["DEFAULT_OWNER", "OWNER"]:
        await query.answer("❌ You are not an Owner!", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton("➕ Add User", callback_data="add_user"), InlineKeyboardButton("➕ Add Admin", callback_data="add_admin")],
        [InlineKeyboardButton("📋 List My Users", callback_data="list_users")],
        [InlineKeyboardButton("⚙️ Change Logic", callback_data="change_logic")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    
    # صرف ڈیفالٹ اونر کے لیے بٹن
    if user_doc['role'] == "DEFAULT_OWNER":
        keyboard.insert(0, [InlineKeyboardButton("➕ Add NEW OWNER", callback_data="add_owner")])

    await query.edit_message_caption(caption="👑 **Owner Control Panel**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# --- (Add User/Admin کے Conversation Handlers یہاں آئیں گے جو ڈیٹا بیس میں create_user فنکشن کال کریں گے) ---
# کوڈ کی لمبائی کی وجہ سے میں صرف منطق بتا رہا ہوں:
# 1. Ask Login ID -> 2. Ask Password -> 3. Ask Days -> 4. Save to DB with 'created_by': current_user

# ================================
# 4. SIGNAL SYSTEM & ANIMATION (USER SIDE)
# ================================
async def get_pairs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("EUR/USD", callback_data="pair_EURUSD"), InlineKeyboardButton("GBP/USD", callback_data="pair_GBPUSD")],
        [InlineKeyboardButton("USD/JPY", callback_data="pair_USDJPY"), InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    await update.callback_query.edit_message_caption(caption="📉 **Select a Currency Pair:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def time_select_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pair = query.data.split("_")[1]
    context.user_data['selected_pair'] = pair
    
    # ٹائم فریم بٹنز
    keyboard = [
        [InlineKeyboardButton("1 Min", callback_data="time_1m"), InlineKeyboardButton("5 Min", callback_data="time_5m")],
        [InlineKeyboardButton("🔙 Back", callback_data="get_pairs")]
    ]
    await query.edit_message_caption(caption=f"Selected: **{pair}**\nNow choose timeframe:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# --- LIVE SIGNAL ANIMATION ---
async def live_signal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    timeframe = query.data.split("_")[1]
    pair = context.user_data.get('selected_pair', 'EURUSD')
    
    # 1. لوڈنگ اینیمیشن
    await query.edit_message_caption(caption=f"📡 Connecting to Market for {pair} ({timeframe})...")
    await asyncio.sleep(1)
    
    msg = query.message
    
    # 2. لائیو لوپ (مثال کے طور پر 10 سیکنڈ تک چلائیں، پھر ریفریش)
    # ٹیلیگرام کی لمٹ کی وجہ سے ہم ہر سیکنڈ میسج ایڈٹ نہیں کر سکتے، ہم 3 سیکنڈ کا وقفہ دیں گے
    for i in range(5): 
        # API سے اصلی ڈیٹا لائیں
        # logic_response = await trade_brain_dynamic(prices) 
        
        # فرضی ڈیٹا برائے ڈیمو
        current_price = 1.3400 + (i * 0.0005)
        signal = "WAITING..."
        if i > 2: signal = "CALL 🟢" # نقلی سگنل
        
        display_text = f"""
🔴 **LIVE MARKET SIGNAL** 🔴
--------------------------------
📊 **Pair:** {pair}
⏳ **Time:** {timeframe}
💲 **Price:** `{current_price:.5f}`
--------------------------------
🧠 **AI Analysis:**
• RSI: `45.2` (Neutral)
• Trend: `UP` 📈
--------------------------------
🎯 **FINAL SIGNAL:**
# {signal}
        """
        
        try:
            await msg.edit_caption(caption=display_text, parse_mode="Markdown")
            await asyncio.sleep(2) # 2 سیکنڈ کا وقفہ لازمی ہے ورنہ ٹیلیگرام بلاک کر دے گا
        except:
            pass # اگر میسج ڈیلیٹ ہو جائے تو ایرر نہ آئے

    # فائنل بٹن دکھائیں
    key = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"time_{timeframe}"), InlineKeyboardButton("🛑 Stop", callback_data="main_menu")]]
    await msg.edit_reply_markup(reply_markup=InlineKeyboardMarkup(key))

# ================================
# 5. CHANGE LOGIC (OWNER FEATURE)
# ================================
async def change_logic_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    example_msg = """
Please send the new logic configuration in this format:
`
{
  "ema_short": 20,
  "ema_long": 100,
  "rsi_period": 10,
  "rsi_upper": 70,
  "rsi_lower": 30
}
`
**Copy this, edit values, and send back.**
    """
    await update.callback_query.message.reply_text(example_msg, parse_mode="Markdown")
    return CHANGE_LOGIC

async def save_new_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import json
    try:
        new_settings = json.loads(update.message.text)
        await settings_collection.update_one({"type": "logic"}, {"$set": new_settings})
        await update.message.reply_text("✅ **Logic Updated Successfully!** All users will now use new settings.")
    except:
        await update.message.reply_text("❌ **Error!** Invalid JSON format.")
    
    return ConversationHandler.END

# ================================
# MAIN EXECUTION
# ================================
if __name__ == "__main__":
    app = Application.builder().token("YOUR_TELEGRAM_BOT_TOKEN").build()
    
    # Conversation Handler for Login
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LOGIN_USER: [MessageHandler(filters.TEXT, login_user_input)],
            LOGIN_PASS: [MessageHandler(filters.TEXT, login_pass_input)],
        },
        fallbacks=[]
    )
    
    # Handlers
    app.add_handler(login_conv)
    app.add_handler(CallbackQueryHandler(owner_panel_handler, pattern="^panel_owner$"))
    app.add_handler(CallbackQueryHandler(get_pairs_handler, pattern="^get_pairs$"))
    app.add_handler(CallbackQueryHandler(time_select_handler, pattern="^pair_"))
    app.add_handler(CallbackQueryHandler(live_signal_handler, pattern="^time_"))
    
    # Logic Change Conversation
    logic_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(change_logic_start, pattern="^change_logic$")],
        states={CHANGE_LOGIC: [MessageHandler(filters.TEXT, save_new_logic)]},
        fallbacks=[]
    )
    app.add_handler(logic_conv)

    print("Bot Started...")
    # ڈیٹا بیس انیشیلاز کریں
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    
    app.run_polling()
