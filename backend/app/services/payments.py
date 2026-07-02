"""Stripe 支付（P9）：Checkout 充值 + webhook 入账。

未配 STRIPE_SECRET_KEY 时不可用（返回未配置错误），系统仍支持 owner 手动充值。
"""
from app.config import settings


def stripe_enabled() -> bool:
    return bool(settings.stripe_secret_key)


def _client():
    import stripe
    stripe.api_key = settings.stripe_secret_key
    return stripe


def create_checkout_session(org_id: int, amount_usd: float, success_url: str, cancel_url: str) -> str:
    """创建 Stripe Checkout Session，返回支付跳转 URL。金额以美分计。"""
    stripe = _client()
    session = stripe.checkout.Session.create(
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        line_items=[{
            "quantity": 1,
            "price_data": {
                "currency": settings.stripe_currency,
                "unit_amount": int(round(amount_usd * 100)),
                "product_data": {"name": "TokenRouter 额度充值"},
            },
        }],
        metadata={"org_id": str(org_id), "kind": "credit_topup"},
    )
    return session.url


def parse_webhook_event(payload: bytes, sig_header: str) -> dict | None:
    """校验签名并解析 webhook；返回已完成充值事件的 {org_id, amount_usd, ref}，否则 None。"""
    stripe = _client()
    event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
    if event.get("type") != "checkout.session.completed":
        return None
    obj = event["data"]["object"]
    meta = obj.get("metadata") or {}
    if meta.get("kind") != "credit_topup":
        return None
    org_id = meta.get("org_id")
    amount_total = obj.get("amount_total")  # 美分，以实付为准
    if org_id is None or amount_total is None:
        return None
    return {
        "org_id": int(org_id),
        "amount_usd": round(amount_total / 100, 2),
        "ref": obj.get("payment_intent") or obj.get("id"),
    }
