-name: start-dev
description: 启动 Companion 开发环境 — Core 后端 (port 8000) + Web-Shell 前端 (port 8080)
---

# Start Dev Environment

启动 Companion 项目的完整开发环境，包括 FastAPI 核心后端和 Web-Shell 调试前端。

## 架构

```
Browser (web-shell/index.html)
   → web-shell/server.py (port 8080, 反向代理)
       → /core/*  →  FastAPI app (port 8000)
       → /*       →  DeepSeek API (api.deepseek.com)
```

## 执行步骤

### 1. 清理旧进程

先杀掉可能占用端口的旧进程：

```bash
kill $(lsof -ti :8000) 2>/dev/null; kill $(lsof -ti :8080) 2>/dev/null; echo "cleaned"
```

### 2. 检查环境

确认虚拟环境和 API Key：

```bash
cd /workspaces/Companion
source .venv/bin/activate
echo "DEEPSEEK_API_KEY: $([ -n \"$DEEPSEEK_API_KEY\" ] && echo '✓ set' || echo '✗ missing — 需要设置才能调用 LLM')"
```

### 3. 启动 Core 后端

在后台启动 FastAPI 开发服务器（端口 8000）：

```bash
source .venv/bin/activate && nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/core.log 2>&1 &
sleep 2
curl -s http://127.0.0.1:8000/health
```

预期输出：`{"status":"ok"}`

### 4. 启动 Web-Shell 前端

在后台启动反向代理服务器（端口 8080）：

```bash
source .venv/bin/activate && nohup python3 web-shell/server.py > /tmp/webshell.log 2>&1 &
sleep 1
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/
```

预期输出：`200`

### 5. 验证

两个服务都就绪后，打印访问地址：

```bash
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Core:      http://localhost:8000"
echo "  Web-Shell: http://localhost:8080"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
```

## 常用端口

| 服务 | 端口 | 说明 |
|------|------|------|
| Core (FastAPI) | 8000 | 主后端 API，聊天/记忆/决策 |
| Web-Shell | 8080 | 调试前端 + API 反向代理 |
| DeepSeek API | 443 | 上游 LLM（通过 web-shell 代理） |

## 日志文件

- Core 日志：`/tmp/core.log`
- Web-Shell 日志：`/tmp/webshell.log`

```bash
# 查看实时日志
tail -f /tmp/core.log
tail -f /tmp/webshell.log
```

## 停止服务

```bash
kill $(lsof -ti :8000) 2>/dev/null
kill $(lsof -ti :8080) 2>/dev/null
echo "Companion dev environment stopped."
```
