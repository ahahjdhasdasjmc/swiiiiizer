"""
Playerok-бот.

Слушает события Playerok через EventListener и:
  - при новой оплаченной сделке категории Roblox запрашивает логин/пароль
  - при получении логина/пароля создаёт hosted_link заказ на 2faroblox.com
    с pre-seeded credentials и отправляет покупателю verify-ссылку
  - если данные неверны - просит ввести их заново
  - следит за статусом заказа и завершает сделку на Playerok после успеха
  - пишет "после подтверждения" когда покупатель подтвердил сделку

Все события и ошибки пишутся в SQLite (db.py) и видны в Telegram-панели.

Запуск:
    python playerok_bot.py
"""

import logging

from playerokapi.account import Account
from playerokapi.enums import EventTypes
from playerokapi.listener.listener import EventListener

import config
import db
from order_processor import OrderProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("roblox_bot")


def main():
    db.init_db()
    db.add_log("INFO", "system", "Playerok-бот запускается...")

    try:
        acc = Account(
            token=config.PLAYEROK_TOKEN,
            user_agent=config.PLAYEROK_USER_AGENT,
        ).get()
    except Exception as e:
        db.add_log("ERROR", "system", f"Не удалось авторизоваться в Playerok: {e!r}")
        raise

    db.add_log("INFO", "system", f"Авторизован как {acc.username} (id={acc.id})")
    logger.info(f"Авторизован как {acc.username} (id={acc.id})")

    processor = OrderProcessor(acc)
    listener = EventListener(acc)

    for event in listener.listen():
        try:
            if event.type in (EventTypes.NEW_DEAL, EventTypes.ITEM_PAID):
                processor.handle_new_deal(event.deal, event.chat)

            elif event.type is EventTypes.DEAL_CONFIRMED:
                processor.handle_deal_confirmed(event.deal, event.chat)

            elif event.type is EventTypes.NEW_MESSAGE:
                if event.message.user and event.message.user.id == acc.id:
                    continue
                processor.handle_message(event.message, event.chat)

        except Exception as e:
            logger.exception("Ошибка обработки события")
            db.add_log("ERROR", "system", f"Ошибка обработки события {event.type}: {e!r}")


if __name__ == "__main__":
    main()
