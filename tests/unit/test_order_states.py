import pytest

from app.core.order_states import ensure_transition, InvalidOrderTransition


def test_valid_order_transitions():
    ensure_transition("awaiting_payment", "paid")
    ensure_transition("paid", "processing")
    ensure_transition("processing", "completed")
    ensure_transition("processing", "refunded")
    ensure_transition("paid", "refund_pending")
    ensure_transition("processing", "refund_pending")
    ensure_transition("refund_pending", "refunded")


def test_invalid_order_transition_is_rejected():
    with pytest.raises(InvalidOrderTransition):
        ensure_transition("awaiting_payment", "completed")
    with pytest.raises(InvalidOrderTransition):
        ensure_transition("refunded", "paid")
