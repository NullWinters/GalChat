import os
try:
    import tomllib
except ImportError:
    import tomli as tomllib
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, text, UniqueConstraint, Index
from sqlalchemy.orm import relationship, sessionmaker, declarative_base
from datetime import datetime

# 加载配置
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
config_path = os.path.join(project_root, "config.toml")
with open(config_path, "rb") as f:
    config = tomllib.load(f)

db_config = config['MySQL']
DATABASE_URL = f"mysql+aiomysql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}"
BACKUP_DB_NAME = "galchat_backup"
BACKUP_DATABASE_URL = f"mysql+aiomysql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{BACKUP_DB_NAME}"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# 备份引擎
backup_engine = create_async_engine(BACKUP_DATABASE_URL, echo=False)

class DBUser(Base):
    __tablename__ = "users"
    ip_addr = Column(String(50), primary_key=True)
    last_seen = Column(DateTime, default=datetime.now)

    # 关系
    messages = relationship("DBMessage", back_populates="user")
    memberships = relationship("DBUserRoom", back_populates="user")

class DBRoom(Base):
    __tablename__ = "rooms"
    room_id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    # 关系
    messages = relationship("DBMessage", back_populates="room", cascade="all, delete-orphan")
    members = relationship("DBUserRoom", back_populates="room", cascade="all, delete-orphan")

class DBFile(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True, autoincrement=True)
    digest = Column(String(64), unique=True, nullable=False)
    file_path = Column(String(255), nullable=False)

    # 关系
    messages = relationship("DBMessage", back_populates="file")

class DBMessage(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(String(50), ForeignKey("rooms.room_id"), nullable=False, index=True)
    user_ip = Column(String(50), ForeignKey("users.ip_addr"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.now, nullable=False, index=True)
    message_type = Column(String(20), default="text")
    file_id = Column(Integer, ForeignKey("files.id"), nullable=True)

    # 关系
    room = relationship("DBRoom", back_populates="messages")
    user = relationship("DBUser", back_populates="messages")
    file = relationship("DBFile", back_populates="messages")

class DBAvatar(Base):
    __tablename__ = "avatars"
    id = Column(Integer, primary_key=True, autoincrement=True)
    digest = Column(String(64), unique=True, nullable=False)
    avatar_path = Column(String(255), nullable=False)

    # 关系
    user_rooms = relationship("DBUserRoom", back_populates="avatar")

class DBUserRoom(Base):
    __tablename__ = "user_rooms"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_ip = Column(String(50), ForeignKey("users.ip_addr"), nullable=False, index=True)
    room_id = Column(String(50), ForeignKey("rooms.room_id"), nullable=False, index=True)
    nickname = Column(String(100), nullable=True)
    avatar_id = Column(Integer, ForeignKey("avatars.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint('user_ip', 'room_id', name='_user_room_uc'),
    )

    # 关系
    user = relationship("DBUser", back_populates="memberships")
    room = relationship("DBRoom", back_populates="members")
    avatar = relationship("DBAvatar", back_populates="user_rooms")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def clear_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

async def backup_db():
    """备份数据库"""
    # 1. 确保备份数据库存在
    # 使用不带数据库名的URL连接来创建数据库
    ROOT_URL = f"mysql+aiomysql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/"
    root_engine = create_async_engine(ROOT_URL, echo=False)
    async with root_engine.begin() as conn:
        await conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {BACKUP_DB_NAME}"))
    await root_engine.dispose()

    # 2. 初始化备份数据库结构
    async with backup_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 3. 复制数据
    # 由于使用异步 SQLAlchemy 进行跨库大批量数据迁移较为复杂，
    # 这里我们采用简单的逐表查询并插入的方式
    # 注意：删除和插入顺序需要考虑外键约束
    tables = ["user_rooms", "messages", "avatars", "files", "rooms", "users"]
    
    async with engine.connect() as source_conn:
        async with backup_engine.connect() as target_conn:
            # 首先清空所有目标表（按引用的反序）
            # 在清空前临时禁用外键检查，以确保万无一失，虽然顺序已经考虑了
            await target_conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for table_name in tables:
                await target_conn.execute(text(f"TRUNCATE TABLE {table_name}"))
            await target_conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            
            # 然后按依赖正序复制数据
            for table_name in reversed(tables):
                # 获取源数据
                result = await source_conn.execute(text(f"SELECT * FROM {table_name}"))
                rows = result.fetchall()
                
                if rows:
                    # 获取列名
                    keys = result.keys()
                    
                    # 构造插入语句
                    placeholders = ", ".join([f":{k}" for k in keys])
                    insert_stmt = text(f"INSERT INTO {table_name} ({', '.join(keys)}) VALUES ({placeholders})")
                    
                    # 批量插入
                    # rows 是 Row 对象列表，需要转为字典
                    data = [dict(row._mapping) for row in rows]
                    await target_conn.execute(insert_stmt, data)
            
            await target_conn.commit()

if __name__ == "__main__":
    import asyncio
    asyncio.run(init_db())
    print("Database initialized successfully.")
