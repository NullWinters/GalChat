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
- **多端接入**：提供 Web 界面、Socket 服务器 and 命令行工具。

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
2. 在 `galchat/config.toml` 中配置你的 MySQL 数据库连接信息：
```toml
[MySQL]
host = "localhost"
port = 3306
user = "root"
password = "your_password"
database = "galchat_db"
```

---

## 使用方法

### 方案一：网页聊天室 (推荐)

网页版提供了最完整的交互体验，支持多人多房间实时聊天和可视化建议生成。

1. **启动 Web 服务器**：
   ```bash
   uv run python web_app.py
   ```
2. **访问界面**：
   - **本机访问**：[http://localhost:8000](http://localhost:8000)
   - **局域网访问**：`http://[你的服务器IP地址]:8000`
3. **功能说明**：
   - **群聊管理**：点击左侧“新建群聊”或“加入群聊”进行操作。群聊 ID 唯一。
   - **身份识别**：系统根据 IP 识别“我”和“他人”，本机消息显示在右侧。
   - **手动触发建议**：点击“生成建议”按钮获取选项。系统会自动提取当前群聊最近的 10 条消息作为上下文。
   - **快捷填入**：点击生成的建议选项，内容会自动填入输入框。

### 方案二：Socket 服务器

如果你希望将 GalChat 接入到其他客户端（如 QQ/微信机器人），可以使用 Socket 服务器。

1. **启动服务器**：
   ```bash
   uv run python server.py --host 127.0.0.1 --port 8888
   ```
2. **请求格式**：发送 JSON 格式请求，例如：
   ```json
   {
     "mode": 0,
     "input_str": "最近在忙什么？",
     "local_user": "Alice"
   }
   ```

### 方案三：命令行工具

适用于快速测试或脚本调用。

```bash
uv run python OptionsGenerator.py --input_str "你好，很高兴见到你"
```

## 技术架构

- **后端**：FastAPI + WebSocket (实时通讯)
- **前端**：Tailwind CSS + 原生 JS
- **核心逻辑**：LangChain + Structured Output (确保输出格式稳定)
- **管理工具**：uv (依赖与环境管理)

## 许可说明
本项目仅供学习与交流使用。
