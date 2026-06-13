"""
Минимальный клиент для Swizzyer Public API (2faroblox.com).

Реализует только то, что нужно для flow:
mode=hosted_link с pre-seeded credentials.
"""

import uuid
import requests

import config


class SwizzyerError(Exception):
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload
        try:
            msg = payload["error"]["message"]["ru"]
        except Exception:
            msg = str(payload)
        super().__init__(f"[{status_code}] {msg}")


class SwizzyerClient:
    def __init__(self, api_key: str = None, base_url: str = None):
        self.api_key = api_key or config.SWIZZYER_API_KEY
        self.base_url = (base_url or config.SWIZZYER_API_BASE).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _request(self, method, path, json_body=None, idempotency_key=None, params=None):
        url = f"{self.base_url}{path}"
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        resp = self.session.request(method, url, json=json_body, headers=headers, params=params, timeout=30)

        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except Exception:
                payload = {"raw": resp.text}
            raise SwizzyerError(resp.status_code, payload)

        if resp.content:
            return resp.json()
        return None

    # ---------- Orders ----------

    def create_hosted_link_order(
        self,
        username: str,
        password: str,
        items: list[dict],
        language: str = "ru",
        metadata: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """
        Создаёт заказ mode=hosted_link с pre-seeded credentials.
        Покупателю нужно будет только пройти 2FA по ссылке из
        order["verification"]["url"].
        """
        body = {
            "mode": "hosted_link",
            "credentials": {
                "username": username,
                "password": password,
            },
            "items": items,
            "language": language,
        }
        if metadata:
            body["metadata"] = metadata

        idem = idempotency_key or str(uuid.uuid4())
        return self._request("POST", "/v1/orders", json_body=body, idempotency_key=idem)

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/v1/orders/{order_id}")

    def cancel_order(self, order_id: str) -> dict:
        idem = str(uuid.uuid4())
        return self._request("POST", f"/v1/orders/{order_id}/cancel", idempotency_key=idem)

    def refresh_verification(self, order_id: str) -> dict:
        idem = str(uuid.uuid4())
        return self._request("POST", f"/v1/orders/{order_id}/refresh_verification", idempotency_key=idem)

    def get_order_events(self, order_id: str) -> dict:
        return self._request("GET", f"/v1/orders/{order_id}/events")

    # ---------- Subscription ----------

    def get_subscription(self) -> dict:
        return self._request("GET", "/v1/subscription")

    # ---------- Meta ----------

    def health(self) -> dict:
        return self._request("GET", "/v1/health")
