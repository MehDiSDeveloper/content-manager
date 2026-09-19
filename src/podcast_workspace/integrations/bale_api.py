"""Minimal client for the Bale bot API (Telegram-compatible, https://docs.bale.ai).

Blocking; meant for the bot's own worker thread. Every failure surfaces as a BaleError
subclass so the caller can stay quiet and retry instead of crashing.
"""

from pathlib import Path
from typing import Any

import requests

API_BASE = "https://tapi.bale.ai"
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # Bale's getFile limit for bots
CONNECT_TIMEOUT_S = 10


class BaleError(Exception):
    pass


class BaleNetworkError(BaleError):
    """No connection, DNS failure, timeout, or a 5xx from the server."""


class BaleUnauthorizedError(BaleError):
    """The token was rejected; retrying will not help until it changes."""


class BaleApiError(BaleError):
    def __init__(self, code: int, description: str) -> None:
        super().__init__(f"{code}: {description}")
        self.code = code
        self.description = description


class FileTooLargeError(BaleError):
    pass


class BaleClient:
    def __init__(self, token: str) -> None:
        self._token = token.strip()
        self._http = requests.Session()

    def close(self) -> None:
        self._http.close()

    def call(self, method: str, read_timeout: float = 30, **params: Any) -> Any:
        url = f"{API_BASE}/bot{self._token}/{method}"
        payload = {k: v for k, v in params.items() if v is not None}
        try:
            response = self._http.post(url, json=payload, timeout=(CONNECT_TIMEOUT_S, read_timeout))
        except requests.RequestException as exc:
            raise BaleNetworkError(str(exc)) from exc
        if response.status_code in (401, 403, 404) and not _looks_like_json(response):
            raise BaleUnauthorizedError(response.text[:200])
        if response.status_code >= 500:
            raise BaleNetworkError(f"HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise BaleNetworkError(f"HTTP {response.status_code}: not JSON") from exc
        if not body.get("ok"):
            code = int(body.get("error_code") or response.status_code)
            description = str(body.get("description") or "")
            if code in (401, 403) or (code == 404 and "not found" in description.lower()):
                raise BaleUnauthorizedError(description)
            raise BaleApiError(code, description)
        return body.get("result")

    # methods ---------------------------------------------------------------------------
    def get_me(self) -> dict[str, Any]:
        return self.call("getMe")

    def delete_webhook(self) -> None:
        self.call("deleteWebhook")

    def get_updates(self, offset: int | None, timeout_s: int) -> list[dict[str, Any]]:
        result = self.call(
            "getUpdates",
            read_timeout=timeout_s + 15,
            offset=offset,
            timeout=timeout_s,
            allowed_updates=["message", "callback_query"],
        )
        return list(result or [])

    def send_message(
        self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self.call("sendMessage", chat_id=chat_id, text=text, reply_markup=reply_markup)

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        self.call(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup or {"inline_keyboard": []},
        )

    def answer_callback_query(
        self, callback_id: str, text: str | None = None, show_alert: bool = False
    ) -> None:
        self.call(
            "answerCallbackQuery", callback_query_id=callback_id, text=text, show_alert=show_alert
        )

    def get_file(self, file_id: str) -> dict[str, Any]:
        return self.call("getFile", file_id=file_id)

    def download(self, file_path: str, target: Path) -> None:
        """Stream a file from getFile's `file_path` to `target` (atomic: .part then rename)."""
        url = f"{API_BASE}/file/bot{self._token}/{file_path}"
        partial = target.with_name(target.name + ".part")
        try:
            with self._http.get(url, stream=True, timeout=(CONNECT_TIMEOUT_S, 120)) as response:
                if response.status_code != 200:
                    raise BaleApiError(response.status_code, "file download failed")
                written = 0
                with partial.open("wb") as out:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        written += len(chunk)
                        if written > MAX_DOWNLOAD_BYTES * 2:  # server should never send this
                            raise FileTooLargeError(file_path)
                        out.write(chunk)
            partial.replace(target)
        except requests.RequestException as exc:
            raise BaleNetworkError(str(exc)) from exc
        finally:
            partial.unlink(missing_ok=True)


def _looks_like_json(response: requests.Response) -> bool:
    return "json" in response.headers.get("Content-Type", "")
