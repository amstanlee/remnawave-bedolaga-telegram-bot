from fastapi import APIRouter, Request, HTTPException, status
from pydantic import BaseModel

from app.database.database import AsyncSessionLocal
from app.database.crud.user import get_user_by_telegram_id
from app.database.crud.subscription import get_subscription_by_user_id
from app.services.user_service import UserService
from app.database.models import PaymentMethod  # ✅ добавили Enum для метода оплаты


# Токен для внутреннего API (хранится непосредственно в файле)
# Для безопасности рекомендуется сгенерировать токен длиной не менее 32 символов
# Пример генерации: python -c "import secrets; print(secrets.token_urlsafe(32))"
INTERNAL_API_TOKEN = "c4d347fb63cfec0f310bb80d27217606fb9b7734424e30976dcd5a2fcf7405cf"


router = APIRouter(prefix="/internal")


class TopUpNotification(BaseModel):
    telegram_id: int
    amount_kopeks: int
    payment_id: str


@router.post("/notify_topup")
async def notify_topup(request: Request, payload: TopUpNotification):
    # Проверка токена
    token = request.headers.get("X-Internal-Token")
    if token != INTERNAL_API_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    # Получаем бота из состояния приложения
    bot = request.app.state.bot

    # Работаем в контексте сессии
    async with AsyncSessionLocal() as session:
        # Находим пользователя по telegram_id
        user = await get_user_by_telegram_id(session, payload.telegram_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Обновляем баланс пользователя
        from app.database.crud.user import add_user_balance
        new_balance = await add_user_balance(
            session,
            user,
            payload.amount_kopeks,
            description=f"Top-up from external service: {payload.payment_id}",
            payment_method=PaymentMethod.YOOKASSA,  # ✅ передаём Enum, а не строку
        )

        # Получаем текущую подписку пользователя
        subscription = await get_subscription_by_user_id(session, user.id)

        # Используем существующий сервис для отправки уведомления
        user_service = UserService()
        success = await user_service.send_topup_success_to_user(
            bot=bot,
            user=user,
            amount_kopeks=payload.amount_kopeks,
            subscription=subscription,
        )

        if success:
            return {"status": "ok", "message": "Notification sent successfully"}
        else:
            return {"status": "ok", "message": "Balance updated but notification failed"}
