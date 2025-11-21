from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, String, Float, DateTime, ForeignKey, Integer, UniqueConstraint, Boolean
from datetime import datetime
from database import Base

# --- КОРИСТУВАЧІ ---
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str] = mapped_column(String, nullable=True)
    full_name: Mapped[str] = mapped_column(String, nullable=True)
    balance: Mapped[float] = mapped_column(Float, default=500.0)
    last_bonus_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    bank_balance: Mapped[float] = mapped_column(Float, default=0.0)
    last_interest_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, nullable=True)

    # --- НОВІ ПОЛЯ ---
    has_license: Mapped[bool] = mapped_column(Boolean, default=False) # Брокерська ліцензія
    vip_until: Mapped[datetime] = mapped_column(DateTime, nullable=True) # VIP статус (Інсайд)
    custom_title: Mapped[str] = mapped_column(String, nullable=True) # Кастомний титул
    
    clan_id: Mapped[int] = mapped_column(ForeignKey("clans.id"), nullable=True) # ID клану

# --- НОВА ТАБЛИЦЯ: ХЕДЖ-ФОНДИ (КЛАНИ) ---
class Clan(Base):
    __tablename__ = "clans"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id")) # Власник
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# --- НОВА ТАБЛИЦЯ: ЛОТЕРЕЯ ---
class LotteryTicket(Base):
    __tablename__ = "lottery_tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    purchased_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# ... (Решта моделей: Meme, Portfolio, PriceHistory, PromoCode, UsedPromo, News, Item, UserItem, Bet залишаються без змін) ...
# Скопіюй сюди старі моделі, щоб файл був повним, або просто додай нові класи до існуючого файлу.
# Я для скорочення не дублюю код Meme та інших, якщо ти їх не змінював.
class Meme(Base):
    __tablename__ = "memes"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), unique=True)
    current_price: Mapped[float] = mapped_column(Float)
    volatility: Mapped[float] = mapped_column(Float)
    image_url: Mapped[str] = mapped_column(String, nullable=True) 
    manipulation_mode: Mapped[str] = mapped_column(String, default="NONE")
    manipulation_remaining: Mapped[int] = mapped_column(Integer, default=0)
    trade_volume: Mapped[int] = mapped_column(Integer, default=0)

class Portfolio(Base):
    __tablename__ = "portfolio"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    meme_id: Mapped[int] = mapped_column(ForeignKey("memes.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint('user_id', 'meme_id', name='_user_meme_uc'),)

class PriceHistory(Base):
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    meme_id: Mapped[int] = mapped_column(ForeignKey("memes.id"))
    price: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class PromoCode(Base):
    __tablename__ = "promo_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    amount: Mapped[float] = mapped_column(Float)
    valid_until: Mapped[datetime] = mapped_column(DateTime)

class UsedPromo(Base):
    __tablename__ = "used_promos"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    promo_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id"))
    __table_args__ = (UniqueConstraint('user_id', 'promo_id', name='_user_promo_uc'),)

class News(Base):
    __tablename__ = "news"
    id: Mapped[int] = mapped_column(primary_key=True)
    meme_id: Mapped[int] = mapped_column(ForeignKey("memes.id"))
    ticker: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(String)
    change_percent: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    price: Mapped[float] = mapped_column(Float)
    emoji: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)

class UserItem(Base):
    __tablename__ = "user_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))

class Bet(Base):
    __tablename__ = "bets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    meme_id: Mapped[int] = mapped_column(ForeignKey("memes.id"))
    amount: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String) 
    start_price: Mapped[float] = mapped_column(Float)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)