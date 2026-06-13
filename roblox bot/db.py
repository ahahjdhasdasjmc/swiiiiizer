"""
SQLite-хранилище: настраиваемые тексты, логи событий, маппинг товаров.

Используется и Playerok-ботом (чтение текстов, запись логов),
и Telegram admin-ботом (редактирование текстов, чтение логов).
"""

import sqlite3
import threading
import time
from contextlib import contextmanager

DB_PATH = "bot.db"

_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_conn():
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


# ===================== Тексты =====================

# key -> (description, default_text, enabled_by_default)
TEXT_DEFAULTS = {
    "ask_credentials": (
        "Не указали логин и пароль",
        "Здравствуйте, укажите логин и пароль от Roblox.",
        True,
    ),
    "got_credentials": (
        "Ответ после данных",
        "Увидел ваши данные, ожидайте пожалуйста, как куплю - "
        "напишу, все заказы выполняются в порядке очереди.",
        True,
    ),
    "credentials_invalid_format": (
        "Неверный формат данных",
        "Не получилось распознать данные. Отправьте, пожалуйста, в формате:\n"
        "почта/логин:пароль",
        True,
    ),
    "credentials_rejected": (
        "Данные неверные (отклонено Roblox/Swizzyer)",
        "Данные от вашего аккаунта неверные, проверьте их ещё раз и отправьте, пожалуйста, заново.",
        True,
    ),
    "credentials_accepted": (
        "Данные верные, ожидаем 2FA",
        "Данные верны! Перейдите по ссылке ниже и подтвердите вход (2FA):\n{url}\n\n"
        "Ссылка действительна до: {expires}",
        True,
    ),
    "order_completed": (
        "После выполнения",
        "Заказ выполнен! Проверьте получение товара и подтвердите сделку, "
        "буду благодарен за оставленный вами отзыв и рекомендацию друзьям =)",
        True,
    ),
    "after_confirmation": (
        "После подтверждения",
        "Буду ждать ещё! Так же если вас интересуют какие-то акции "
        "- всегда могу помочь по очень хорошим ценам.",
        True,
    ),
    "order_failed": (
        "Заказ не выполнен (общая ошибка)",
        "Возникла проблема при выполнении заказа ({reason}). "
        "Свяжитесь со мной в чате, разберёмся вручную.",
        True,
    ),
    "manual_processing": (
        "Товар не найден в каталоге (ручная обработка)",
        "Здравствуйте! Ваш заказ принят, но требует ручной обработки. "
        "Свяжитесь со мной, пожалуйста, я выполню заказ вручную.",
        True,
    ),
    "verification_expired": (
        "Время на 2FA истекло",
        "Время на подтверждение (2FA) истекло. Напишите, пожалуйста, и я перевыпущу ссылку.",
        True,
    ),
}


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS texts (
                key TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                text TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                level TEXT NOT NULL,
                source TEXT NOT NULL,
                message TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                item_name TEXT PRIMARY KEY,
                product_id TEXT NOT NULL,
                sku_id TEXT NOT NULL,
                availability_id TEXT NOT NULL,
                amount REAL NOT NULL,
                product_name TEXT
            )
        """)

        for key, (desc, default_text, enabled) in TEXT_DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO texts (key, description, text, enabled) VALUES (?, ?, ?, ?)",
                (key, desc, default_text, int(enabled)),
            )


# ===================== Тексты: API =====================

def get_text(key: str) -> str | None:
    """
    Возвращает текст для key, либо None если этот текст отключён (enabled=0)
    - в этом случае бот не должен отправлять сообщение для этого шага.
    """
    with get_conn() as conn:
        row = conn.execute("SELECT text, enabled FROM texts WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        if not row["enabled"]:
            return None
        return row["text"]


def get_all_texts() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT key, description, text, enabled FROM texts ORDER BY key").fetchall()


def get_text_row(key: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT key, description, text, enabled FROM texts WHERE key = ?", (key,)).fetchone()


def set_text(key: str, text: str):
    with get_conn() as conn:
        conn.execute("UPDATE texts SET text = ? WHERE key = ?", (text, key))


def toggle_text(key: str) -> bool:
    """Переключает enabled, возвращает новое значение."""
    with get_conn() as conn:
        row = conn.execute("SELECT enabled FROM texts WHERE key = ?", (key,)).fetchone()
        new_val = 0 if row["enabled"] else 1
        conn.execute("UPDATE texts SET enabled = ? WHERE key = ?", (new_val, key))
        return bool(new_val)


# ===================== Логи =====================

def add_log(level: str, source: str, message: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO logs (ts, level, source, message) VALUES (?, ?, ?, ?)",
            (time.time(), level, source, message),
        )
        # Чистим старые записи, оставляем последние 2000
        conn.execute("""
            DELETE FROM logs WHERE id NOT IN (
                SELECT id FROM logs ORDER BY id DESC LIMIT 2000
            )
        """)


def get_recent_logs(limit: int = 20, level: str | None = None) -> list[sqlite3.Row]:
    with get_conn() as conn:
        if level:
            return conn.execute(
                "SELECT * FROM logs WHERE level = ? ORDER BY id DESC LIMIT ?",
                (level, limit),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def get_logs_since(last_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM logs WHERE id > ? ORDER BY id ASC", (last_id,)
        ).fetchall()


# ===================== Товары / маппинг =====================

def get_product_mapping(item_name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE item_name = ?", (item_name,)
        ).fetchone()
        if row:
            return dict(row)

        # fuzzy match по подстроке
        rows = conn.execute("SELECT * FROM products").fetchall()
        for r in rows:
            if r["item_name"].lower() in item_name.lower() or item_name.lower() in r["item_name"].lower():
                return dict(r)
    return None


def upsert_product(item_name, product_id, sku_id, availability_id, amount, product_name=None):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO products (item_name, product_id, sku_id, availability_id, amount, product_name)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_name) DO UPDATE SET
                product_id=excluded.product_id,
                sku_id=excluded.sku_id,
                availability_id=excluded.availability_id,
                amount=excluded.amount,
                product_name=excluded.product_name
        """, (item_name, product_id, sku_id, availability_id, amount, product_name))


def get_all_products() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM products ORDER BY item_name").fetchall()


def delete_product(item_name: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM products WHERE item_name = ?", (item_name,))
