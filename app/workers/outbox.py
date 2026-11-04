from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import or_, select

from app.config import Settings
from app.database.models import BroadcastCampaign, BroadcastRecipient, OutboxEvent
from app.database.session import SessionFactory

logger = logging.getLogger(__name__)


async def _claim_batch(settings: Settings) -> list[tuple[int, str, dict]]:
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=5)
    async with SessionFactory() as session:
        async with session.begin():
            rows = (await session.scalars(
                select(OutboxEvent)
                .where(
                    or_(
                        (OutboxEvent.status == "pending") & (OutboxEvent.next_attempt_at <= now),
                        (OutboxEvent.status == "processing") & (OutboxEvent.locked_at < stale_before),
                    )
                )
                .order_by(OutboxEvent.id)
                .with_for_update(skip_locked=True)
                .limit(settings.outbox_batch_size)
            )).all()
            result = []
            for row in rows:
                row.status = "processing"
                row.locked_at = now
                result.append((row.id, row.event_type, dict(row.payload)))
            return result


async def _finish_event(event_id: int, *, error: str | None = None) -> None:
    async with SessionFactory() as session:
        async with session.begin():
            event = await session.get(OutboxEvent, event_id, with_for_update=True)
            if not event:
                return
            event.locked_at = None
            if error is None:
                event.status = "sent"
                if event.event_type == "broadcast_message":
                    recipient_id = event.payload.get("recipient_id")
                    campaign_id = event.payload.get("campaign_id")
                    recipient = await session.get(BroadcastRecipient, recipient_id) if recipient_id else None
                    if recipient and recipient.status == "pending":
                        recipient.status = "sent"
                        if campaign_id:
                            campaign = await session.get(BroadcastCampaign, campaign_id, with_for_update=True)
                            if campaign:
                                campaign.sent_count += 1
                                if campaign.sent_count + campaign.failed_count >= campaign.total_count:
                                    campaign.status = "completed"
            else:
                event.attempts += 1
                event.last_error = error[:500]
                if event.event_type == "broadcast_message":
                    recipient_id = event.payload.get("recipient_id")
                    campaign_id = event.payload.get("campaign_id")
                    recipient = await session.get(BroadcastRecipient, recipient_id) if recipient_id else None
                    if event.attempts >= 8 and recipient and recipient.status == "pending":
                        recipient.status = "failed"
                        recipient.error = error[:300]
                        if campaign_id:
                            campaign = await session.get(BroadcastCampaign, campaign_id, with_for_update=True)
                            if campaign:
                                campaign.failed_count += 1
                                if campaign.sent_count + campaign.failed_count >= campaign.total_count:
                                    campaign.status = "completed"
                if event.attempts >= 8:
                    event.status = "dead"
                else:
                    event.status = "pending"
                    event.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=min(3600, 2 ** event.attempts * 5))


async def process_outbox_once(bot: Bot, settings: Settings) -> int:
    batch = await _claim_batch(settings)
    for event_id, event_type, payload in batch:
        try:
            if event_type not in {"send_message", "send_encrypted_message", "broadcast_message"}:
                raise ValueError(f"Unknown outbox event: {event_type}")
            if event_type == "send_encrypted_message":
                from app.core.crypto import decrypt_sensitive_text
                key = settings.phone_encryption_key.get_secret_value()
                if not key:
                    raise ValueError("PHONE_ENCRYPTION_KEY is required to deliver an allocated resource")
                text = decrypt_sensitive_text(str(payload["ciphertext"]), key)
                await bot.send_message(chat_id=int(payload["chat_id"]), text=text, parse_mode=None)
            elif event_type == "broadcast_message" and payload.get("source_chat_id") and payload.get("source_message_id"):
                button_text = payload.get("button_text")
                button_url = payload.get("button_url")
                markup = None
                if button_text and button_url:
                    markup = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text=str(button_text)[:64], url=str(button_url))
                    ]])
                await bot.copy_message(
                    chat_id=int(payload["chat_id"]),
                    from_chat_id=int(payload["source_chat_id"]),
                    message_id=int(payload["source_message_id"]),
                    reply_markup=markup,
                )
            else:
                await bot.send_message(chat_id=int(payload["chat_id"]), text=str(payload["text"]), parse_mode=None)
            await _finish_event(event_id)
            if event_type == "broadcast_message":
                await asyncio.sleep(1.0 / settings.max_broadcast_per_minute * 60)
        except Exception as exc:  # Telegram errors are retried with bounded exponential backoff.
            logger.warning("Outbox event %s failed: %s", event_id, exc)
            await _finish_event(event_id, error=f"{type(exc).__name__}: {exc}")
    return len(batch)


async def run_outbox_worker(bot: Bot, settings: Settings) -> None:
    from app.services.order_service import expire_unpaid_orders

    logger.info("Outbox worker started")
    last_expiry_sweep = 0.0
    while True:
        try:
            now = asyncio.get_running_loop().time()
            if now - last_expiry_sweep >= 30:
                async with SessionFactory() as session:
                    async with session.begin():
                        await expire_unpaid_orders(session)
                last_expiry_sweep = now
            processed = await process_outbox_once(bot, settings)
            if not processed:
                await asyncio.sleep(settings.outbox_poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Outbox worker iteration failed")
            await asyncio.sleep(settings.outbox_poll_seconds)
