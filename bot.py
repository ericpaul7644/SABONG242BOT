"""Crypto Digest bot: /start -> welcome + instructions, tap 'Digest' -> top coins
being bought (gainers) and sold (losers). Telegram Bot API + CoinGecko public
endpoint (no API key). Long polling, no database."""
import html
import logging
import os
import time
from datetime import datetime, timezone

import requests

TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"
MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
CACHE_SECONDS = 90          # free CoinGecko endpoint is rate limited
DIGEST_BTN = "📊 Digest"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("digest-bot")

_cache = {"ts": 0.0, "coins": None}

WELCOME = (
    "👋 <b>Welcome to Crypto Digest!</b>\n\n"
    "Get a quick snapshot of what the crypto market is doing right now.\n\n"
    "<b>How to use it</b>\n"
    "1️⃣ Tap the <b>📊 Digest</b> button below (or send /digest)\n"
    "2️⃣ See the top coins being <b>bought 🟢</b> and <b>sold 🔴</b> in the last 24h\n"
    "3️⃣ Tap <b>🔄 Refresh</b> under a digest for the latest numbers\n\n"
    "<i>Educational only, not financial advice.</i>"
)


def api(method, **params):
    try:
        data = requests.post(f"{API}/{method}", json=params, timeout=65).json()
    except Exception as e:
        log.warning("API %s failed: %s", method, e)
        return {"ok": False}
    if not data.get("ok"):
        log.warning("API %s error: %s", method, data)
    return data


# ---------- market data ----------
def get_coins():
    """Top 100 coins by market cap. Cached; falls back to stale data on errors."""
    now = time.time()
    if _cache["coins"] and now - _cache["ts"] < CACHE_SECONDS:
        return _cache["coins"], _cache["ts"], False
    try:
        r = requests.get(MARKETS_URL, params={
            "vs_currency": "usd", "order": "market_cap_desc",
            "per_page": 100, "page": 1, "price_change_percentage": "24h"},
            headers={"User-Agent": "crypto-digest-bot"}, timeout=15)
        r.raise_for_status()
        coins = [c for c in r.json() if c.get("current_price") is not None
                 and c.get("price_change_percentage_24h") is not None]
        _cache.update(ts=now, coins=coins)
        return coins, now, False
    except Exception as e:
        log.warning("CoinGecko fetch failed: %s", e)
        if _cache["coins"]:
            return _cache["coins"], _cache["ts"], True   # stale
        return None, 0, True


def price(p):
    if p >= 1:
        return f"${p:,.2f}"
    return f"${p:.4f}" if p >= 0.01 else f"${p:.6f}"


def line(i, c):
    ch = c["price_change_percentage_24h"]
    return (f"{i}. <b>{html.escape(c['symbol'].upper())}</b>  "
            f"{price(c['current_price'])}  ({ch:+.2f}%)")


def build_digest():
    coins, ts, stale = get_coins()
    if not coins:
        return "⚠️ Couldn't load market data right now. Please try again in a minute."
    by_change = sorted(coins, key=lambda c: c["price_change_percentage_24h"])
    gainers = by_change[::-1][:5]
    losers = by_change[:5]
    top = coins[:5]
    when = datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M UTC")
    out = [f"📊 <b>Crypto Digest</b>",
           f"<i>Top 100 coins by market cap · last 24h · updated {when}</i>"
           + (" <i>(delayed)</i>" if stale else ""),
           "", "🟢 <b>Most bought (top gainers)</b>"]
    out += [line(i, c) for i, c in enumerate(gainers, 1)]
    out += ["", "🔴 <b>Most sold (top losers)</b>"]
    out += [line(i, c) for i, c in enumerate(losers, 1)]
    out += ["", "💰 <b>Biggest coins</b>"]
    out += [line(i, c) for i, c in enumerate(top, 1)]
    out += ["", "<i>Buying/selling is estimated from 24h price change, not actual order flow. "
                "Not financial advice.</i>"]
    return "\n".join(out)


REFRESH_KB = {"inline_keyboard": [[{"text": "🔄 Refresh", "callback_data": "refresh"}]]}
MAIN_KB = {"keyboard": [[{"text": DIGEST_BTN}]], "resize_keyboard": True}


def send_digest(chat_id):
    api("sendMessage", chat_id=chat_id, text=build_digest(), parse_mode="HTML",
        reply_markup=REFRESH_KB, disable_web_page_preview=True)


# ---------- handlers ----------
def handle_message(msg):
    if msg["chat"]["type"] != "private":
        return
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    cmd = text.split()[0].split("@")[0].lstrip("/").lower() if text.startswith("/") else ""
    if cmd in ("start", "help"):
        api("sendMessage", chat_id=chat_id, text=WELCOME, parse_mode="HTML", reply_markup=MAIN_KB)
    elif cmd == "digest" or text == DIGEST_BTN:
        send_digest(chat_id)
    elif text:
        api("sendMessage", chat_id=chat_id, text="Tap 📊 Digest to see the market, or send /help.",
            reply_markup=MAIN_KB)


def handle_callback(cb):
    msg = cb.get("message")
    if cb.get("data") != "refresh" or not msg:
        return api("answerCallbackQuery", callback_query_id=cb["id"])
    res = api("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
              text=build_digest(), parse_mode="HTML", reply_markup=REFRESH_KB,
              disable_web_page_preview=True)
    api("answerCallbackQuery", callback_query_id=cb["id"],
        text="Updated ✅" if res.get("ok") else "Already up to date")


def main():
    api("deleteWebhook")
    api("setMyCommands", commands=[
        {"command": "digest", "description": "Top coins bought and sold"},
        {"command": "help", "description": "How to use the bot"},
        {"command": "start", "description": "Welcome message"}])
    api("setMyShortDescription", short_description="Tap Digest to see which top coins are being bought and sold. 📊")
    api("setMyDescription", description=(
        "Your quick crypto market snapshot 📊\n\n"
        "Tap START, then press the Digest button to see:\n"
        "🟢 Top coins being bought\n🔴 Top coins being sold\n💰 The biggest coins by market cap\n\n"
        "Educational only, not financial advice."))
    log.info("Digest bot running")
    offset = None
    while True:
        params = {"timeout": 50, "allowed_updates": ["message", "callback_query"]}
        if offset:
            params["offset"] = offset
        res = api("getUpdates", **params)
        if not res.get("ok"):
            time.sleep(5)
            continue
        for upd in res["result"]:
            offset = upd["update_id"] + 1
            try:
                if "message" in upd:
                    handle_message(upd["message"])
                elif "callback_query" in upd:
                    handle_callback(upd["callback_query"])
            except Exception:
                log.exception("update failed: %s", upd)


if __name__ == "__main__":
    main()
