"""
Telegram admin-бот - панель управления.

Возможности:
  - Главное меню
  - "Тексты для заказов Roblox" - список текстов с кнопками вкл/выкл и
    редактированием (как на скрине: "Не указали логин и пароль",
    "Ответ после данных", "Данные неверные", "Данные верные",
    "После выполнения", "После подтверждения" и др.)
  - "Логи" - последние записи + live-стрим новых логов
  - "Товары" - просмотр/добавление сопоставлений товар Playerok -> Robux SKU

Запуск:
    python tg_admin_bot.py

Бот можно запускать одновременно с playerok_bot.py (используют общую БД).
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

import config
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("tg_admin_bot")

bot = Bot(token=config.TG_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


def is_admin(user_id: int) -> bool:
    return user_id in config.TG_ADMIN_IDS


# ===================== FSM =====================

class EditText(StatesGroup):
    waiting_text = State()


class AddProduct(StatesGroup):
    waiting_item_name = State()
    waiting_product_id = State()
    waiting_sku_id = State()
    waiting_availability_id = State()
    waiting_amount = State()
    waiting_product_name = State()


# временное хранилище данных при добавлении товара (по user_id)
_product_drafts: dict[int, dict] = {}


# ===================== Клавиатуры =====================

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001F47E Тексты для заказов Roblox", callback_data="menu:texts")],
        [InlineKeyboardButton(text="\U0001F4DC Логи", callback_data="menu:logs")],
        [InlineKeyboardButton(text="\U0001F6CD Товары", callback_data="menu:products")],
    ])


def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u2B05 Главное меню", callback_data="menu:main")],
    ])


def texts_menu_kb() -> InlineKeyboardMarkup:
    rows = []
    for row in db.get_all_texts():
        status = "\U0001F7E2 вкл" if row["enabled"] else "\U0001F534 выкл"
        rows.append([
            InlineKeyboardButton(text=f"\U0001F94F {row['description']}", callback_data=f"text:open:{row['key']}"),
            InlineKeyboardButton(text=status, callback_data=f"text:toggle:{row['key']}"),
        ])
    rows.append([InlineKeyboardButton(text="\u2B05 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def text_detail_kb(key: str, enabled: bool) -> InlineKeyboardMarkup:
    toggle_label = "\U0001F534 Выключить" if enabled else "\U0001F7E2 Включить"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u270F\uFE0F Изменить текст", callback_data=f"text:edit:{key}")],
        [InlineKeyboardButton(text=toggle_label, callback_data=f"text:toggle:{key}")],
        [InlineKeyboardButton(text="\u2B05 К списку текстов", callback_data="menu:texts")],
    ])


def logs_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Все", callback_data="logs:all"),
            InlineKeyboardButton(text="Только ошибки", callback_data="logs:ERROR"),
        ],
        [InlineKeyboardButton(text="\U0001F504 Обновить", callback_data="logs:all")],
        [InlineKeyboardButton(text="\u2B05 Главное меню", callback_data="menu:main")],
    ])


def products_menu_kb() -> InlineKeyboardMarkup:
    rows = []
    for p in db.get_all_products():
        rows.append([
            InlineKeyboardButton(text=f"{p['item_name']} → {p['product_name'] or p['product_id']}", callback_data=f"product:open:{p['item_name']}"),
        ])
    rows.append([InlineKeyboardButton(text="\u2795 Добавить товар", callback_data="product:add")])
    rows.append([InlineKeyboardButton(text="\u2B05 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_detail_kb(item_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001F5D1 Удалить", callback_data=f"product:delete:{item_name}")],
        [InlineKeyboardButton(text="\u2B05 К списку товаров", callback_data="menu:products")],
    ])


# ===================== Хендлеры: главное меню =====================

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("\u26D4 Доступ запрещён.")
        return
    await state.clear()
    await message.answer(
        "\U0001F47E <b>Roblox бот - панель управления</b>\n\nВыберите раздел:",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "menu:main")
async def cb_main_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "\U0001F47E <b>Roblox бот - панель управления</b>\n\nВыберите раздел:",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )
    await call.answer()


# ===================== Хендлеры: Тексты =====================

@dp.callback_query(F.data == "menu:texts")
async def cb_texts_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "\U0001F47E <b>Тексты для заказов Roblox.</b>\n\n"
        "Нажмите на текст, чтобы посмотреть/изменить его, "
        "или на индикатор справа, чтобы включить/выключить отправку.",
        reply_markup=texts_menu_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@dp.callback_query(F.data.startswith("text:toggle:"))
async def cb_text_toggle(call: CallbackQuery):
    key = call.data.split(":", 2)[2]
    new_state = db.toggle_text(key)
    db.add_log("INFO", "admin", f"Текст '{key}' переключен в состояние {'вкл' if new_state else 'выкл'}")

    # если открыта карточка текста - обновим её, иначе общий список
    try:
        row = db.get_text_row(key)
        text_preview = row["text"]
        status = "\U0001F7E2 включён" if new_state else "\U0001F534 выключен"
        await call.message.edit_text(
            f"<b>{row['description']}</b>\nСтатус: {status}\n\n"
            f"Текущий текст:\n<code>{text_preview}</code>",
            reply_markup=text_detail_kb(key, new_state),
            parse_mode="HTML",
        )
    except Exception:
        await call.message.edit_reply_markup(reply_markup=texts_menu_kb())
    await call.answer("Готово")


@dp.callback_query(F.data.startswith("text:open:"))
async def cb_text_open(call: CallbackQuery):
    key = call.data.split(":", 2)[2]
    row = db.get_text_row(key)
    status = "\U0001F7E2 включён" if row["enabled"] else "\U0001F534 выключен"
    await call.message.edit_text(
        f"<b>{row['description']}</b>\nСтатус: {status}\n\n"
        f"Текущий текст:\n<code>{row['text']}</code>\n\n"
        f"<i>Доступные подстановки в тексте (если есть): {{url}}, {{expires}}, {{reason}}</i>",
        reply_markup=text_detail_kb(key, bool(row["enabled"])),
        parse_mode="HTML",
    )
    await call.answer()


@dp.callback_query(F.data.startswith("text:edit:"))
async def cb_text_edit(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 2)[2]
    await state.update_data(edit_key=key)
    await state.set_state(EditText.waiting_text)
    row = db.get_text_row(key)
    await call.message.edit_text(
        f"Отправьте новый текст для:\n<b>{row['description']}</b>\n\n"
        f"Текущий текст:\n<code>{row['text']}</code>\n\n"
        f"Для отмены отправьте /cancel",
        parse_mode="HTML",
    )
    await call.answer()


@dp.message(EditText.waiting_text)
async def msg_text_edit(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.", reply_markup=back_to_main_kb())
        return

    data = await state.get_data()
    key = data["edit_key"]
    db.set_text(key, message.text)
    db.add_log("INFO", "admin", f"Текст '{key}' изменён администратором")
    await state.clear()

    row = db.get_text_row(key)
    status = "\U0001F7E2 включён" if row["enabled"] else "\U0001F534 выключен"
    await message.answer(
        f"\u2705 Текст обновлён.\n\n<b>{row['description']}</b>\nСтатус: {status}\n\n"
        f"Новый текст:\n<code>{row['text']}</code>",
        reply_markup=text_detail_kb(key, bool(row["enabled"])),
        parse_mode="HTML",
    )


# ===================== Хендлеры: Логи =====================

LOG_LEVEL_EMOJI = {
    "INFO": "\u2139\uFE0F",
    "WARNING": "\u26A0\uFE0F",
    "ERROR": "\u274C",
}


def format_logs(rows) -> str:
    if not rows:
        return "Логов пока нет."
    lines = []
    for r in reversed(rows):  # от старых к новым
        import datetime
        ts = datetime.datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S")
        emoji = LOG_LEVEL_EMOJI.get(r["level"], "\u2022")
        lines.append(f"{emoji} <code>{ts}</code> [{r['source']}] {r['message']}")
    return "\n".join(lines)


@dp.callback_query(F.data == "menu:logs")
async def cb_logs_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    rows = db.get_recent_logs(limit=20)
    text = "\U0001F4DC <b>Последние события бота</b>\n\n" + format_logs(rows)
    if len(text) > 4000:
        text = text[-4000:]
    await call.message.edit_text(text, reply_markup=logs_menu_kb(), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "logs:all")
async def cb_logs_all(call: CallbackQuery):
    rows = db.get_recent_logs(limit=20)
    text = "\U0001F4DC <b>Последние события бота</b>\n\n" + format_logs(rows)
    if len(text) > 4000:
        text = text[-4000:]
    try:
        await call.message.edit_text(text, reply_markup=logs_menu_kb(), parse_mode="HTML")
    except Exception:
        pass  # сообщение не изменилось
    await call.answer("Обновлено")


@dp.callback_query(F.data == "logs:ERROR")
async def cb_logs_errors(call: CallbackQuery):
    rows = db.get_recent_logs(limit=20, level="ERROR")
    text = "\u274C <b>Последние ошибки</b>\n\n" + format_logs(rows)
    if len(text) > 4000:
        text = text[-4000:]
    try:
        await call.message.edit_text(text, reply_markup=logs_menu_kb(), parse_mode="HTML")
    except Exception:
        pass
    await call.answer("Обновлено")


# ===================== Хендлеры: Товары =====================

@dp.callback_query(F.data == "menu:products")
async def cb_products_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "\U0001F6CD <b>Товары (сопоставление с Robux SKU на Swizzyer)</b>\n\n"
        "Название товара должно совпадать (или быть похожим) с названием "
        "предмета на Playerok.",
        reply_markup=products_menu_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@dp.callback_query(F.data.startswith("product:open:"))
async def cb_product_open(call: CallbackQuery):
    item_name = call.data.split(":", 2)[2]
    p = db.get_product_mapping(item_name)
    if not p:
        await call.answer("Не найдено", show_alert=True)
        return
    text = (
        f"<b>{p['item_name']}</b>\n\n"
        f"product_id: <code>{p['product_id']}</code>\n"
        f"sku_id: <code>{p['sku_id']}</code>\n"
        f"availability_id: <code>{p['availability_id']}</code>\n"
        f"amount: {p['amount']}\n"
        f"product_name: {p['product_name'] or '-'}"
    )
    await call.message.edit_text(text, reply_markup=product_detail_kb(item_name), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data.startswith("product:delete:"))
async def cb_product_delete(call: CallbackQuery):
    item_name = call.data.split(":", 2)[2]
    db.delete_product(item_name)
    db.add_log("INFO", "admin", f"Товар '{item_name}' удалён из каталога")
    await call.message.edit_text("\u2705 Товар удалён.", reply_markup=products_menu_kb())
    await call.answer()


@dp.callback_query(F.data == "product:add")
async def cb_product_add(call: CallbackQuery, state: FSMContext):
    _product_drafts[call.from_user.id] = {}
    await state.set_state(AddProduct.waiting_item_name)
    await call.message.edit_text(
        "Введите название товара (как на Playerok), например:\n<code>1000 R$</code>\n\n/cancel для отмены",
        parse_mode="HTML",
    )
    await call.answer()


@dp.message(AddProduct.waiting_item_name)
async def add_product_item_name(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.", reply_markup=back_to_main_kb())
        return
    _product_drafts[message.from_user.id]["item_name"] = message.text.strip()
    await state.set_state(AddProduct.waiting_product_id)
    await message.answer("Введите <b>product_id</b> (из дашборда Swizzyer), например:\n<code>9NRQLWSN0K89</code>", parse_mode="HTML")


@dp.message(AddProduct.waiting_product_id)
async def add_product_product_id(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.", reply_markup=back_to_main_kb())
        return
    _product_drafts[message.from_user.id]["product_id"] = message.text.strip()
    await state.set_state(AddProduct.waiting_sku_id)
    await message.answer("Введите <b>sku_id</b> (обычно <code>0010</code> для Robux):", parse_mode="HTML")


@dp.message(AddProduct.waiting_sku_id)
async def add_product_sku_id(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.", reply_markup=back_to_main_kb())
        return
    _product_drafts[message.from_user.id]["sku_id"] = message.text.strip()
    await state.set_state(AddProduct.waiting_availability_id)
    await message.answer("Введите <b>availability_id</b>:", parse_mode="HTML")


@dp.message(AddProduct.waiting_availability_id)
async def add_product_availability_id(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.", reply_markup=back_to_main_kb())
        return
    _product_drafts[message.from_user.id]["availability_id"] = message.text.strip()
    await state.set_state(AddProduct.waiting_amount)
    await message.answer("Введите цену в USD (например <code>9.99</code>):", parse_mode="HTML")


@dp.message(AddProduct.waiting_amount)
async def add_product_amount(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.", reply_markup=back_to_main_kb())
        return
    try:
        amount = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Введите число, например 9.99")
        return
    _product_drafts[message.from_user.id]["amount"] = amount
    await state.set_state(AddProduct.waiting_product_name)
    await message.answer(
        "Введите отображаемое название товара (как в Swizzyer Products), "
        "или отправьте «-» чтобы оставить пустым:"
    )


@dp.message(AddProduct.waiting_product_name)
async def add_product_product_name(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.", reply_markup=back_to_main_kb())
        return

    draft = _product_drafts.pop(message.from_user.id, {})
    product_name = None if message.text.strip() == "-" else message.text.strip()

    db.upsert_product(
        item_name=draft["item_name"],
        product_id=draft["product_id"],
        sku_id=draft["sku_id"],
        availability_id=draft["availability_id"],
        amount=draft["amount"],
        product_name=product_name,
    )
    db.add_log("INFO", "admin", f"Добавлен/обновлён товар '{draft['item_name']}'")
    await state.clear()

    await message.answer(
        f"\u2705 Товар <b>{draft['item_name']}</b> сохранён.",
        reply_markup=products_menu_kb(),
        parse_mode="HTML",
    )


# ===================== Запуск =====================

async def main():
    db.init_db()
    db.add_log("INFO", "system", "Telegram admin-бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
