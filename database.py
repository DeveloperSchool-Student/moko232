from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from config import Config

# Створення асинхронного рушія SQLAlchemy
engine = create_async_engine(Config.DB_URL, echo=False)

# Фабрика сесій для взаємодії з БД
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# Базовий клас для всіх моделей (таблиць)
class Base(DeclarativeBase):
    pass

# Функція для ініціалізації таблиць (створення, якщо не існують)
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)