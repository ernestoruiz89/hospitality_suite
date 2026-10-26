"""Small, Frappe-independent rules shared by PMS posting and journal validation."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class LedgerValidationError(ValueError):
    pass


def amount(value, precision=2):
    if isinstance(value, bool):
        raise LedgerValidationError("El importe debe ser numérico")
    try:
        number = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise LedgerValidationError("El importe debe ser numérico") from exc
    if not number.is_finite() or number < 0:
        raise LedgerValidationError("El importe debe ser finito y no negativo")
    if number >= Decimal("1000000000000000"):
        raise LedgerValidationError("El importe excede el máximo contable")
    if not isinstance(precision, int) or not 0 <= precision <= 6:
        raise LedgerValidationError("Precisión monetaria inválida")
    quantum = Decimal(1).scaleb(-precision)
    if number != number.quantize(quantum):
        raise LedgerValidationError("El importe excede la precisión de la moneda")
    return number.quantize(quantum)


def rate_for_base(original, base, precision=2):
    """A nine-decimal rate that reproduces an already booked base balance."""
    original = amount(original, precision)
    base = amount(base, precision)
    if not original or not base:
        raise LedgerValidationError("El saldo original y el saldo base deben ser positivos")
    rate = (base / original).quantize(Decimal("0.000000001"), rounding=ROUND_HALF_UP)
    if (rate <= 0 or rate >= Decimal("1000000000") or
            (original * rate).quantize(Decimal(1).scaleb(-precision),
                                       rounding=ROUND_HALF_UP) != base):
        raise LedgerValidationError("El tipo de cambio histórico no reproduce el saldo base")
    return format(rate, "f")


def normalize_lines(lines, precision=2):
    if not isinstance(lines, (list, tuple)) or len(lines) < 2:
        raise LedgerValidationError("Un asiento requiere al menos dos líneas")
    normalized = []
    debit_total = credit_total = Decimal(0)
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("account"), str) or not line["account"].strip():
            raise LedgerValidationError("Cada línea requiere una cuenta")
        debit = amount(line.get("debit"), precision)
        credit = amount(line.get("credit"), precision)
        if (debit > 0) == (credit > 0):
            raise LedgerValidationError("Cada línea debe tener exactamente un débito o un crédito")
        normalized.append({**line, "debit": str(debit), "credit": str(credit)})
        debit_total += debit
        credit_total += credit
    if debit_total != credit_total:
        raise LedgerValidationError("El asiento no está balanceado")
    return normalized, str(debit_total)


def inverse_lines(lines):
    inverse = []
    for line in lines:
        flipped = {**line, "debit": line["credit"], "credit": line["debit"]}
        if "debit_in_account_currency" in line or "credit_in_account_currency" in line:
            flipped["debit_in_account_currency"] = line.get("credit_in_account_currency", "0")
            flipped["credit_in_account_currency"] = line.get("debit_in_account_currency", "0")
        inverse.append(flipped)
    return inverse


def currency_line(line, account_currency, base_currency, precision=2):
    """Verify and freeze one journal line in account and company currency."""
    debit = amount(line["debit"], precision)
    credit = amount(line["credit"], precision)
    if line.get("account_currency") and line["account_currency"] != account_currency:
        raise LedgerValidationError("La moneda de la partida no coincide con la cuenta")
    quantum = Decimal(1).scaleb(-precision)
    foreign = account_currency != base_currency
    if foreign:
        try:
            rate = Decimal(str(line.get("exchange_rate")))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise LedgerValidationError("Indique un tipo de cambio válido") from exc
        if not rate.is_finite() or rate <= 0 or rate >= Decimal("1000000000") or rate.as_tuple().exponent < -9:
            raise LedgerValidationError("El tipo de cambio debe ser positivo y tener hasta 9 decimales")
        account_debit = amount(line.get("debit_in_account_currency"), precision)
        account_credit = amount(line.get("credit_in_account_currency"), precision)
        if (account_debit > 0) != (debit > 0) or (account_credit > 0) != (credit > 0):
            raise LedgerValidationError("El débito o crédito en moneda de cuenta debe corresponder al importe base")
        if account_debit and (account_debit * rate).quantize(quantum, rounding=ROUND_HALF_UP) != debit:
            raise LedgerValidationError("El débito base no coincide con el importe y tipo de cambio")
        if account_credit and (account_credit * rate).quantize(quantum, rounding=ROUND_HALF_UP) != credit:
            raise LedgerValidationError("El crédito base no coincide con el importe y tipo de cambio")
    else:
        rate = Decimal(1)
        if line.get("exchange_rate") not in (None, "", 0, "0", 1, "1", "1.0", "1.000000000"):
            raise LedgerValidationError("La cuenta en moneda base usa tipo de cambio 1")
        for field, base in (("debit_in_account_currency", debit), ("credit_in_account_currency", credit)):
            supplied = line.get(field)
            if supplied not in (None, "", 0, "0") and amount(supplied, precision) != base:
                raise LedgerValidationError("El importe de la cuenta en moneda base no coincide")
        account_debit, account_credit = debit, credit
    return {**line, "account_currency": account_currency, "exchange_rate": format(rate, "f"),
            "debit_in_account_currency": str(account_debit),
            "credit_in_account_currency": str(account_credit)}
