import motor.motor_asyncio
from datetime import datetime, timedelta
import pytz

# --- MONGODB CONNECTION ---
# اپنی کنکشن اسٹرنگ یہاں ڈالیں
MONGO_URL = "mongodb://mongo:AEvrikOWlrmJCQrDTQgfGtqLlwhwLuAA@crossover.proxy.rlwy.net:29609"
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = client['trading_bot_db']

users_collection = db['users']
settings_collection = db['settings']

# --- DEFAULT OWNER SETUP (اگر ڈیٹا بیس خالی ہو تو یہ چلائیں) ---
async def init_db():
    # چیک کریں کہ کوئی ڈیفالٹ اونر ہے یا نہیں
    if await users_collection.count_documents({"role": "DEFAULT_OWNER"}) == 0:
        await users_collection.insert_one({
            "login_id": "superadmin",
            "password": "password123",
            "role": "DEFAULT_OWNER",
            "created_by": "SYSTEM",
            "expiry": None,  # کبھی ختم نہ ہو
            "telegram_id": None, # پہلی بار لاگ ان پر سیٹ ہوگا
            "is_blocked": False
        })
        print("Default Owner Created: ID: superadmin, Pass: password123")
    
    # ڈیفالٹ لوجک سیٹنگز
    if await settings_collection.count_documents({"type": "logic"}) == 0:
        await settings_collection.insert_one({
            "type": "logic",
            "ema_short": 50,
            "ema_long": 200,
            "rsi_period": 14,
            "macd_fast": 12,
            "macd_slow": 26,
            "rsi_upper": 60,
            "rsi_lower": 40
        })

# --- USER FUNCTIONS ---
async def get_user_by_login(login_id, password):
    return await users_collection.find_one({"login_id": login_id, "password": password})

async def get_user_by_tg_id(tg_id):
    return await users_collection.find_one({"telegram_id": tg_id})

async def create_user(creator_id, login_id, password, role, days, permissions=None):
    expiry_date = datetime.now() + timedelta(days=int(days))
    new_user = {
        "login_id": login_id,
        "password": password,
        "role": role,          # OWNER, ADMIN, USER
        "created_by": creator_id, # کس نے بنایا
        "expiry": expiry_date,
        "telegram_id": None,
        "is_blocked": False,
        "permissions": permissions # اگر ایڈمن ہے تو کیا اختیارات ہیں
    }
    await users_collection.insert_one(new_user)
