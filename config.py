import os
from dotenv import load_dotenv
from aiogram.filters import Filter
from aiogram.types import Message

load_dotenv()

class Config:
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
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

if not Config.BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing in .env file!")

ADMIN_IDS = [6500735335, 123456789] 

class IsAdmin(Filter):
    async def __call__(self, message: Message) -> bool:

        return message.from_user.id in ADMIN_IDS
