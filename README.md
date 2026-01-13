# GalChat ~ 对话辅助即时聊天

聊天不再是打字和语音，你可以像 GalGame 一样用选项快捷回复消息！支持多人多群聊实时互动。

## 项目简介

GalChat 是一个基于大语言模型的对话辅助系统。它能够实时分析聊天记录，并为用户生成数个可能的回复选项。用户只需点击选项即可快速回复，提升聊天效率，缓解社交压力。

## 核心功能

- **多群聊支持**：支持新建和加入多个群聊，各群聊消息独立。
- **智能回复建议**：基于 LLM 异步生成符合当前群聊语境的回复选项。
- **免登录体验**：通过 IP 地址自动识别身份，支持多人在线即时通讯。
- **持久化存储**：接入 MySQL 数据库，确保用户信息、聊天室及消息历史在服务重启后依然保留。
- **个性化体验**：针对对话中不同的参与者提供差异化的回复建议。
- **双端接入**：提供 Web 界面和 Socket 服务器。

## 项目结构

```
GalChat/
├── backend/            # 后端核心代码
│   ├── ai/            # 智能回复建议服务 (LLM 逻辑)
│   ├── chatroom/      # 聊天室服务 (Web & Socket)
│   ├── database/      # 数据库操纵服务
│   └── common/        # 通用工具类
├── frontend/           # 前端界面文件 (HTML/JS)
├── resources/          # 资源存储区 (图标、上传的文件、头像)
├── config.toml         # 核心配置文件
└── README.md
```

## 快速开始

本项目使用 `uv` 管理依赖，请确保已安装 [uv](https://github.com/astral-sh/uv)。

### 1. 安装依赖
```bash
uv sync
```

### 2. 配置环境
1. 在项目根目录创建 `.env` 文件，并配置你的 LLM 密钥（如 DeepSeek）：
```env
DEEPSEEK_API_KEY=your_api_key_here
```
2. 参考 `config.toml.template` ，在项目根目录下新建 `config.toml`。

## 配置文件 (config.toml) 说明

| 配置项 | 说明 |
| :--- | :--- |
| **[Generator]** | |
| `model_name` | 使用的大模型名称 (目前支持 deepseek-chat) |
| `system_prompt` | 定义 AI 助手的角色、任务及生成回复选项的逻辑 |
| **[MySQL]** | |
| `host`, `port` | 数据库连接地址与端口 |
| `user`, `password` | 数据库用户名与密码 |
| `database` | 数据库名称 |
| **[App]** | |
| `delete_history` | 是否在每次启动时清空数据库 (true/false) |
| `backup_interval` | 数据库备份间隔时间 (分钟) |
| `share_text` | 网页端分享功能显示的文案 |

---

## 使用方法

### 方案一：网页聊天室 (推荐)

网页版提供了最完整的交互体验，支持多人多房间实时聊天和可视化建议生成。

1. **启动 Web 服务器**：
   ```bash
   uv run python backend/chatroom/web_app.py
   ```
2. **访问界面**：
   - **本机访问**：[http://localhost:8000](http://localhost:8000)
   - **局域网访问**：`http://[你的服务器IP地址]:8000`
3. **功能说明**：
   - **群聊管理**：点击左侧“新建群聊”或“加入群聊”进行操作。群聊 ID 唯一。
   - **身份识别**：系统根据 IP 识别“我”和“他人”，本机消息显示在右侧。
   - **自定义昵称/头像**：点击顶部设置图标，可为当前群聊设定独立的昵称与头像。
   - **手动触发建议**：点击“生成建议”按钮获取选项。
   - **快捷填入**：点击生成的建议选项，内容会自动填入输入框。

### 方案二：Socket 服务器

如果你希望将 GalChat 接入到其他客户端（如 QQ/微信机器人），可以使用 Socket 服务器。

1. **启动服务器**：
   ```bash
   uv run python backend/chatroom/server.py --host 127.0.0.1 --port 8888
   ```
2. **请求格式**：发送 JSON 格式请求，例如：
   ```json
   {
     "mode": 0,
     "input_str": "最近在忙什么？",
     "local_user": "Alice"
   }
   ```

## 技术架构

- **后端**：FastAPI + WebSocket (实时通讯)
- **前端**：Tailwind CSS + 原生 JS
- **核心逻辑**：LangChain + Structured Output + Pillow (图像处理)
- **数据库**：MySQL (SQLAlchemy + aiomysql)
- **管理工具**：uv (依赖与环境管理)

## 许可说明
本项目仅供学习与交流使用。
