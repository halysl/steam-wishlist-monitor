"""
Steam 愿望单折扣监控器
Cloudflare Workers Python 入口
"""

from js import fetch, Object, console
from pyodide.ffi import to_js
import json
import asyncio


# ============================================================
# 配置常量
# ============================================================

STEAM_WISHLIST_API = "https://api.steampowered.com/IWishlistService/GetWishlist/v1"
STEAM_STORE_API = "https://store.steampowered.com/api/appdetails"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# 去重 KV 过期时间 (秒): 7 天
NOTIFICATION_TTL = 7 * 24 * 60 * 60


# ============================================================
# HTTP 工具函数
# ============================================================

async def http_get(url: str) -> dict | None:
    """发起 GET 请求并返回 JSON"""
    try:
        response = await fetch(url)
        if not response.ok:
            console.error(f"HTTP GET failed: {url} -> {response.status}")
            return None
        text = await response.text()
        return json.loads(text)
    except Exception as e:
        console.error(f"HTTP GET error: {url} -> {e}")
        return None


async def http_post(url: str, data: dict) -> dict | None:
    """发起 POST 请求并返回 JSON"""
    try:
        options = Object.fromEntries(to_js([
            ["method", "POST"],
            ["headers", Object.fromEntries(to_js([
                ["Content-Type", "application/json"]
            ]))],
            ["body", json.dumps(data)]
        ]))
        response = await fetch(url, options)
        if not response.ok:
            console.error(f"HTTP POST failed: {url} -> {response.status}")
            return None
        text = await response.text()
        return json.loads(text)
    except Exception as e:
        console.error(f"HTTP POST error: {url} -> {e}")
        return None


# ============================================================
# Steam API 函数
# ============================================================

async def get_wishlist(steam_id: str, api_key: str) -> list[int]:
    """
    获取用户愿望单中的游戏 AppID 列表
    返回: [appid1, appid2, ...]
    """
    url = f"{STEAM_WISHLIST_API}?steamid={steam_id}&key={api_key}"
    data = await http_get(url)
    
    if not data or "response" not in data:
        console.error("Failed to fetch wishlist")
        return []
    
    items = data["response"].get("items", [])
    return [item["appid"] for item in items]


async def get_game_price(app_id: int, country_code: str) -> dict | None:
    """
    获取单个游戏的价格信息
    返回: {
        "app_id": 12345,
        "name": "Game Name",
        "discount_percent": 50,
        "original_price": "¥298.00",
        "final_price": "¥149.00",
        "url": "https://store.steampowered.com/app/12345"
    }
    """
    url = f"{STEAM_STORE_API}?appids={app_id}&cc={country_code}&filters=price_overview,basic"
    data = await http_get(url)
    
    if not data:
        return None
    
    app_data = data.get(str(app_id), {})
    if not app_data.get("success"):
        return None
    
    game_data = app_data.get("data", {})
    price_overview = game_data.get("price_overview")
    
    # 免费游戏或无价格信息
    if not price_overview:
        return None
    
    return {
        "app_id": app_id,
        "name": game_data.get("name", f"AppID: {app_id}"),
        "discount_percent": price_overview.get("discount_percent", 0),
        "original_price": price_overview.get("initial_formatted", ""),
        "final_price": price_overview.get("final_formatted", ""),
        "url": f"https://store.steampowered.com/app/{app_id}"
    }


async def get_game_prices(app_ids: list[int], country_code: str) -> list[dict]:
    """
    批量获取游戏价格 (带 1 秒间隔避免速率限制)
    """
    results = []
    for app_id in app_ids:
        price_info = await get_game_price(app_id, country_code)
        if price_info:
            results.append(price_info)
        # 避免触发 Steam API 速率限制
        await asyncio.sleep(3)
    return results


# ============================================================
# 折扣筛选
# ============================================================

def filter_discounted_games(games: list[dict], min_discount: int = 0) -> list[dict]:
    """
    筛选有折扣的游戏
    min_discount: 最低折扣百分比阈值 (预留参数，当前默认 0)
    """
    return [
        game for game in games
        if game["discount_percent"] > min_discount
    ]


