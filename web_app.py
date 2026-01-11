import os
import sys
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import json
from datetime import datetime

# 将当前目录添加到路径以便导入 galchat
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from galchat.agent import Generator
from galchat.utils import _get_now_time as get_now_time
from galchat.database import AsyncSessionLocal, DBRoom, DBMessage, DBUser, DBUserRoom, init_db
from sqlalchemy import select

# 加载 App 配置以支持分享功能
try:
    import tomllib
except ImportError:
    import tomli as tomllib

def load_app_config():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, "galchat", "config.toml")
    with open(config_path, "rb") as f:
        config = tomllib.load(f)
    return config.get("App", {})

app = FastAPI(title="GalChat Web API")

@app.on_event("startup")
async def startup_event():
    await init_db()

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

@app.post("/api/rooms/create")
async def create_room(request: CreateRoomRequest):
    async with AsyncSessionLocal() as session:
        # 检查房间是否存在
        result = await session.execute(select(DBRoom).where(DBRoom.room_id == request.room_id))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="ID已存在")
        
        # 创建新房间
        new_room = DBRoom(room_id=request.room_id, name=request.name)
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
                    
                    lines = []
                    for msg in messages:
                        lines.append(f"{msg.user_ip}: {msg.text}")
                    
                    input_text = "\n".join(lines)
            
            if not input_text:
                 return {
                    "status": "success",
                    "data": {"contents": [], "length": 0},
                    "timestamp": get_now_time()
                }

            result = await generator.astr_generate(input_text, local_user=client_ip)
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
        await websocket.send_json({"type": "init", "your_ip": client_ip, "room_name": room.name})

        # 获取历史消息并发给客户端
        msg_result = await session.execute(
            select(DBMessage).where(DBMessage.room_id == room_id).order_by(DBMessage.id.asc())
        )
        history = msg_result.scalars().all()
        for msg in history:
            await websocket.send_json({
                "type": "message",
                "text": msg.text,
                "user": msg.user_ip,
                "timestamp": msg.timestamp
            })
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            # 准备要广播的消息
            timestamp = get_now_time()
            broadcast_msg = {
                "type": "message",
                "text": message_data["text"],
                "user": client_ip,
                "timestamp": timestamp
            }
            
            # 持久化消息到数据库
            async with AsyncSessionLocal() as session:
                new_msg = DBMessage(
                    room_id=room_id,
                    user_ip=client_ip,
                    text=message_data["text"],
                    timestamp=timestamp
                )
                session.add(new_msg)
                await session.commit()
            
            # 广播消息
            await manager.broadcast(room_id, broadcast_msg)
    except WebSocketDisconnect:
        manager.disconnect(room_id, websocket)
    except Exception as e:
        print(f"WebSocket 错误: {e}")
        manager.disconnect(room_id, websocket)

# 挂载静态文件
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("res/favicon.ico")

@app.get("/res/delete_group.ico", include_in_schema=False)
async def delete_group_icon():
    return FileResponse("res/delete_group.ico")

@app.get("/res/share.ico", include_in_schema=False)
async def share_icon():
    return FileResponse("res/share.ico")

@app.get("/")
async def get_index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
