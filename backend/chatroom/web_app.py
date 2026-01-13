import os
import sys
import json
import hashlib
import shutil
import asyncio
import bleach
import io
from PIL import Image
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, UploadFile, File

# 将项目根目录添加到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

from sqlalchemy import select, delete
from sqlalchemy.orm import joinedload
from backend.ai.agent import Generator
from backend.common.utils import _get_now_time as get_now_time
from backend.database.database import AsyncSessionLocal, DBRoom, DBMessage, DBUser, DBUserRoom, DBFile, DBAvatar, init_db, clear_db, backup_db

# 加载 App 配置以支持分享功能
try:
    import tomllib
except ImportError:
    import tomli as tomllib

def load_app_config():
    config_path = os.path.join(project_root, "config.toml")
    with open(config_path, "rb") as f:
        config = tomllib.load(f)
    return config.get("App", {})

def sanitize_text(text: str) -> str:
    """清理文本，防止 XSS"""
    if not text:
        return ""
    # 默认不允许任何标签
    return bleach.clean(text, tags=[], attributes={}, strip=True)

app = FastAPI(title="GalChat Web API")

@app.on_event("startup")
async def startup_event():
    config = load_app_config()
    if config.get("delete_history", False):
        print("检测到 delete_history=True，正在清空数据库...")
        await clear_db()
        print("数据库已清空。")
    else:
        await init_db()
    
    # 启动异步备份任务
    backup_interval = config.get("backup_interval", 60) # 默认60分钟
    if backup_interval > 0:
        asyncio.create_task(backup_task(backup_interval))

async def backup_task(interval_minutes: int):
    """异步备份任务"""
    print(f"备份任务已启动，每 {interval_minutes} 分钟备份一次。")
    while True:
        try:
            # 等待指定的间隔时间
            await asyncio.sleep(interval_minutes * 60)
            print(f"[{datetime.now()}] 正在执行自动备份...")
            await backup_db()
            print(f"[{datetime.now()}] 自动备份完成。")
        except Exception as e:
            print(f"备份过程中出错: {e}")

