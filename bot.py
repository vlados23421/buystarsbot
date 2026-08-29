import os
import json
import hmac
import hashlib
import time
import logging
from fastapi import FastAPI, Request, Response, Header
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from mystars_faas import AsyncMyStarsClient
import uvicorn
import httpx

# === ЛОГИРОВАНИЕ ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
MYSTARS_API_KEY = os.getenv("MYSTARS_API_KEY")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://telegram-stars-bot-rc3.onrender.com")

# === ПРОВЕРКА ПЕРЕМЕННЫХ ===
if not all([BOT_TOKEN, MYSTARS_API_KEY, WEBHOOK_SECRET]):
    logger.error("❌ Ошибка: Не все переменные окружения заданы!")
    logger.error(f"BOT_TOKEN: {'✅' if BOT_TOKEN else '❌'}")
    logger.error(f"MYSTARS_API_KEY: {'✅' if MYSTARS_API_KEY else '❌'}")
    logger.error(f"WEBHOOK_SECRET: {'✅' if WEBHOOK_SECRET else '❌'}")
    exit(1)

logger.info(f"✅ Переменные окружения загружены")
logger.info(f"🌐 RENDER_URL: {RENDER_URL}")

# === ИНИЦИАЛИЗАЦИЯ ===
app = FastAPI()
telegram_app = Application.builder().token(BOT_TOKEN).build()

# === КОМАНДЫ БОТА ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("⭐ Купить Звёзды", callback_data="buy_stars")],
        [InlineKeyboardButton("👑 Купить Premium", callback_data="buy_premium")],
        [InlineKeyboardButton("📊 Мой баланс", callback_data="balance")],
    ]
    await update.message.reply_text(
        "👋 Добро пожаловать в магазин!\n"
        "Выберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def buy_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("100 ⭐ — 1.5 TON", callback_data="stars_100")],
        [InlineKeyboardButton("500 ⭐ — 7 TON", callback_data="stars_500")],
        [InlineKeyboardButton("1000 ⭐ — 13 TON", callback_data="stars_1000")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back")],
    ]
    await query.edit_message_text(
        "Выберите пакет Звёзд:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def buy_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("1 месяц — 3 TON", callback_data="premium_1")],
        [InlineKeyboardButton("3 месяца — 8 TON", callback_data="premium_3")],
        [InlineKeyboardButton("6 месяцев — 15 TON", callback_data="premium_6")],
        [InlineKeyboardButton("12 месяцев — 28 TON", callback_data="premium_12")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back")],
    ]
    await query.edit_message_text(
        "Выберите срок Premium:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def process_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    username = query.from_user.username or str(user_id)
    
    parts = data.split("_")
    product_type = parts[0]
    amount = int(parts[1])
    
    try:
        async with AsyncMyStarsClient.production(MYSTARS_API_KEY) as client:
            if product_type == "stars":
                quote = await client.get_pricing(
                    type="stars",
                    stars=amount,
                    payment_currency="ton"
                )
                
                recipient = await client.check_recipient(username, type="stars")
                if not recipient.eligible:
                    await query.edit_message_text(
                        f"❌ {recipient.telegram_message}\n\n"
                        "Убедись, что у тебя открыт профиль в Telegram."
                    )
                    return
                
                order = await client.create_order(
                    type="stars",
                    recipient=username,
                    stars=amount,
                    payment_currency="ton",
                    callback_url=f"{RENDER_URL}/webhooks/mystars",
                    idempotency_key=f"order_{user_id}_{amount}_{int(time.time())}"
                )
                
            else:
                quote = await client.get_pricing(
                    type="premium",
                    months=amount,
                    payment_currency="ton"
                )
                
                recipient = await client.check_recipient(username, type="premium")
                if not recipient.eligible:
                    await query.edit_message_text(
                        f"❌ {recipient.telegram_message}\n\n"
                        "Убедись, что у тебя открыт профиль в Telegram."
                    )
                    return
                
                order = await client.create_order(
                    type="premium",
                    recipient=username,
                    months=amount,
                    payment_currency="ton",
                    callback_url=f"{RENDER_URL}/webhooks/mystars",
                    idempotency_key=f"order_{user_id}_{amount}_{int(time.time())}"
                )
            
            payment = order.payment
            payment_info = (
                f"💳 **Оплата в TON**\n\n"
                f"💰 Сумма: **{payment.amount} TON**\n"
                f"📱 Кошелёк: `{payment.address}`\n"
                f"📝 Комментарий: `{payment.memo}`\n\n"
                f"⏳ Ожидаем подтверждения...\n"
                f"🆔 Заказ: `{order.id}`"
            )
            
            await query.edit_message_text(
                payment_info,
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при создании заказа:\n`{str(e)}`",
            parse_mode="Markdown"
        )

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await start(update, context)

# === РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ ===
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CallbackQueryHandler(buy_stars, pattern="^buy_stars$"))
telegram_app.add_handler(CallbackQueryHandler(buy_premium, pattern="^buy_premium$"))
telegram_app.add_handler(CallbackQueryHandler(process_purchase, pattern="^(stars|premium)_"))
telegram_app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back$"))

# === WEBHOOK ДЛЯ TELEGRAM ===
@app.post(f"/webhook/{WEBHOOK_SECRET}")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.process_update(update)
        logger.info(f"✅ Webhook обработан: {update.update_id}")
        return {"ok": True}
    except Exception as e:
        logger.error(f"❌ Ошибка webhook: {e}")
        return {"ok": False}

# === WEBHOOK ДЛЯ MYSTARS ===
@app.post("/webhooks/mystars")
async def mystars_webhook(request: Request, x_signature: str = Header(None)):
    try:
        body = await request.body()
        
        secret = WEBHOOK_SECRET.encode()
        signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
        
        if signature != x_signature:
            logger.warning("⚠️ Неверная подпись webhook")
            return Response(status_code=403, content="Invalid signature")
        
        data = json.loads(body)
        order_id = data.get("order_id")
        status = data.get("status")
        
        logger.info(f"📦 Заказ {order_id} → статус: {status}")
        
        return {"ok": True}
    except Exception as e:
        logger.error(f"❌ Ошибка в webhook MyStars: {e}")
        return {"ok": False}

# === HEALTH CHECK ===
@app.get("/health")
async def health():
    return {"status": "ok", "service": "telegram-stars-bot", "webhook_secret": WEBHOOK_SECRET[:8] + "..."}

# === ROOT ===
@app.get("/")
async def root():
    return {"message": "Telegram Stars Bot is running!"}

# === ЗАПУСК ===
if __name__ == "__main__":
    logger.info("🚀 Запуск бота...")
    
    # Устанавливаем вебхук
    webhook_url = f"{RENDER_URL}/webhook/{WEBHOOK_SECRET}"
    logger.info(f"🔗 Регистрируем вебхук: {webhook_url}")
    
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={
                "url": webhook_url,
                "drop_pending_updates": True,
                "allowed_updates": ["message", "callback_query"]
            }
        )
        result = resp.json()
        logger.info(f"✅ Webhook установлен: {result}")
    except Exception as e:
        logger.error(f"❌ Ошибка установки webhook: {e}")
    
    # Запускаем сервер
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🌐 Запуск сервера на порту {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
