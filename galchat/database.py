import os
try:
    import tomllib
except ImportError:
    import tomli as tomllib
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from datetime import datetime

# 加载配置
current_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(current_dir, "config.toml")
with open(config_path, "rb") as f:
    config = tomllib.load(f)

db_config = config['MySQL']
DATABASE_URL = f"mysql+aiomysql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class DBUser(Base):
    __tablename__ = "users"
    ip_addr = Column(String(50), primary_key=True)
    last_seen = Column(DateTime, default=datetime.now)

class DBRoom(Base):
    __tablename__ = "rooms"
    room_id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.now)

class DBMessage(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(String(50), ForeignKey("rooms.room_id"), nullable=False)
    user_ip = Column(String(50), nullable=False)
    text = Column(Text, nullable=False)
    timestamp = Column(String(20), nullable=False) # 保持与现有格式一致

class DBUserRoom(Base):
    __tablename__ = "user_rooms"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_ip = Column(String(50), ForeignKey("users.ip_addr"), nullable=False)
    room_id = Column(String(50), ForeignKey("rooms.room_id"), nullable=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

if __name__ == "__main__":
    import asyncio
    asyncio.run(init_db())
    print("Database initialized successfully.")
