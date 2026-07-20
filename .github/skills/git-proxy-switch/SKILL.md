---
name: git-proxy-switch
description: '切换 Git 代理模式（代理/直连）。在需要 push/pull/clone 遇到网络问题时使用，或在内外网环境间切换时使用。支持 Git 别名和 PowerShell 脚本两种方式。'
argument-hint: 'on 或 off'
user-invocable: true
---

# Git 代理模式切换

## 适用场景

- `git push` / `git pull` / `git clone` 因网络问题超时或失败时 → **开启代理**
- 在无需代理的网络环境（如公司内网、校园网直连）下 → **关闭代理**
- 在不同网络环境间切换工作时

## 代理配置

| 项目 | 值 |
|------|-----|
| 代理地址 | `http://127.0.0.1:7897` |
| 生效范围 | Git 全局配置 (`--global`) |
| 适用协议 | HTTP / HTTPS |

## 切换方式

### 方式一：Git 别名（推荐，最快速）

```bash
# 开启代理
git proxy-on

# 关闭代理
git proxy-off

# 查看当前状态
git proxy-status
```

### 方式二：PowerShell 脚本

```powershell
# 开启代理
.\scripts\proxy-on.ps1

# 关闭代理
.\scripts\proxy-off.ps1
```

### 方式三：手动命令

```bash
# 开启代理
git config --global http.proxy http://127.0.0.1:7897
git config --global https.proxy http://127.0.0.1:7897

# 关闭代理
git config --global --unset http.proxy
git config --global --unset https.proxy

# 查看当前代理状态
git config --global --get http.proxy
git config --global --get https.proxy
```

## 查看当前状态

```bash
# 查看所有 Git 全局代理配置
git config --global --get-regexp "proxy"

# 查看当前代理环境变量（如果有）
$env:HTTP_PROXY
$env:HTTPS_PROXY
```

## 初始设置（仅需一次）

首次使用时，运行以下命令设置 Git 别名（使用 `!` 前缀来执行 shell 命令）：

```bash
git config --global alias.proxy-on '!git config --global http.proxy http://127.0.0.1:7897 && git config --global https.proxy http://127.0.0.1:7897 && echo Git proxy is now ON'
git config --global alias.proxy-off '!git config --global --unset http.proxy && git config --global --unset https.proxy && echo Git proxy is now OFF'
git config --global alias.proxy-status '!git config --global --get-regexp proxy 2>/dev/null || echo Proxy is not set'
```

## 排错指南

| 问题 | 可能原因 | 解决方法 |
|------|---------|---------|
| 开启代理后仍无法连接 | 代理服务未启动 | 检查代理客户端（如 Clash/v2ray）是否运行 |
| 关闭代理后 git 报错 | `~/.gitconfig` 中仍有代理残留 | 手动运行 `git config --global --unset http.proxy` |
| 只想对特定仓库使用代理 | 全局代理影响所有仓库 | 改用 `--local` 在仓库目录下单独设置代理 |
