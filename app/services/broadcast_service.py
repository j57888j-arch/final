from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BroadcastCampaign, BroadcastRecipient, OutboxEvent, User
from app.services.common import audit, enqueue_message


async def queue_broadcast(
    session: AsyncSession, *, message: str, created_by: int,
    source_chat_id: int | None = None, source_message_id: int | None = None,
    button_text: str | None = None, button_url: str | None = None,
) -> BroadcastCampaign:
    text = message.strip()
    if not text or len(text) > 4000:
        raise ValueError("Xabar 1–4000 belgidan iborat bo‘lishi kerak.")
    users = (await session.scalars(select(User).where(User.is_blocked.is_(False)))).all()
    if (button_text and not button_url) or (button_url and not button_text):
        raise ValueError("Inline tugma uchun matn va URL birga berilishi kerak.")
    if button_url and not button_url.startswith(("https://", "http://")):
        raise ValueError("Tugma URL http:// yoki https:// bilan boshlanishi kerak.")
    campaign = BroadcastCampaign(
        created_by=created_by, message=text, source_chat_id=source_chat_id,
        source_message_id=source_message_id, button_text=button_text, button_url=button_url,
        status="queued" if users else "completed", total_count=len(users),
    )
    session.add(campaign)
    await session.flush()
    for user in users:
        recipient = BroadcastRecipient(campaign_id=campaign.id, user_id=user.id, status="pending")
        session.add(recipient)
        await session.flush()
        session.add(OutboxEvent(
            event_type="broadcast_message",
            payload={"chat_id": user.telegram_id, "text": text,
                     "campaign_id": campaign.id, "recipient_id": recipient.id,
                     "source_chat_id": source_chat_id, "source_message_id": source_message_id,
                     "button_text": button_text, "button_url": button_url},
        ))
    await audit(session, created_by, "broadcast.queued", "broadcast", campaign.id, {"recipients": len(users)})
    return campaign
