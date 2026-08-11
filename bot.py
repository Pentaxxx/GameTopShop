import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
    FSInputFile,
)

from config import (
    BOT_TOKEN,
    ADMIN_ID,
    ABOUT_TEXT,
    PRODUCTS,
    UPSELL_AFTER,
    UPSELL_TEXT,
    CONTACT_URL,
    CHANNEL_URL,
    BANNER_PATH,
    delivery_text,
)

logging.basicConfig(level=logging.INFO)
router = Router()

# ---------------------------------------------------------------------------
# Хранилище в памяти. Для демо этого достаточно — на реальном проекте
# для конкретного клиента это будет БД (SQLite/Postgres).
# ---------------------------------------------------------------------------
sales_log: list[dict] = []  # лог продаж — для /stats у админа


# ---------------------------------------------------------------------------
# Общий обработчик ошибок. Ловит некритичные сбои вроде "query is too old"
# (устаревшая кнопка, обычно из-за рассинхронизации времени на компьютере) —
# бот просто пропускает такое событие вместо падения с трейсбеком.
# ---------------------------------------------------------------------------
@router.errors()
async def handle_errors(event: ErrorEvent):
    if isinstance(event.exception, TelegramBadRequest):
        logging.warning(f"Некритичная ошибка Telegram API, пропускаем: {event.exception}")
        return True
    logging.exception("Необработанная ошибка", exc_info=event.exception)
    return True


# ---------------------------------------------------------------------------
# Клавиатуры
# ---------------------------------------------------------------------------
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛍 Каталог товаров", callback_data="catalog")],
            [InlineKeyboardButton(text="ℹ️ О нас", callback_data="about")],
            [InlineKeyboardButton(text="🆘 Поддержка", url=CONTACT_URL)],
            [InlineKeyboardButton(text="📢 Наш канал", url=CHANNEL_URL)],
        ]
    )


def catalog_kb() -> InlineKeyboardMarkup:
    rows = []
    for product_id, product in PRODUCTS.items():
        title = f"{product['name']} — {product['price_stars']} ⭐"
        rows.append([InlineKeyboardButton(text=title, callback_data=f"product:{product_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_kb(product_id: str) -> InlineKeyboardMarkup:
    product = PRODUCTS[product_id]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"Купить за {product['price_stars']} ⭐",
                callback_data=f"buy:{product_id}",
            )],
            [InlineKeyboardButton(text="⬅️ К каталогу", callback_data="catalog")],
        ]
    )


def upsell_kb(product_id: str) -> InlineKeyboardMarkup:
    product = PRODUCTS[product_id]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"Купить за {product['price_stars']} ⭐",
                callback_data=f"buy:{product_id}",
            )],
            [InlineKeyboardButton(text="Не сейчас", callback_data="menu")],
        ]
    )


# ---------------------------------------------------------------------------
# Старт и меню
# ---------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message):
    try:
        await message.answer_photo(FSInputFile(BANNER_PATH), reply_markup=main_menu_kb())
    except FileNotFoundError:
        # Файла баннера нет рядом с bot.py — не роняем бота, просто
        # показываем меню без картинки.
        await message.answer("Меню:", reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery):
    await callback.message.edit_caption(caption=None, reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "about")
async def cb_about(callback: CallbackQuery):
    await callback.message.edit_caption(caption=ABOUT_TEXT, reply_markup=main_menu_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# Каталог и карточка товара
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "catalog")
async def cb_catalog(callback: CallbackQuery):
    await callback.message.edit_caption(
        caption="Вот что есть сейчас 👇\nВыбери, чтобы посмотреть подробнее.",
        reply_markup=catalog_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("product:"))
async def cb_product(callback: CallbackQuery):
    product_id = callback.data.split(":", 1)[1]
    product = PRODUCTS.get(product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    await callback.message.edit_caption(caption=product["description"], reply_markup=product_kb(product_id))
    await callback.answer()


# ---------------------------------------------------------------------------
# Оплата через Telegram Stars
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(callback: CallbackQuery, bot: Bot):
    product_id = callback.data.split(":", 1)[1]
    product = PRODUCTS.get(product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=product["name"],
        description=product["short"],
        payload=f"product:{product_id}",
        provider_token="",  # для Stars всегда пустая строка
        currency="XTR",     # XTR = Telegram Stars
        prices=[LabeledPrice(label=product["name"], amount=product["price_stars"])],
    )
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    # Тут же можно проверить наличие товара на складе и т.п.
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, bot: Bot):
    payload = message.successful_payment.invoice_payload  # "product:vbucks_1000"
    product_id = payload.split(":", 1)[1]
    product = PRODUCTS.get(product_id)
    if not product:
        return

    # Зачисление ручное — просим написать игровой ник/ID менеджеру
    await message.answer(delivery_text(product["name"]))

    # Лог продажи + уведомление админу
    sales_log.append({
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "product": product["name"],
        "amount": message.successful_payment.total_amount,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    if ADMIN_ID:
        await bot.send_message(
            ADMIN_ID,
            f"💰 Новая продажа: {product['name']}\n"
            f"Покупатель: @{message.from_user.username or message.from_user.id}\n"
            f"Сумма: {message.successful_payment.total_amount} ⭐\n"
            f"Ждём от него игровой ник/ID в личке для зачисления.",
        )

    # Апсейл, если для этого товара он настроен
    upsell_id = UPSELL_AFTER.get(product_id)
    if upsell_id:
        await message.answer(UPSELL_TEXT, reply_markup=upsell_kb(upsell_id))


# ---------------------------------------------------------------------------
# Любой текст вне сценария — мягко вернуть в меню.
# Вопросы теперь идут не через бота, а напрямую в личку по кнопке "Написать нам".
# ---------------------------------------------------------------------------
@router.message(F.text & ~F.text.startswith("/"))
async def handle_free_text(message: Message):
    await message.answer("Не совсем понял 🙂 Вот меню:", reply_markup=main_menu_kb())


# ---------------------------------------------------------------------------
# Простая админ-статистика
# ---------------------------------------------------------------------------
@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    if not sales_log:
        await message.answer("Продаж пока нет.")
        return

    total = sum(s["amount"] for s in sales_log)
    lines = [f"Всего продаж: {len(sales_log)}, на сумму {total} ⭐\n"]
    for s in sales_log[-10:]:
        lines.append(f"• {s['time']} — {s['product']} — @{s['username'] or s['user_id']}")
    await message.answer("\n".join(lines))


# ---------------------------------------------------------------------------
async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
