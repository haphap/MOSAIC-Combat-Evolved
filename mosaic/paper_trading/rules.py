"""A-share ETF trading rules for paper trading."""

COMMISSION_RATE = 0.00025
MIN_COMMISSION = 5.0
STAMP_DUTY_RATE = 0.0
LOT_SIZE = 100


def calc_commission(amount: float) -> float:
    return max(amount * COMMISSION_RATE, MIN_COMMISSION)


def calc_stamp_duty(amount: float) -> float:
    return amount * STAMP_DUTY_RATE


def validate_quantity(quantity: int) -> None:
    if quantity <= 0 or quantity % LOT_SIZE != 0:
        raise ValueError(f"Quantity must be a positive multiple of {LOT_SIZE}, got {quantity}")


def get_t1_available(quantity: int, today_bought: int) -> int:
    return max(quantity - today_bought, 0)


def estimate_trade_cost(price: float, quantity: int, side: str) -> dict:
    amount = price * quantity
    commission = calc_commission(amount)
    stamp_duty = calc_stamp_duty(amount) if side == "sell" else 0.0
    total_cost = amount + commission + stamp_duty if side == "buy" else amount - commission - stamp_duty
    return {
        "price": price,
        "quantity": quantity,
        "amount": amount,
        "commission": commission,
        "stamp_duty": stamp_duty,
        "total_cost": total_cost,
    }