# 聊天室连接管理 (保持内存中的连接，但数据持久化到数据库)
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, List[WebSocket]] = {}

    async def connect(self, room_id: str, websocket: WebSocket):
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = []
        self.active_connections[room_id].append(websocket)

    def disconnect(self, room_id: str, websocket: WebSocket):
        if room_id in self.active_connections:
            if websocket in self.active_connections[room_id]:
                self.active_connections[room_id].remove(websocket)

    async def broadcast(self, room_id: str, message: dict):
        if room_id in self.active_connections:
            for connection in self.active_connections[room_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

manager = ConnectionManager()

# 初始化生成器
try:
    generator = Generator()
except Exception as e:
    print(f"初始化 Generator 失败: {e}")
    generator = None

# 请求模型
class ChatRequest(BaseModel):
    mode: int = 0  # 0: 纯文本
    input_str: Optional[str] = None
    max_messages: int = 10
    current_user: Optional[str] = None # 用于生成针对当前用户的建议
    room_id: Optional[str] = None

class CreateRoomRequest(BaseModel):
    room_id: str
    name: str

class LeaveRoomRequest(BaseModel):
    room_id: str

class UpdateNicknameRequest(BaseModel):
    nickname: str
    room_id: str
    avatar_id: Optional[int] = None

@app.get("/api/user/info")
async def get_user_info(fastapi_request: Request, room_id: Optional[str] = None):
    client_ip = fastapi_request.client.host if fastapi_request.client else "127.0.0.1"
    async with AsyncSessionLocal() as session:
        nickname = client_ip
        avatar_path = DEFAULT_AVATAR
        if room_id:
            result = await session.execute(
                select(DBUserRoom)
                .options(joinedload(DBUserRoom.avatar))
                .where(DBUserRoom.user_ip == client_ip, DBUserRoom.room_id == room_id)
            )
            ur = result.scalar_one_or_none()
            if ur:
                if ur.nickname:
                    nickname = ur.nickname
                if ur.avatar:
                    avatar_path = ur.avatar.avatar_path
        
        return {"ip": client_ip, "nickname": nickname, "avatar_path": avatar_path}

@app.post("/api/user/nickname")
async def update_nickname(request: UpdateNicknameRequest, fastapi_request: Request):
    client_ip = fastapi_request.client.host if fastapi_request.client else "127.0.0.1"
    
    clean_nickname = sanitize_text(request.nickname)
    if not clean_nickname:
        clean_nickname = client_ip
        
    async with AsyncSessionLocal() as session:
        # 确保用户和房间关系存在
        result = await session.execute(
            select(DBUserRoom)
            .options(joinedload(DBUserRoom.avatar))
            .where(DBUserRoom.user_ip == client_ip, DBUserRoom.room_id == request.room_id)
        )
        ur = result.scalar_one_or_none()
        if not ur:
            # 如果不存在关系，先检查房间是否存在
            room_result = await session.execute(select(DBRoom).where(DBRoom.room_id == request.room_id))
            if not room_result.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Room not found")
            
            ur = DBUserRoom(user_ip=client_ip, room_id=request.room_id, nickname=clean_nickname, avatar_id=request.avatar_id)
            session.add(ur)
            # 提交后重新查询以加载头像关系，或者手动加载
            await session.commit()
            result = await session.execute(
                select(DBUserRoom)
                .options(joinedload(DBUserRoom.avatar))
                .where(DBUserRoom.user_ip == client_ip, DBUserRoom.room_id == request.room_id)
            )
            ur = result.scalar_one_or_none()
        else:
            ur.nickname = clean_nickname
            if request.avatar_id is not None:
                ur.avatar_id = request.avatar_id
            await session.commit()
            await session.refresh(ur, ["avatar"])
        
        avatar_path = ur.avatar.avatar_path if ur.avatar else DEFAULT_AVATAR

        return {"status": "success", "nickname": clean_nickname, "avatar_path": avatar_path}

@app.post("/api/rooms/create")
async def create_room(request: CreateRoomRequest):
    clean_room_id = sanitize_text(request.room_id)
    clean_name = sanitize_text(request.name)
    
    if not clean_room_id or not clean_name:
        raise HTTPException(status_code=400, detail="无效的群聊ID或名称")

    async with AsyncSessionLocal() as session:
        # 检查房间是否存在
        result = await session.execute(select(DBRoom).where(DBRoom.room_id == clean_room_id))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="ID已存在")
        
        # 创建新房间
        new_room = DBRoom(room_id=clean_room_id, name=clean_name)
        session.add(new_room)
        await session.commit()
        return {"status": "success"}

@app.get("/api/rooms/check/{room_id}")
async def check_room(room_id: str):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DBRoom).where(DBRoom.room_id == room_id))
        room = result.scalar_one_or_none()
        if not room:
            raise HTTPException(status_code=404, detail="ID不存在")
        return {"status": "success", "name": room.name}

@app.post("/api/rooms/leave")
async def leave_room(request: LeaveRoomRequest, fastapi_request: Request):
    client_ip = fastapi_request.client.host if fastapi_request.client else "127.0.0.1"
    
    async with AsyncSessionLocal() as session:
        # 1. 移除用户与房间的关系
        from sqlalchemy import delete
        await session.execute(
            delete(DBUserRoom).where(DBUserRoom.user_ip == client_ip, DBUserRoom.room_id == request.room_id)
        )
        
        # 2. 检查是否还有其他用户在该房间
        result = await session.execute(
            select(DBUserRoom).where(DBUserRoom.room_id == request.room_id).limit(1)
        )
        remaining_user = result.scalar_one_or_none()
        
        if not remaining_user:
            # 3. 如果没有其他用户，删除消息和房间
            await session.execute(
                delete(DBMessage).where(DBMessage.room_id == request.room_id)
            )
            await session.execute(
                delete(DBRoom).where(DBRoom.room_id == request.room_id)
            )
        
        await session.commit()
        return {"status": "success"}

@app.get("/api/config/share")
async def get_share_config():
    app_config = load_app_config()
    return {"share_text": app_config.get("share_text", "")}

UPLOAD_DIR = os.path.join(project_root, "resources/uploads/fileMsgs")
AVATAR_DIR = os.path.join(project_root, "resources/uploads/avatars")
DEFAULT_AVATAR = "/resources/uploads/avatars/default.ico"

