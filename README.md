# Steam 愿望单折扣监控器

基于 Cloudflare Workers (Python) 的 Steam 愿望单折扣监控工具，自动检测打折游戏并通过 Telegram 推送通知。

## 功能

- 🎮 每日自动检查 Steam 愿望单
- 💰 获取游戏实时价格和折扣信息
- 📱 通过 Telegram Bot 推送打折通知
- 🔄 KV 去重机制，避免重复推送

## 前置要求

在开始之前，请确保你拥有以下内容：

1. **Cloudflare 账号**
2. **STEAM API KEY**
3. **STEAM USER ID**
4. **TELEGRAM BOT TOKEN**
5. **TELEGRAM CHAT ID**

### 💡 快速获取指南

- **Cloudflare 账号**: [注册 Cloudflare](https://dash.cloudflare.com)
- **STEAM API KEY**: 登录 [Steam Community](https://steamcommunity.com/dev/apikey) 申请（域名可随意填写）。
- **STEAM USER ID**: 
    - 访问你的 Steam 个人主页 URL，末尾的数字即是。
    - 或者使用 [SteamID Finder](https://steamid.io/) 查询 `steamID64`。
- **TELEGRAM BOT TOKEN**: 
    - 私聊 [@BotFather](https://t.me/BotFather) 发送 `/newbot` 创建机器人。
    - 获取到的 HTTP API Token 即为 Token。
- **TELEGRAM CHAT ID**:
    - 给你的机器人发送随意一条消息。
    - 访问 `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
    - 在返回的 JSON 中查找 `result[0].message.chat.id`。

## 部署步骤

### 1. 初始化配置

```bash
cp wrangler.toml.example wrangler.toml
```

### 2. 安装 wrangler

```bash
npm install -g wrangler
# 或使用 npx 无需全局安装
```

### 3. 登录 Cloudflare

```bash
npx wrangler login
```

### 4. 创建 KV Namespace

```bash
npx wrangler kv:namespace create NOTIFIED_GAMES
```

记录返回的 `id`，更新到 `wrangler.toml` 中：

```toml
[[kv_namespaces]]
binding = "NOTIFIED_GAMES"
id = "你的实际ID"
```

### 5. 配置 Secrets

```bash
npx wrangler secret put STEAM_API_KEY
npx wrangler secret put STEAM_USER_ID
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put TELEGRAM_CHAT_ID
```

### 6. 部署

```bash
npx wrangler deploy
```

## 本地测试

### 1. 生成配置文件

```bash
# 复制配置文件
cp wrangler.toml.example wrangler.toml
# 注意：本地测试时，wrangler.toml 中的 kv_namespaces id 可以填写任意字符串，例如 "test_id"
```

### 2. 配置环境变量

创建 `.dev.vars` 文件（此文件不应提交到 git），写入你的 secrets：

```env
STEAM_API_KEY="你的SteamKey"
STEAM_USER_ID="你的SteamID"
TELEGRAM_BOT_TOKEN="你的BotToken"
TELEGRAM_CHAT_ID="你的ChatID"
```

### 3. 启动测试

```bash
# 启动开发服务器
npx wrangler dev

# 手动触发任务，方便调试
- GET /check       执行完整检查流程（发送通知）
curl "http://localhost:8787/check"

- GET /check?dry_run=true  执行检查但不发送通知
curl "http://localhost:8787/check?dry_run=true"

- GET /health      健康检查
curl "http://localhost:8787/health"
```

## 配置说明

| 环境变量 | 说明 |
|---------|------|
| `STEAM_API_KEY` | Steam Web API 密钥 |
| `STEAM_USER_ID` | 目标用户的 17 位 Steam ID |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | 接收通知的 Chat ID |
| `COUNTRY_CODE` | 价格区域 (默认 `CN`) |
| `MIN_DISCOUNT` | 最低折扣阈值 (默认 `0`) |


## 注意事项

- Steam 愿望单必须设置为**公开**
- Cron 触发器使用 UTC 时区
- Steam Store API 有速率限制，请勿频繁部署测试
