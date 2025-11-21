import os
from dotenv import load_dotenv
from aiogram.filters import Filter
from aiogram.types import Message

load_dotenv()

class Config:
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    # --- ЛОГІКА БАЗИ ДАНИХ ---
    # Отримуємо посилання від Render (або Neon)
    _db_url = os.environ.get("DATABASE_URL")
    
    if _db_url:
        # --- ВИПРАВЛЕННЯ ТУТ ---
        # Якщо посилання починається з "postgres://", міняємо на асинхронне
        if _db_url.startswith("postgres://"):
            _db_url = _db_url.replace("postgres://", "postgresql+asyncpg://", 1)
        # Якщо посилання починається з "postgresql://", теж міняємо (ось цього не вистачало)
        elif _db_url.startswith("postgresql://"):
            _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            
        DB_URL = _db_url
    else:
        # Якщо змінної немає, використовуємо локальний файл (як раніше)
        DB_URL = "sqlite+aiosqlite:///meme_exchange.db"
    
    # --- ЕКОНОМІКА ---
    MARKET_IMPACT_FACTOR = 0.002
    NEWS_THRESHOLD = 0.10
    
    # Комісії
    SELL_COMMISSION_DEFAULT = 0.03 # 3%
    SELL_COMMISSION_BROKER = 0.01  # 1% (для власників ліцензії)
    
    # Ставки
    BET_PROFIT_FACTOR = 1.8
    BET_DURATION = 65

    # --- ЦІНИ НА ПОСЛУГИ ---
    LICENSE_COST = 50000.0       # Ліцензія брокера
    VIP_COST = 5000.0            # Інсайд (VIP) на 1 годину
    LOTTERY_TICKET = 500.0       # Квиток лотереї
    CLAN_CREATION_COST = 1000000.0 # Створення Хедж-фонду
    TITLE_CHANGE_COST = 10000.0  # Зміна титулу

# Перевірка на всяк випадок
if not Config.BOT_TOKEN:
     # Щоб локально не падало, якщо немає змінних, але на Render вони є
    pass

ADMIN_IDS = [6500735335, 123456789] 

class IsAdmin(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in ADMIN_IDS
