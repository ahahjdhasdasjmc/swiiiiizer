"""
Конфигурация бота.

Заполни своими данными перед запуском.
Тексты ответов и маппинг товаров настраиваются через Telegram admin-бота
и хранятся в SQLite (db.py) - см. README.
"""

# ===== Playerok =====
PLAYEROK_TOKEN = "вставь_свой_токен_плеерок"
PLAYEROK_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

# Название категории игры в Playerok, заказы из которой обрабатывает бот
ROBLOX_GAME_CATEGORY_NAME = "Roblox"

# ===== Swizzyer / 2faroblox.com =====
SWIZZYER_API_BASE = "https://2faroblox.com"
SWIZZYER_API_KEY = "swz_live_вставь_свой_ключ"

# ===== Telegram admin-бот =====
TG_BOT_TOKEN = "вставь_токен_телеграм_бота"
# ID пользователей Telegram, которым разрешён доступ к панели (твой личный ID)
TG_ADMIN_IDS = [123456789]

# Polling настройки
SWIZZYER_POLL_INTERVAL_SEC = 10
SWIZZYER_POLL_TIMEOUT_SEC = 60 * 30  # 30 минут максимум ждём верификацию
