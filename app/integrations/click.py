from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings


class ClickIntegrationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ClickConfiguration:
    merchant_id: str
    service_id: str
    secret_key: str


class ClickAdapter:
    """Fail-closed adapter shell.

    CLICK merchant Prepare/Complete callback signing must be implemented against the
    merchant's current contract. This project deliberately does not guess a signature
    formula or mark a payment as paid from an unverified request.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return False

    def configuration(self) -> ClickConfiguration:
        if not self.settings.click_enabled:
            raise ClickIntegrationUnavailable("CLICK is disabled. Set up a verified merchant adapter first.")
        raise ClickIntegrationUnavailable(
            "CLICK credentials are present, but merchant callback verification is not enabled in this build."
        )

    async def prepare(self, payload: dict) -> dict:
        self.configuration()
        raise AssertionError("Unreachable")

    async def complete(self, payload: dict) -> dict:
        self.configuration()
        raise AssertionError("Unreachable")
