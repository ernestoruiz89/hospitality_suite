"""Weighted-average stock valuation in the legal entity's base currency."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from hospitality_suite.ledger_rules import LedgerValidationError, amount


class StockValidationError(ValueError):
    pass


def quantity(value):
    if isinstance(value, bool):
        raise StockValidationError("La cantidad debe ser positiva")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise StockValidationError("La cantidad debe ser numérica") from exc
    if not result.is_finite() or result <= 0 or result >= Decimal("1000000000") or result != result.quantize(Decimal("0.000001")):
        raise StockValidationError("La cantidad debe ser positiva y admitir hasta seis decimales")
    return result


def receipt(balance_qty, balance_value, received_qty, received_value, precision=2):
    qty = quantity(received_qty)
    try:
        value = amount(received_value, precision)
    except LedgerValidationError as exc:
        raise StockValidationError(str(exc)) from exc
    if value <= 0:
        raise StockValidationError("La recepción requiere un costo positivo")
    previous_qty = Decimal(str(balance_qty))
    previous_value = Decimal(str(balance_value))
    if previous_qty < 0 or previous_value < 0 or (previous_qty == 0 and previous_value != 0):
        raise StockValidationError("El saldo previo de inventario no está conciliado")
    return {"quantity_delta": str(qty), "value_delta": str(value),
            "balance_quantity": str(previous_qty + qty), "balance_value": str(previous_value + value)}


def issue(balance_qty, balance_value, issued_qty, precision=2):
    qty = quantity(issued_qty)
    previous_qty = Decimal(str(balance_qty))
    previous_value = Decimal(str(balance_value))
    if previous_qty <= 0 or previous_value < 0 or qty > previous_qty:
        raise StockValidationError("No hay existencias suficientes para la salida")
    quantum = Decimal(1).scaleb(-precision)
    cost = previous_value if qty == previous_qty else (previous_value * qty / previous_qty).quantize(quantum, rounding=ROUND_HALF_UP)
    cost = min(cost, previous_value)
    return {"quantity_delta": str(-qty), "value_delta": str(-cost),
            "balance_quantity": str(previous_qty - qty), "balance_value": str(previous_value - cost)}
