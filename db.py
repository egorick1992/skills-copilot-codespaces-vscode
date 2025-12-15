from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Enum
import enum
from datetime import datetime
import asyncio
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.getenv("DB_DIR", os.path.join(BASE_DIR, "data"))
DATABASE_URL = f"sqlite+aiosqlite:///{DB_DIR}/air_db.db"

# Создаем директорию если ее нет
os.makedirs(DB_DIR, exist_ok=True)

print(f"📁 Путь к базе данных: {DATABASE_URL}")

# Асинхронный движок
engine = create_async_engine(
    DATABASE_URL,
    echo=True if os.getenv("DEBUG", "0") == "1" else False,
    future=True,
    connect_args={"check_same_thread": False}  # Для SQLite в асинхронном режиме
)

# Асинхронная фабрика сессий
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()

# Статусы задачи
class TaskStatus(str, enum.Enum):
    active = "active"
    done = "done"
    closed = "closed"

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    is_public = Column(Boolean, default=False)
    user_id = Column(Integer, nullable=True, index=True)
    origin = Column(String, nullable=False)
    destination = Column(String, nullable=False)
    date_from = Column(String, nullable=False)  # Храним как строку
    date_to = Column(String, nullable=False)    # Храним как строку
    max_price = Column(Integer, nullable=True)
    return_days = Column(Integer, nullable=True)
    flex_days = Column(Integer, nullable=True)
    trip_class = Column(Integer, default=0)
    status = Column(Enum(TaskStatus), default=TaskStatus.active)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_checked_at = Column(DateTime, nullable=True)
    max_transfers = Column(Integer, nullable=True)
    retry_interval = Column(Integer, default=86400)

# Создание таблиц
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("База данных создана")

# Вызов init_db при старте
if __name__ == "__main__":
    asyncio.run(init_db())