@app.post("/api/upload/avatar")
async def upload_avatar(file: UploadFile = File(...)):
    # 确保目录存在
    os.makedirs(AVATAR_DIR, exist_ok=True)
    
    # 检查是否是图像
    try:
        content = await file.read()
        img = Image.open(io.BytesIO(content))
        img.verify() # 验证图像完整性
        
        # 重新打开以进行处理，因为 verify() 后不能再操作
        img = Image.open(io.BytesIO(content))
        
        # 缩放为正方形
        width, height = img.size
        size = min(width, height)
        left = (width - size) / 2
        top = (height - size) / 2
        right = (width + size) / 2
        bottom = (height + size) / 2
        img = img.crop((left, top, right, bottom))
        img = img.resize((200, 200), Image.Resampling.LANCZOS)
        
        # 转回字节流计算摘要
        out_buffer = io.BytesIO()
        # 统一保存为 PNG 或原格式？建议统一为 PNG 以保证兼容性，或者保留原格式。
        # 这里统一转为 PNG 比较安全。
        img.save(out_buffer, format="PNG")
        processed_content = out_buffer.getvalue()
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无效的图像文件: {e}")

    digest = hashlib.sha256(processed_content).hexdigest()
    
    async with AsyncSessionLocal() as session:
        # 检查摘要是否已存在
        result = await session.execute(select(DBAvatar).where(DBAvatar.digest == digest))
        db_avatar = result.scalar_one_or_none()
        
        if not db_avatar:
            # 保存新头像
            save_filename = f"{digest}.png"
            file_path = os.path.join(AVATAR_DIR, save_filename)
            
            with open(file_path, "wb") as f:
                f.write(processed_content)
            
            db_avatar = DBAvatar(digest=digest, avatar_path=f"/res/uploads/avatars/{save_filename}")
            session.add(db_avatar)
            await session.commit()
            await session.refresh(db_avatar)
        
        return {
            "status": "success",
            "avatar_id": db_avatar.id,
            "avatar_path": db_avatar.avatar_path
        }

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    # 确保目录存在
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # 清理文件名
    clean_filename = sanitize_text(file.filename)
    if not clean_filename:
        clean_filename = "unnamed_file"

    # 读取内容以计算摘要
    content = await file.read()
    digest = hashlib.sha256(content).hexdigest()
    
    async with AsyncSessionLocal() as session:
        # 检查摘要是否已存在
        result = await session.execute(select(DBFile).where(DBFile.digest == digest))
        db_file = result.scalar_one_or_none()
        
        if not db_file:
            # 如果不存在，保存文件
            file_ext = os.path.splitext(file.filename)[1]
            save_filename = f"{digest}{file_ext}"
            file_path = os.path.join(UPLOAD_DIR, save_filename)
            
            with open(file_path, "wb") as f:
                f.write(content)
            
            # 添加到数据库
            db_file = DBFile(digest=digest, file_path=file_path)
            session.add(db_file)
            await session.commit()
            await session.refresh(db_file)
        
        return {
            "status": "success",
            "file_id": db_file.id,
            "filename": clean_filename
        }

@app.get("/api/download/{message_id}")
async def download_file(message_id: int):
    async with AsyncSessionLocal() as session:
        # 获取消息及其关联文件
        result = await session.execute(
            select(DBMessage).where(DBMessage.id == message_id)
        )
        msg = result.scalar_one_or_none()
        
        if not msg or msg.message_type != "file" or not msg.file_id:
            raise HTTPException(status_code=404, detail="File not found")
        
        # 获取文件信息
        file_result = await session.execute(
            select(DBFile).where(DBFile.id == msg.file_id)
        )
        db_file = file_result.scalar_one_or_none()
        
        if not db_file or not os.path.exists(db_file.file_path):
            raise HTTPException(status_code=404, detail="File content missing")
        
        return FileResponse(
            path=db_file.file_path,
            filename=msg.text, # 使用消息中的文本作为下载文件名
            media_type="application/octet-stream"
        )

