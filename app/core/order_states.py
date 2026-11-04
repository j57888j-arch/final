from __future__ import annotations

from enum import StrEnum


class OrderStatus(StrEnum):
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    PROCESSING = "processing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    REFUND_PENDING = "refund_pending"


TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.AWAITING_PAYMENT: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.PROCESSING, OrderStatus.REFUNDED, OrderStatus.CANCELLED, OrderStatus.REFUND_PENDING},
    OrderStatus.PROCESSING: {OrderStatus.COMPLETED, OrderStatus.REFUNDED, OrderStatus.CANCELLED, OrderStatus.REFUND_PENDING},
    OrderStatus.COMPLETED: {OrderStatus.REFUNDED},
    OrderStatus.REJECTED: {OrderStatus.REFUNDED},
    OrderStatus.CANCELLED: {OrderStatus.REFUNDED},
    OrderStatus.REFUND_PENDING: {OrderStatus.REFUNDED, OrderStatus.PAID, OrderStatus.PROCESSING},
    OrderStatus.REFUNDED: set(),
}


class InvalidOrderTransition(ValueError):
    pass


def ensure_transition(old_status: str, new_status: str) -> None:
    allowed = TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        raise InvalidOrderTransition(f"Order status transition is not allowed: {old_status} -> {new_status}")
