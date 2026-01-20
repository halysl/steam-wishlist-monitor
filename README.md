# Steam 愿望单折扣监控器

基于 Cloudflare Workers (Python) 的 Steam 愿望单折扣监控工具，自动检测打折游戏并通过 Telegram 推送通知。

## 功能

- 🎮 每日自动检查 Steam 愿望单
- 💰 获取游戏实时价格和折扣信息
- 📱 通过 Telegram Bot 推送打折通知
- 🔄 KV 去重机制，避免重复推送

## 前置要求

1. [Cloudflare 账号](https://dash.cloudflare.com)
2. [Steam Web API Key](https://steamcommunity.com/dev/apikey)
3. [Telegram Bot Token](https://t.me/BotFather)
4. 安装 [wrangler CLI](https://developers.cloudflare.com/workers/wrangler/install-and-update/)

## 部署步骤

### 1. 安装 wrangler

```bash
npm install -g wrangler
# 或使用 npx 无需全局安装
```

### 2. 创建 KV Namespace

```bash
npx wrangler kv:namespace create NOTIFIED_GAMES
```

记录返回的 `id`，更新到 `wrangler.toml` 中：

```toml
[[kv_namespaces]]
binding = "NOTIFIED_GAMES"
id = "你的实际ID"
```

### 3. 配置 Secrets

```bash
npx wrangler secret put STEAM_API_KEY
npx wrangler secret put STEAM_USER_ID
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put TELEGRAM_CHAT_ID
```

### 4. 部署

```bash
npx wrangler deploy
```

## 本地测试

```bash
# 启动开发服务器
npx wrangler dev

# 手动触发任务，方便调试
```shell
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

## 获取 Steam User ID

1. 打开 Steam 个人资料页面
2. URL 中的数字即为 17 位 Steam ID
3. 或使用 [SteamID Finder](https://steamid.io/)

## 注意事项

- Steam 愿望单必须设置为**公开**
- Cron 触发器使用 UTC 时区
- Steam Store API 有速率限制，请勿频繁部署测试
