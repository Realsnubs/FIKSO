"""SMS through an EU provider (Q-08). Messente (Estonia, EU data processing) is implemented; others plug
in via
`SmsSender`. A message counts as sent only when the provider accepted it and returned its message ID; delivery
is confirmed later by the provider's delivery report (webhook). Phone numbers and texts are never logged."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import httpx

from app.core.config import get_settings


class SmsError(Exception):
    def __init__(self, message: str, permanent: bool) -> None:
        super().__init__(message)
        self.permanent = (
            permanent  # True: retrying cannot help (invalid number, rejected sender, bad credentials)
        )


@dataclass(frozen=True)
class SmsAccepted:
    provider: str
    message_id: str


class SmsSender(Protocol):
    name: str

    def send(self, to: str, text: str, reference: str) -> SmsAccepted: ...


class MessenteSender:
    """Messente Omnimessage API: POST /v1/omnimessage with basic auth; DLR to our webhook."""

    name = "messente"
    URL = "https://api.messente.com/v1/omnimessage"

    def __init__(
        self,
        username: str,
        password: str,
        sender: str,
        dlr_url: str | None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.auth = (username, password)
        self.sender = sender
        self.dlr_url = dlr_url
        self.transport = transport

    def send(self, to: str, text: str, reference: str) -> SmsAccepted:
        body: dict[str, Any] = {
            "to": to,
            "messages": [{"channel": "sms", "sender": self.sender, "text": text}],
        }
        if self.dlr_url:
            body["dlr_url"] = self.dlr_url
        try:
            with httpx.Client(
                timeout=get_settings().provider_timeout_seconds, transport=self.transport
            ) as client:
                response = client.post(
                    self.URL, json=body, auth=self.auth, headers={"X-Request-Id": reference}
                )
        except httpx.HTTPError as exc:
            raise SmsError(f"provider unreachable: {type(exc).__name__}", permanent=False) from exc
        if response.status_code in (400, 401, 403, 422):
            raise SmsError(f"provider rejected the message ({response.status_code})", permanent=True)
        if response.status_code >= 300:
            raise SmsError(f"provider error {response.status_code}", permanent=False)
        try:
            message_id = response.json()["messages"][0]["message_id"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            # No message ID = no proof the provider took it: retried, never reported as sent.
            raise SmsError("provider answer without a message ID", permanent=False) from exc
        return SmsAccepted(self.name, str(message_id))


@lru_cache
def get_sms_sender() -> SmsSender | None:
    settings = get_settings()
    if settings.sms_provider != "messente":
        return None
    assert settings.messente_api_username and settings.messente_api_password and settings.sms_sender
    dlr = None
    if settings.app_origin and settings.sms_webhook_token:
        token = settings.sms_webhook_token.get_secret_value()
        dlr = f"{settings.app_origin}/api/v1/webhooks/sms/messente?token={token}"
    return MessenteSender(
        settings.messente_api_username,
        settings.messente_api_password.get_secret_value(),
        settings.sms_sender,
        dlr,
    )


# Final DLR statuses (Messente/SMPP): delivered vs definitely not delivered; anything else is still in
# transit.
DELIVERED = {"DELIVRD"}
UNDELIVERED = {"UNDELIV", "REJECTD", "EXPIRED", "FAILED", "DELETED"}
