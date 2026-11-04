from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.integrations.click import ClickAdapter, ClickIntegrationUnavailable

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/click/prepare")
async def click_prepare(request: Request):
    try:
        await ClickAdapter(get_settings()).prepare(await request.json())
    except ClickIntegrationUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/click/complete")
async def click_complete(request: Request):
    try:
        await ClickAdapter(get_settings()).complete(await request.json())
    except ClickIntegrationUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
