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


async def http_post(url: str, data: dict) -> tuple[dict | None, str | None]:
    """
    发起 POST 请求并返回 JSON
    返回: (response_data, error_message)
    """
    try:
        options = Object.fromEntries(to_js([
            ["method", "POST"],
            ["headers", Object.fromEntries(to_js([
                ["Content-Type", "application/json"]
            ]))],
            ["body", json.dumps(data)]
        ]))
        response = await fetch(url, options)
        text = await response.text()
        
        if not response.ok:
            error_msg = f"HTTP {response.status}: {text}"
            console.error(f"HTTP POST failed: {url} -> {error_msg}")
            return None, error_msg
        
        return json.loads(text), None
    except Exception as e:
        error_msg = str(e)
        console.error(f"HTTP POST error: {url} -> {error_msg}")
        return None, error_msg


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
        await asyncio.sleep(1)
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


async def send_telegram_notification(bot_token: str, chat_id: str, message: str) -> tuple[bool, str | None]:
    """
    发送 Telegram 消息
    返回: (success, error_message)
    """
    url = TELEGRAM_API.format(token=bot_token)
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    result, error = await http_post(url, payload)
    if error:
        console.error(f"Failed to send Telegram notification: {error}")
        return False, error
    
    if result and result.get("ok"):
        console.log(f"Telegram notification sent successfully")
        return True, None
    else:
        error_msg = f"Telegram API returned: {result}"
        console.error(error_msg)
        return False, error_msg


# ============================================================
# Worker 入口
# ============================================================

async def check_wishlist_discounts(env, dry_run: bool = False) -> dict:
    """
    检查愿望单折扣的核心逻辑
    
    Args:
        env: Cloudflare Workers 环境对象
        dry_run: 如果为 True，则只检查不发送通知，用于调试
    
    Returns:
        包含执行结果的字典
    """
    result = {
        "success": True,
        "wishlist_count": 0,
        "games_with_price": 0,
        "discounted_count": 0,
        "new_discounts_count": 0,
        "notification_sent": False,
        "discounted_games": [],
        "errors": []
    }
    
    try:
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
        result["wishlist_count"] = len(app_ids)
        console.log(f"Found {len(app_ids)} games in wishlist")
        
        if not app_ids:
            console.log("Wishlist is empty, exiting")
            return result
        
        # 2. 获取价格信息
        console.log("Fetching price information...")
        games = await get_game_prices(app_ids, country_code)
        result["games_with_price"] = len(games)
        console.log(f"Got price info for {len(games)} games")
        
        # 3. 筛选有折扣的游戏
        discounted = filter_discounted_games(games, min_discount)
        result["discounted_count"] = len(discounted)
        result["discounted_games"] = discounted
        console.log(f"Found {len(discounted)} discounted games")
        
        if not discounted:
            console.log("No discounted games found, exiting")
            return result
        
        # 4. 过滤已通知过的游戏
        new_discounts = await filter_new_discounts(kv, discounted)
        result["new_discounts_count"] = len(new_discounts)
        console.log(f"Found {len(new_discounts)} new discounts to notify")
        
        if not new_discounts:
            console.log("All discounts already notified, exiting")
            return result
        
        # 5. 发送 Telegram 通知 (dry_run 模式下跳过)
        if dry_run:
            console.log("Dry run mode, skipping notification")
            result["notification_sent"] = False
        else:
            message = format_discount_message(new_discounts)
            success, telegram_error = await send_telegram_notification(telegram_bot_token, telegram_chat_id, message)
            result["notification_sent"] = success
            if telegram_error:
                result["errors"].append(f"Telegram: {telegram_error}")
            
            # 6. 标记已通知
            if success:
                for game in new_discounts:
                    await mark_as_notified(kv, game["app_id"])
                    console.log(f"Marked as notified: {game['name']}")
        
        console.log("Steam wishlist monitor completed")
        
    except Exception as e:
        result["success"] = False
        result["errors"].append(str(e))
        console.error(f"Error in check_wishlist_discounts: {e}")
    
    return result


async def on_scheduled(controller, env, ctx):
    """
    Cron Trigger 入口函数
    """
    console.log("Steam wishlist monitor started (scheduled)")
    await check_wishlist_discounts(env, dry_run=False)


async def on_fetch(request, env, ctx):
    """
    HTTP 请求入口函数 - 用于手动触发和调试
    
    支持的路径:
    - GET /check       执行完整检查流程（发送通知）
    - GET /check?dry_run=true  执行检查但不发送通知
    - GET /health      健康检查
    """
    from js import Response, Headers
    
    url_str = request.url
    # 解析 URL 路径
    path = "/" + url_str.split("//", 1)[1].split("/", 1)[-1].split("?")[0]
    
    # 解析查询参数
    query_string = url_str.split("?", 1)[-1] if "?" in url_str else ""
    dry_run = "dry_run=true" in query_string.lower()
    
    headers = Headers.new(to_js([
        ["Content-Type", "application/json"]
    ]))
    
    if path == "/health":
        return Response.new(
            json.dumps({"status": "ok"}),
            to_js({"status": 200, "headers": headers})
        )
    
    if path == "/check":
        console.log(f"Steam wishlist monitor started (manual trigger, dry_run={dry_run})")
        result = await check_wishlist_discounts(env, dry_run=dry_run)
        return Response.new(
            json.dumps(result, ensure_ascii=False, indent=2),
            to_js({"status": 200 if result["success"] else 500, "headers": headers})
        )
    
    # 默认返回 404
    return Response.new(
        json.dumps({"error": "Not found", "available_paths": ["/health", "/check", "/check?dry_run=true"]}),
        to_js({"status": 404, "headers": headers})
    )
