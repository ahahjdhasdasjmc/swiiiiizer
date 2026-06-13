"""
Логика обработки сделок категории Roblox.

Тексты ответов и маппинг товаров берутся из SQLite (db.py),
настраиваются через Telegram admin-бота.
Все действия и ошибки пишутся в лог (db.add_log) - их видно в TG-панели.

Состояния сделки (in-memory, по deal_id):
  AWAITING_CREDENTIALS  -> ждём логин:пароль от покупателя
  AWAITING_VERIFICATION -> заказ создан на 2faroblox, ждём 2FA от покупателя
  DONE / FAILED         -> терминальные состояния
"""

import re
import time
import threading
import logging
from datetime import datetime, timezone

import config
import db
from swizzyer_client import SwizzyerClient, SwizzyerError

logger = logging.getLogger("roblox_bot.orders")

CREDENTIALS_RE = re.compile(r"^\s*([^:\s]+)\s*[:|]\s*(.+?)\s*$")

# Коды failure_reason / order status, означающие "данные неверные"
CREDENTIALS_BAD_HINTS = (
    "credentials_rejected",
    "invalid_credentials",
    "wrong_password",
    "login_failed",
    "incorrect_password",
)


class DealState:
    AWAITING_CREDENTIALS = "awaiting_credentials"
    AWAITING_VERIFICATION = "awaiting_verification"
    DONE = "done"
    FAILED = "failed"


def _log(level: str, msg: str, source: str = "orders"):
    getattr(logger, level)(msg)
    db.add_log(level.upper(), source, msg)


