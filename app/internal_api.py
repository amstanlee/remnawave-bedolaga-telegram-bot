from fastapi import APIRouter, Request, HTTPException, status
from pydantic import BaseModel

from app.database.database import AsyncSessionLocal
from app.database.crud.user import get_user_by_telegram_id, get_user_by_email
from app.database.crud.subscription import get_subscription_by_user_id

from app.services.user_service import UserService

from app.services.referral_service import process_referral_topup

INTERNAL_API_TOKEN = "c4d347fb63cfec0f310bb80d27217606fb9b7734424e30976dcd5a2fcf7405cf"

router = APIRouter(prefix="/internal")


class TopUpNotification(BaseModel):
    telegram_id: int | None = None
    email: str | None = None
    amount_kopeks: int
    payment_id: str
    balance_kopeks: int


@router.post("/notify_topup")
async def notify_topup(request: Request, payload: TopUpNotification):
    token = request.headers.get("X-Internal-Token")
    if token != INTERNAL_API_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    bot = request.app.state.bot

    async with AsyncSessionLocal() as session:

        # --- Находим пользователя ---
        if payload.telegram_id:
            user = await get_user_by_telegram_id(session, payload.telegram_id)
        elif payload.email:
            user = await get_user_by_email(session, payload.email)
        else:
            raise HTTPException(400, "telegram_id or email required")

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # --- Обновляем баланс ---
        user.balance_kopeks = payload.balance_kopeks

        # --- Подписка ---
        subscription = await get_subscription_by_user_id(session, user.id)

        # --- Реферальная система ---
        try:
            await process_referral_topup(
                session,
                user.id,
                payload.amount_kopeks,
                bot,
            )
        except Exception as error:
            print("❌ Ошибка обработки реферального пополнения:", error)

        # --- Уведомление пользователю ---
        user_service = UserService()
        success = await user_service.send_topup_success_to_user(
            bot=bot,
            user=user,
            amount_kopeks=payload.amount_kopeks,
            subscription=subscription,
        )

        await session.commit()

        if success:
            return {"status": "ok", "message": "Notification sent successfully"}
        else:
            return {"status": "ok", "message": "Balance updated but notification failed"}