@app.post("/api/generate")
async def generate_options(request: ChatRequest, fastapi_request: Request):
    if generator is None:
        raise HTTPException(status_code=500, detail="Generator 未能正确初始化")
    
    # 使用客户端 IP 作为当前用户标识
    client_ip = fastapi_request.client.host if fastapi_request.client else "127.0.0.1"
    
    try:
        if request.mode == 0:
            # 如果没有提供 input_str，则使用聊天室当前记录
            input_text = request.input_str
            if not input_text and request.room_id:
                async with AsyncSessionLocal() as session:
                    # 从数据库获取最近10条消息
                    result = await session.execute(
                        select(DBMessage)
                        .where(DBMessage.room_id == request.room_id)
                        .order_by(DBMessage.id.desc())
                        .limit(10)
                    )
                    messages = result.scalars().all()
                    # 翻转回来以保持正序
                    messages = list(reversed(messages))
                    
                    # 获取昵称映射
                    all_user_ips = set(msg.user_ip for msg in messages)
                    nickname_map = {}
                    if all_user_ips:
                        ur_result = await session.execute(
                            select(DBUserRoom)
                            .where(DBUserRoom.room_id == request.room_id, DBUserRoom.user_ip.in_(all_user_ips))
                        )
                        for ur in ur_result.scalars().all():
                            if ur.nickname:
                                nickname_map[ur.user_ip] = ur.nickname
                    
                    lines = []
                    for msg in messages:
                        name = nickname_map.get(msg.user_ip, msg.user_ip)
                        lines.append(f"{name}: {msg.text}")
                    
                    input_text = "\n".join(lines)
            
            if not input_text:
                 return {
                    "status": "success",
                    "data": {"contents": [], "length": 0},
                    "timestamp": get_now_time()
                }

            # 获取当前用户的昵称作为 local_user
            local_user_display = client_ip
            async with AsyncSessionLocal() as session:
                if request.room_id:
                    ur_res = await session.execute(
                        select(DBUserRoom).where(DBUserRoom.user_ip == client_ip, DBUserRoom.room_id == request.room_id)
                    )
                    ur_obj = ur_res.scalar_one_or_none()
                    if ur_obj and ur_obj.nickname:
                        local_user_display = ur_obj.nickname

            result = await generator.astr_generate(input_text, local_user=local_user_display)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的模式: {request.mode}")
        
        return {
            "status": "success",
            "data": result.model_dump(),
            "timestamp": get_now_time(),
            "your_ip": client_ip
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/chat/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    client_ip = websocket.client.host if websocket.client else "127.0.0.1"
    
    async with AsyncSessionLocal() as session:
        # 检查房间是否存在
        result = await session.execute(select(DBRoom).where(DBRoom.room_id == room_id))
        room = result.scalar_one_or_none()
        if not room:
            await websocket.accept()
            await websocket.send_json({"type": "error", "message": "Room not found"})
            await websocket.close()
            return

        # 记录/更新用户
        user_result = await session.execute(select(DBUser).where(DBUser.ip_addr == client_ip))
        user = user_result.scalar_one_or_none()
        if not user:
            user = DBUser(ip_addr=client_ip)
            session.add(user)
        else:
            user.last_seen = datetime.now()
        
        # 记录用户与房间的关系
        ur_result = await session.execute(
            select(DBUserRoom).where(DBUserRoom.user_ip == client_ip, DBUserRoom.room_id == room_id)
        )
        if not ur_result.scalar_one_or_none():
            session.add(DBUserRoom(user_ip=client_ip, room_id=room_id))
        
        await session.commit()

        await manager.connect(room_id, websocket)
        
        # 告诉客户端它的 IP，方便前端判断“我”
        ur_info_result = await session.execute(
            select(DBUserRoom)
            .options(joinedload(DBUserRoom.avatar))
            .where(DBUserRoom.user_ip == client_ip, DBUserRoom.room_id == room_id)
        )
        current_ur = ur_info_result.scalar_one_or_none()
        current_nickname = current_ur.nickname if current_ur and current_ur.nickname else client_ip
        current_avatar_path = current_ur.avatar.avatar_path if current_ur and current_ur.avatar else DEFAULT_AVATAR
        
        await websocket.send_json({
            "type": "init", 
            "your_ip": client_ip, 
            "your_nickname": current_nickname,
            "your_avatar": current_avatar_path,
            "room_name": room.name
        })

        # 获取历史消息并发给客户端
        msg_result = await session.execute(
            select(DBMessage).where(DBMessage.room_id == room_id).order_by(DBMessage.id.asc())
        )
        history = msg_result.scalars().all()
        
        # 预先获取所有相关的昵称和头像
        all_user_ips = set(msg.user_ip for msg in history)
        nickname_map = {}
        avatar_map = {}
        if all_user_ips:
            ur_avatar_result = await session.execute(
                select(DBUserRoom)
                .options(joinedload(DBUserRoom.avatar))
                .where(DBUserRoom.room_id == room_id, DBUserRoom.user_ip.in_(all_user_ips))
            )
            for ur in ur_avatar_result.scalars().all():
                if ur.nickname:
                    nickname_map[ur.user_ip] = ur.nickname
                if ur.avatar:
                    avatar_map[ur.user_ip] = ur.avatar.avatar_path

        for msg in history:
            await websocket.send_json({
                "type": "message",
                "message_id": msg.id,
                "text": msg.text,
                "user": msg.user_ip,
                "nickname": nickname_map.get(msg.user_ip, msg.user_ip),
                "avatar": avatar_map.get(msg.user_ip, DEFAULT_AVATAR),
                "timestamp": msg.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "message_type": msg.message_type
            })
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            text_content = message_data.get("text", "")
            
            # 清理消息内容
            clean_text = sanitize_text(text_content)
            if not clean_text and text_content:
                clean_text = "[包含不安全内容]"
            
            # 准备要广播的消息和持久化
            async with AsyncSessionLocal() as session:
                # 获取发送者信息
                ur_res = await session.execute(
                    select(DBUserRoom)
                    .options(joinedload(DBUserRoom.avatar))
                    .where(DBUserRoom.user_ip == client_ip, DBUserRoom.room_id == room_id)
                )
                ur_obj = ur_res.scalar_one_or_none()
                nickname = ur_obj.nickname if ur_obj and ur_obj.nickname else client_ip
                avatar_path = ur_obj.avatar.avatar_path if ur_obj and ur_obj.avatar else DEFAULT_AVATAR

                message_type = message_data.get("message_type", "text")
                
                # 持久化消息到数据库
                new_msg = DBMessage(
                    room_id=room_id,
                    user_ip=client_ip,
                    text=clean_text,
                    message_type=message_type,
                    file_id=message_data.get("file_id")
                )
                session.add(new_msg)
                await session.commit()
                await session.refresh(new_msg)
                
                message_id = new_msg.id
                timestamp_str = new_msg.timestamp.strftime("%Y-%m-%d %H:%M:%S")

            broadcast_msg = {
                "type": "message",
                "message_id": message_id,
                "text": clean_text,
                "user": client_ip,
                "nickname": nickname,
                "avatar": avatar_path,
                "timestamp": timestamp_str,
                "message_type": message_type,
                "file_id": message_data.get("file_id")
            }
            
            # 广播消息
            await manager.broadcast(room_id, broadcast_msg)
    except WebSocketDisconnect:
        manager.disconnect(room_id, websocket)
    except Exception as e:
        print(f"WebSocket 错误: {e}")
        manager.disconnect(room_id, websocket)

# 挂载资源
os.makedirs(AVATAR_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
# 挂载前端和资源目录
app.mount("/frontend", StaticFiles(directory=os.path.join(project_root, "frontend")), name="frontend")
app.mount("/resources", StaticFiles(directory=os.path.join(project_root, "resources")), name="resources")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(os.path.join(project_root, "resources/favicon.ico"))

@app.get("/resources/delete_group.ico", include_in_schema=False)
async def delete_group_icon():
    return FileResponse(os.path.join(project_root, "resources/delete_group.ico"))

@app.get("/resources/share.ico", include_in_schema=False)
async def share_icon():
    return FileResponse(os.path.join(project_root, "resources/share.ico"))

@app.get("/resources/setting.ico", include_in_schema=False)
async def setting_icon():
    return FileResponse(os.path.join(project_root, "resources/setting.ico"))

@app.get("/resources/file.ico", include_in_schema=False)
async def file_icon():
    return FileResponse(os.path.join(project_root, "resources/file.ico"))

@app.get("/resources/download.ico", include_in_schema=False)
async def download_icon():
    return FileResponse(os.path.join(project_root, "resources/download.ico"))

@app.get("/")
async def get_index():
    index_path = os.path.join(project_root, "frontend/index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