class OrderProcessor:
    """
    Хранит состояние активных Roblox-сделок и взаимодействует со Swizzyer.
    """

    def __init__(self, account, swizzyer: SwizzyerClient | None = None):
        self.account = account
        self.swizzyer = swizzyer or SwizzyerClient()
        self.deals: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ---------- Отправка сообщений с учётом включён/выключен текст ----------

    def _send(self, chat_id: str, text_key: str, **fmt):
        text = db.get_text(text_key)
        if text is None:
            _log("info", f"Текст '{text_key}' выключен - сообщение не отправлено (chat={chat_id})")
            return
        try:
            text = text.format(**fmt)
        except Exception:
            pass
        try:
            self.account.send_message(chat_id, text, mark_chat_as_read=True)
            _log("info", f"Отправлено сообщение [{text_key}] в чат {chat_id}")
        except Exception as e:
            _log("error", f"Ошибка отправки сообщения [{text_key}] в чат {chat_id}: {e!r}")

    # ---------- Вспомогательное ----------

    def is_roblox_item(self, item) -> bool:
        """Проверяет, относится ли предмет сделки к категории Roblox."""
        try:
            category_name = item.category.name
        except Exception:
            category_name = ""
        try:
            game_name = item.game.name
        except Exception:
            game_name = ""

        target = config.ROBLOX_GAME_CATEGORY_NAME.lower()
        return target in category_name.lower() or target in game_name.lower()

    # ---------- Обработка новой сделки ----------

    def handle_new_deal(self, deal, chat):
        """
        Вызывается на событие NewDealEvent / ItemPaidEvent.
        Если предмет относится к Roblox - запрашиваем логин/пароль.
        """
        item = deal.item

        if not self.is_roblox_item(item):
            return

        _log("info", f"Новая сделка {deal.id}: товар '{item.name}'")

        mapping = db.get_product_mapping(item.name or "")
        if mapping is None:
            _log("warning", f"Сделка {deal.id}: товар '{item.name}' не найден в каталоге продуктов - ручная обработка")
            self._send(chat.id, "manual_processing")
            return

        with self._lock:
            self.deals[deal.id] = {
                "state": DealState.AWAITING_CREDENTIALS,
                "chat_id": chat.id,
                "item": item,
                "mapping": mapping,
                "swizzyer_order_id": None,
            }

        self._send(chat.id, "ask_credentials")
        _log("info", f"Сделка {deal.id}: запросили логин/пароль у покупателя")

    # ---------- Обработка сообщений от покупателя ----------

    def handle_message(self, message, chat) -> bool:
        """
        Вызывается на NewMessageEvent.
        Возвращает True, если сообщение было обработано как часть Roblox-флоу.
        """
        deal_id = self._find_deal_id_for_chat(chat.id)
        if deal_id is None:
            return False

        state_info = self.deals.get(deal_id)
        if not state_info:
            return False

        if state_info["state"] == DealState.AWAITING_CREDENTIALS:
            return self._handle_credentials_message(deal_id, message, chat)

        return False

    def _find_deal_id_for_chat(self, chat_id: str) -> str | None:
        with self._lock:
            for deal_id, info in self.deals.items():
                if info["chat_id"] == chat_id and info["state"] in (
                    DealState.AWAITING_CREDENTIALS,
                    DealState.AWAITING_VERIFICATION,
                ):
                    return deal_id
        return None

    def _handle_credentials_message(self, deal_id, message, chat) -> bool:
        text = (message.text or "").strip()
        match = CREDENTIALS_RE.match(text)
        if not match:
            self._send(chat.id, "credentials_invalid_format")
            _log("info", f"Сделка {deal_id}: покупатель прислал текст не в формате логин:пароль")
            return True

        username, password = match.group(1), match.group(2)

        self._send(chat.id, "got_credentials")
        _log("info", f"Сделка {deal_id}: получены данные аккаунта от покупателя ({username})")

        info = self.deals[deal_id]
        mapping = info["mapping"]

        item_payload = {
            "product_id": mapping["product_id"],
            "sku_id": mapping["sku_id"],
            "availability_id": mapping["availability_id"],
            "quantity": 1,
            "product_name": mapping.get("product_name"),
            "amount": mapping.get("amount"),
        }

        try:
            order = self.swizzyer.create_hosted_link_order(
                username=username,
                password=password,
                items=[item_payload],
                language="ru",
                metadata={"bot_order_id": deal_id},
                idempotency_key=f"deal-{deal_id}",
            )
        except SwizzyerError as e:
            _log("error", f"Сделка {deal_id}: ошибка создания заказа на Swizzyer: {e}")
            self._send(chat.id, "order_failed", reason="ошибка создания заказа")
            with self._lock:
                info["state"] = DealState.FAILED
            return True

        with self._lock:
            info["swizzyer_order_id"] = order["id"]

        _log("info", f"Сделка {deal_id}: создан заказ Swizzyer {order['id']}, статус={order.get('status')}")

        threading.Thread(
            target=self._poll_order_status,
            args=(deal_id,),
            daemon=True,
        ).start()

        return True

    # ---------- Поллинг статуса заказа на Swizzyer ----------

    def _poll_order_status(self, deal_id: str):
        info = self.deals.get(deal_id)
        if not info:
            return

        order_id = info["swizzyer_order_id"]
        chat_id = info["chat_id"]

        deadline = time.time() + config.SWIZZYER_POLL_TIMEOUT_SEC
        sent_verification_link = False

        while time.time() < deadline:
            time.sleep(config.SWIZZYER_POLL_INTERVAL_SEC)

            try:
                order = self.swizzyer.get_order(order_id)
            except SwizzyerError as e:
                _log("error", f"Сделка {deal_id}: ошибка опроса заказа {order_id}: {e}")
                continue

            status = order.get("status")

            if not sent_verification_link:
                verification = order.get("verification") or {}
                url = verification.get("url")
                if url and status in ("pending_verification", "verifying", "requires_action"):
                    if status == "requires_action" and self._is_bad_credentials(order):
                        self._on_bad_credentials(deal_id, order)
                        return

                    expires_at = verification.get("expires_at")
                    expires_str = (
                        datetime.fromtimestamp(expires_at, tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
                        if expires_at else "—"
                    )
                    self._send(chat_id, "credentials_accepted", url=url, expires=expires_str)
                    _log("info", f"Сделка {deal_id}: данные верны, ссылка на 2FA отправлена покупателю")
                    sent_verification_link = True
                    continue

            if status == "completed":
                self._finish_deal_success(deal_id)
                return

            if status == "requires_action" and self._is_bad_credentials(order):
                self._on_bad_credentials(deal_id, order)
                return

            if status == "expired":
                self._send(chat_id, "verification_expired")
                _log("warning", f"Сделка {deal_id}: время на 2FA истекло (order {order_id})")
                with self._lock:
                    info["state"] = DealState.FAILED
                return

            if status in ("failed", "cancelled", "partially_delivered"):
                reason = (order.get("failure_reason") or {}).get("code", status)
                self._finish_deal_failure(deal_id, reason)
                return

            with self._lock:
                info["state"] = DealState.AWAITING_VERIFICATION

        _log("warning", f"Сделка {deal_id}: таймаут ожидания завершения заказа {order_id}")
        self._send(chat_id, "order_failed", reason="истекло время ожидания подтверждения 2FA")
        with self._lock:
            info["state"] = DealState.FAILED

    @staticmethod
    def _is_bad_credentials(order: dict) -> bool:
        failure_reason = order.get("failure_reason") or {}
        code = (failure_reason.get("code") or "").lower()
        return any(hint in code for hint in CREDENTIALS_BAD_HINTS)

    def _on_bad_credentials(self, deal_id: str, order: dict):
        info = self.deals.get(deal_id)
        if not info:
            return

        chat_id = info["chat_id"]
        self._send(chat_id, "credentials_rejected")
        _log("warning", f"Сделка {deal_id}: данные аккаунта отклонены, запрашиваем заново")

        with self._lock:
            info["state"] = DealState.AWAITING_CREDENTIALS
            info["swizzyer_order_id"] = None

        try:
            self.swizzyer.cancel_order(order["id"])
        except SwizzyerError:
            pass

    def _finish_deal_success(self, deal_id: str):
        info = self.deals.get(deal_id)
        if not info:
            return

        chat_id = info["chat_id"]

        self._send(chat_id, "order_completed")

        try:
            from playerokapi.enums import ItemDealStatuses
            self.account.update_deal(deal_id, ItemDealStatuses.SENT)
            _log("info", f"Сделка {deal_id}: статус на Playerok обновлён на SENT")
        except Exception as e:
            _log("error", f"Сделка {deal_id}: не удалось обновить статус сделки на Playerok: {e!r}")

        with self._lock:
            info["state"] = DealState.DONE

        _log("info", f"Сделка {deal_id}: успешно завершена")

    def _finish_deal_failure(self, deal_id: str, reason: str):
        info = self.deals.get(deal_id)
        if not info:
            return

        chat_id = info["chat_id"]

        self._send(chat_id, "order_failed", reason=reason)

        with self._lock:
            info["state"] = DealState.FAILED

        _log("warning", f"Сделка {deal_id}: завершена с ошибкой ({reason})")

    # ---------- После подтверждения сделки покупателем ----------

    def handle_deal_confirmed(self, deal, chat):
        """Вызывается на событие DEAL_CONFIRMED - покупатель подтвердил сделку."""
        if not self.is_roblox_item(deal.item):
            return
        self._send(chat.id, "after_confirmation")
        _log("info", f"Сделка {deal.id}: покупатель подтвердил сделку, отправлен текст 'после подтверждения'")
