# Companion — Active AI Chat Framework (Prototype)

此仓库包含一个后端骨架，展示如何使用 Deepseek API 构建“主动发起对话”的触发引擎。

当前状态（2026-07）
- 聊天主链路已下沉到 Python：`/chat/history`、`/chat/reply`。
- 记忆功能已接入生产主链路：规则判定 + 边界二判（LLM）+ 冷却/去重 + SQLite 持久化。
- 主回复默认使用窗口化上下文，记忆更新默认后台异步执行。

主要组件
- `app/main.py`: FastAPI 应用入口，包含示例接口。
- `app/deepseek_client.py`: Deepseek API 客户端骨架。
- `app/trigger_engine.py`: 触发引擎骨架，负责依据条件评估并触发动作。
- `app/models.py`: Pydantic 请求/模型定义。

快速启动
1. 创建虚拟环境并安装依赖：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. 设置 Deepseek API Key（示例）：

```bash
export DEEPSEEK_API_KEY="your_api_key"
```

3. 运行开发服务器：

```bash
uvicorn app.main:app --reload --port 8000
```

4. 运行最小测试集：

```bash
pytest -q
```

下一步
- 确认要支持的触发条件类型（例如关键词、时间窗口、搜索匹配阈值等）。
- 我将根据你的优先级实现触发器评估、会话存储与通知机制。

原型说明
- 当前实现包含一个简单的 `SessionManager`（内存或可选 `SQLite` 后端）和 `TriggerEngine`。触发引擎可通过 WebSocket 向已连接的客户端发送实时消息：
	- WebSocket 路径：`/ws/{user_id}`。
	- 触发评估接口：`POST /triggers/evaluate`（接收触发条件与动作）。

测试说明（最小集）
- `tests/test_memory_rules.py`：覆盖记忆规则判定、重大事件识别、JSON 提取、语义记忆去重。
- `tests/test_sessions.py`：覆盖 SQLite 会话/消息上下文读写、记忆 upsert/get。
- 当前目标是保障“记忆链路不回退”的快速回归，不追求全量端到端覆盖。

测试系统优先级建议
1. P0（当前）: 保持最小回归集稳定运行（每次提交可执行）。
2. P1（近期）: 增加 `/chat/reply` 的契约测试（mock 上游 LLM）。
3. P2（中期）: 增加并发与性能场景（异步记忆更新、冷却/去重边界）。
4. P3（后续）: 建立完整测试系统（分层 CI、覆盖率门禁、夜间端到端）。

迁移提示
- `SessionManager` 使用 SQLite 仅做快速原型；生产建议迁移到 PostgreSQL，并通过 SQLAlchemy/Alma/db migration 管理模式变更。
# Companion
This repository aims at creating a proactive system for ai message