# ============================================================
# KV 去重机制
# ============================================================

async def is_already_notified(kv, app_id: int) -> bool:
    """检查是否已通知过该游戏"""
    key = f"notified:{app_id}"
    value = await kv.get(key)
    return value is not None


async def mark_as_notified(kv, app_id: int):
    """标记游戏已通知 (TTL 7 天后自动过期)"""
    key = f"notified:{app_id}"
    options = Object.fromEntries(to_js([
        ["expirationTtl", NOTIFICATION_TTL]
    ]))
    await kv.put(key, "1", options)


async def filter_new_discounts(kv, games: list[dict]) -> list[dict]:
    """过滤掉已通知过的游戏"""
    new_games = []
    for game in games:
        if not await is_already_notified(kv, game["app_id"]):
            new_games.append(game)
    return new_games


# ============================================================
# Telegram 通知
# ============================================================

def format_discount_message(games: list[dict]) -> str:
    """格式化折扣消息 (Markdown 格式)"""
    if not games:
        return ""
    
    lines = ["🎮 *Steam 愿望单折扣提醒*\n"]
    
    for game in games:
        lines.append(
            f"• [{game['name']}]({game['url']})\n"
            f"  ~~{game['original_price']}~~ → *{game['final_price']}* (-{game['discount_percent']}%)\n"
        )
    
    lines.append(f"\n_共 {len(games)} 款游戏正在打折_")
    return "\n".join(lines)


async def send_telegram_notification(bot_token: str, chat_id: str, message: str) -> bool:
    """发送 Telegram 消息"""
    url = TELEGRAM_API.format(token=bot_token)
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    result = await http_post(url, payload)
    if result and result.get("ok"):
        console.log(f"Telegram notification sent successfully")
        return True
    else:
        console.error(f"Failed to send Telegram notification: {result}")
        return False


# ============================================================
# Worker 入口
# ============================================================

async def on_scheduled(controller, env, ctx):
    """
    Cron Trigger 入口函数
    """
    console.log("Steam wishlist monitor started")
    
    # 读取环境变量
    steam_api_key = env.STEAM_API_KEY
    steam_user_id = env.STEAM_USER_ID
    telegram_bot_token = env.TELEGRAM_BOT_TOKEN
    telegram_chat_id = env.TELEGRAM_CHAT_ID
    country_code = getattr(env, "COUNTRY_CODE", "CN")
    min_discount = int(getattr(env, "MIN_DISCOUNT", "0"))
    
    # 获取 KV 绑定
    kv = env.NOTIFIED_GAMES
    
    # 1. 获取愿望单
    console.log("Fetching wishlist...")
    app_ids = await get_wishlist(steam_user_id, steam_api_key)
    console.log(f"Found {len(app_ids)} games in wishlist")
    
    if not app_ids:
        console.log("Wishlist is empty, exiting")
        return
    
    # 2. 获取价格信息
    console.log("Fetching price information...")
    games = await get_game_prices(app_ids, country_code)
    console.log(f"Got price info for {len(games)} games")
    
    # 3. 筛选有折扣的游戏
    discounted = filter_discounted_games(games, min_discount)
    console.log(f"Found {len(discounted)} discounted games")
    
    if not discounted:
        console.log("No discounted games found, exiting")
        return
    
    # 4. 过滤已通知过的游戏
    new_discounts = await filter_new_discounts(kv, discounted)
    console.log(f"Found {len(new_discounts)} new discounts to notify")
    
    if not new_discounts:
        console.log("All discounts already notified, exiting")
        return
    
    # 5. 发送 Telegram 通知
    message = format_discount_message(new_discounts)
    success = await send_telegram_notification(telegram_bot_token, telegram_chat_id, message)
    
    # 6. 标记已通知
    if success:
        for game in new_discounts:
            await mark_as_notified(kv, game["app_id"])
            console.log(f"Marked as notified: {game['name']}")
    
    console.log("Steam wishlist monitor completed")
