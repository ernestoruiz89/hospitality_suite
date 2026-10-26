"""Property-scoped agency attribution and bookable experiences."""

from decimal import Decimal
import hashlib
import re

import frappe
from frappe.utils import nowdate

from hospitality_suite.accounting import post_standard, ready
from hospitality_suite.item_configuration import selling_price
from hospitality_suite.pricing import decimal, money
from hospitality_suite.security import document, require
from hospitality_suite.service import assert_version, audit, canonical, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import provider


def _count(value, label):
    try:
        number = Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        frappe.throw(frappe._("Indique {0} válido").format(label))
    if not number.is_finite() or number != int(number) or not 1 <= number <= 1000:
        frappe.throw(frappe._("Indique {0} entre 1 y 1000").format(label))
    return int(number)


def _percent(value):
    try:
        number = decimal(value or 0)
    except (ValueError, TypeError, ArithmeticError):
        frappe.throw(frappe._("La comisión debe estar entre 0 y 100 %"))
    if not number.is_finite() or number < 0 or number > 100:
        frappe.throw(frappe._("La comisión debe estar entre 0 y 100 %"))
    return number


def agent(prop, name, *, active=True, action="reserve"):
    if not name:
        return None
    doc = document("HS Travel Agent", name, action)
    if doc.property != prop.name or doc.company != prop.company or (active and not doc.active):
        frappe.throw(frappe._("Seleccione una agencia activa del establecimiento"))
    return doc


def attribution(prop, name, amount, previous=None):
    doc = agent(prop, name)
    if not doc:
        return dict(travel_agent=None, agent_commission_pct=0, agent_commission_estimate=0)
    pct = _percent(previous if previous is not None else doc.commission_pct)
    return dict(travel_agent=doc.name, agent_commission_pct=float(pct),
                agent_commission_estimate=money(decimal(amount) * pct / 100, currency=prop.currency))


def save_agent(prop, data):
    require(prop.name, "setup")
    name = str(data.get("agent_name") or "").strip()
    if not name or len(name) > 140:
        frappe.throw(frappe._("Indique el nombre de la agencia"))
    kind = data.get("agent_type") or "Travel Agent"
    if kind not in ("Travel Agent", "OTA", "Tour Operator", "Corporate Desk"):
        frappe.throw(frappe._("Seleccione un tipo de agencia válido"))
    pct = _percent(data.get("commission_pct"))
    supplier = pms_supplier = None
    if provider() == "pms":
        if data.get("supplier"):
            frappe.throw(frappe._("Seleccione un proveedor PMS para la agencia"))
        pms_supplier = data.get("pms_supplier") or None
        if pms_supplier:
            vendor = locked_doc("HS Party", pms_supplier)
            if (vendor.property != prop.name or vendor.organization != prop.organization or
                    not vendor.active or vendor.party_type not in ("Supplier", "Both")):
                frappe.throw(frappe._("Seleccione un proveedor PMS activo del establecimiento"))
    else:
        if data.get("pms_supplier"):
            frappe.throw(frappe._("Seleccione un proveedor ERPNext para la agencia"))
        supplier = data.get("supplier") or None
        if supplier:
            vendor = locked_doc("Supplier", supplier)
            if vendor.disabled or not current_all("HS Supplier", {"property": prop.name, "company": prop.company,
                                                                  "supplier": vendor.name, "active": 1}):
                frappe.throw(frappe._("Registre primero el proveedor activo en este establecimiento"))
    values = dict(agent_name=name, agent_type=kind, commission_pct=float(pct), supplier=supplier,
                  pms_supplier=pms_supplier,
                  contact_name=str(data.get("contact_name") or "")[:140],
                  contact_phone=str(data.get("contact_phone") or "")[:140],
                  contact_email=str(data.get("contact_email") or "")[:140],
                  active=int(data.get("active", 1) in (True, 1, "1")))
    if data.get("agent"):
        doc = document("HS Travel Agent", data["agent"], "setup")
        assert_version(doc, data.get("modified"))
        doc.update(values)
        doc.save()
    else:
        doc = insert("HS Travel Agent", prop, **values)
    audit(prop, "Save travel agent", doc)
    return dict(agent=doc.name, modified=str(doc.modified))


def save_experience(prop, data):
    require(prop.name, "setup")
    name = str(data.get("experience_name") or "").strip()
    if not name or len(name) > 140:
        frappe.throw(frappe._("Indique el nombre de la experiencia"))
    category = data.get("experience_category") or "Other"
    if category not in ("Spa", "Tour", "Dining", "Activity", "Transport", "Other"):
        frappe.throw(frappe._("Seleccione una categoría válida"))
    item = pms_product = None
    if provider() == "pms":
        if data.get("item"):
            frappe.throw(frappe._("Seleccione un producto PMS para la experiencia"))
        from hospitality_suite.item_configuration import _pms_service
        from hospitality_suite.standalone_tax import tax_for_amount
        pms_product = locked_doc("HS Product", data.get("pms_product"))
        _pms_service(prop, pms_product.name, frappe._("Experiencia"))
        if not pms_product.tax_profile or decimal(pms_product.sales_rate or 0) <= 0:
            frappe.throw(frappe._("La experiencia requiere precio positivo y perfil tributario"))
        tax_for_amount(prop, pms_product.tax_profile,
                       money(pms_product.sales_rate, currency=prop.currency))
    else:
        if data.get("pms_product"):
            frappe.throw(frappe._("Seleccione un artículo ERPNext para la experiencia"))
        item = locked_doc("Item", data.get("item"))
        if item.disabled or not item.is_sales_item or item.is_stock_item or item.is_fixed_asset:
            frappe.throw(frappe._("La experiencia requiere un artículo de venta sin inventario"))
        selling_price(prop, item.name, prop.currency)
    image_url=str(data.get("image_url") or "")
    if image_url and (not re.fullmatch(r"/files/[A-Za-z0-9][A-Za-z0-9_.-]{0,180}\.(?:png|jpg|jpeg|webp|gif)",image_url,re.I)
                      or not frappe.db.exists("File",{"file_url":image_url,"is_private":0})):
        frappe.throw(frappe._("Seleccione una imagen pública existente en /files/"))
    values = dict(experience_name=name, experience_category=category,
                  item=item.name if item else None,
                  pms_product=pms_product.name if pms_product else None,
                  duration=str(data.get("duration") or "")[:140],
                  description=str(data.get("description") or "")[:500],
                  image_url=image_url,
                  show_on_booking_page=int(data.get("show_on_booking_page") in (True, 1, "1")),
                  active=int(data.get("active", 1) in (True, 1, "1")))
    if data.get("experience"):
        doc = document("HS Experience", data["experience"], "setup")
        assert_version(doc, data.get("modified"))
        doc.update(values)
        doc.save()
    else:
        doc = insert("HS Experience", prop, **values)
    audit(prop, "Save experience", doc)
    return dict(experience=doc.name, modified=str(doc.modified))


def quote_experiences(prop, rows, customer=None, *, public=False):
    if rows in (None, ""):
        return []
    if not isinstance(rows, list) or len(rows) > 20 or any(not isinstance(row, dict) for row in rows):
        frappe.throw(frappe._("Revise las experiencias seleccionadas"))
    quoted, seen = [], set()
    for row in rows:
        name = row.get("experience")
        if name in seen:
            frappe.throw(frappe._("Seleccione cada experiencia una sola vez"))
        seen.add(name)
        exp = locked_doc("HS Experience", name)
        if (exp.property != prop.name or exp.company != prop.company or not exp.active
                or (public and not exp.show_on_booking_page)):
            frappe.throw(frappe._("La experiencia no está disponible en este establecimiento"))
        quantity = _count(row.get("quantity"), frappe._("una cantidad"))
        if provider() == "pms":
            from hospitality_suite.item_configuration import _pms_service
            from hospitality_suite.standalone_tax import tax_for_amount
            product = locked_doc("HS Product", exp.pms_product)
            _pms_service(prop, product.name, frappe._("Experiencia"))
            if not product.tax_profile:
                frappe.throw(frappe._("Configure el impuesto del producto de la experiencia"))
            rate = money(product.sales_rate, currency=prop.currency)
            if rate <= 0:
                frappe.throw(frappe._("Configure un precio positivo para la experiencia"))
            price = money(rate * quantity, currency=prop.currency)
            tax = tax_for_amount(prop, product.tax_profile, price)
            quoted.append(dict(experience=exp.name, name=exp.experience_name,
                               item=None, pms_product=product.name, item_price=None,
                               quantity=quantity, rate=str(rate), amount=str(price),
                               tax_amount=tax["tax"], total_amount=tax["total"],
                               experience_modified=str(exp.modified),
                               product_modified=str(product.modified),
                               tax_profile_modified=tax["profile_modified"]))
        else:
            item = locked_doc("Item", exp.item)
            if item.disabled or not item.is_sales_item or item.is_stock_item:
                frappe.throw(frappe._("El artículo de la experiencia no está habilitado"))
            price = selling_price(prop, item.name, prop.currency, customer)
            rate = money(price.price_list_rate, currency=prop.currency)
            quoted.append(dict(experience=exp.name, name=exp.experience_name, item=item.name,
                               item_price=price.name, quantity=quantity, rate=str(rate),
                               amount=str(money(rate * quantity, currency=prop.currency))))
    return quoted


def book_experiences(prop, booking, quoted):
    created=[]
    for row in quoted:
        order = insert("HS Experience Order", prop, experience=row["experience"], booking=booking.name,
                       customer=booking.customer, item=row["item"],
                       pms_product=row.get("pms_product"), quantity=row["quantity"],
                       participants=row["quantity"], unit_rate=row["rate"], amount=row["amount"],
                       currency=prop.currency, status="Reserved")
        audit(prop, "Book experience", order, details=dict(item_price=row["item_price"],
            pms_product=row.get("pms_product"), tax_amount=row.get("tax_amount")))
        created.append(order.name)
    return created


def order_quote(prop, data):
    booking = document("HS Booking", data["booking"], "reserve")
    if booking.status not in ("Confirmed", "Checked In"):
        frappe.throw(frappe._("Seleccione una reserva confirmada o una estancia activa"))
    quoted = quote_experiences(prop, [{"experience": data.get("experience"),
                                       "quantity": data.get("quantity")}], booking.customer)
    result=dict(booking=booking.name,modified=str(booking.modified),line=quoted[0],currency=prop.currency)
    result["acceptance"]=hashlib.sha256(canonical(result).encode()).hexdigest()
    return result


def order_experience(prop, data):
    """Reception may also book an accepted experience after the room reservation."""
    q=order_quote(prop,data)
    if data.get("acceptance")!=q["acceptance"]:
        frappe.throw(frappe._("Revise y acepte el precio vigente de la experiencia"))
    booking=document("HS Booking",q["booking"],"reserve")
    return dict(order=book_experiences(prop, booking, [q["line"]])[0])


def direct_order_quote(prop, data):
    from hospitality_suite.standalone_accounting import account, require_pms
    from hospitality_suite.standalone_tax import tax_for_amount
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) != {"customer", "experience", "quantity"}:
        frappe.throw(frappe._("Revise la venta directa de experiencia"))
    customer = locked_doc("HS Party", data["customer"])
    if (customer.property != prop.name or customer.organization != prop.organization or
            not customer.active or customer.party_type not in ("Customer", "Both")):
        frappe.throw(frappe._("Seleccione un cliente PMS activo del establecimiento"))
    line = quote_experiences(prop, [{"experience": data["experience"],
                                    "quantity": data["quantity"]}])[0]
    product = locked_doc("HS Product", line["pms_product"])
    tax = tax_for_amount(prop, product.tax_profile, line["amount"])
    income = account(prop, product.income_account)
    line = {**line, "net_amount": tax["net"],
            "income_account": income.name,
            "tax_account": tax["liability_account"],
            "accepted_tax_profile": tax["profile"]}
    basis = {"property": prop.name, "customer": customer.name,
             "customer_modified": str(customer.modified), "line": line}
    return {**basis, "customer_name": customer.party_name, "currency": prop.currency,
            "acceptance": hashlib.sha256(canonical(basis).encode()).hexdigest()}


def direct_order(prop, data):
    if not isinstance(data, dict) or set(data) != {"customer", "experience", "quantity", "acceptance"}:
        frappe.throw(frappe._("Revise la venta directa de experiencia"))
    reviewed = direct_order_quote(prop, {key: data[key] for key in
        ("customer", "experience", "quantity")})
    if data["acceptance"] != reviewed["acceptance"]:
        frappe.throw(frappe._("El cliente, precio o impuesto cambió; revise la experiencia"))
    line = reviewed["line"]
    order = insert("HS Experience Order", prop, experience=line["experience"],
        customer=reviewed["customer"], pms_product=line["pms_product"],
        quantity=line["quantity"], participants=line["quantity"],
        unit_rate=line["rate"], amount=line["amount"],
        accepted_net=line["net_amount"], accepted_tax=line["tax_amount"],
        accepted_total=line["total_amount"],
        accepted_tax_profile=line["accepted_tax_profile"],
        income_account=line["income_account"],
        tax_account=line["tax_account"],
        currency=prop.currency, status="Reserved")
    audit(prop, "pms_direct_experience_reserved", order,
          details={"price": line["amount"], "tax": line["tax_amount"],
                   "total": line["total_amount"]})
    return {"order": order.name, "modified": str(order.modified),
            "status": order.status, "currency": prop.currency,
            "total_amount": line["total_amount"]}


def legacy_direct_quote(prop, data):
    """Review an unsplit historic direct sale without guessing its original tax."""
    from hospitality_suite.standalone_accounting import require_pms
    from hospitality_suite.standalone_tax import tax_for_amount
    require_pms(prop)
    require(prop.name, "approve")
    if (not isinstance(data, dict) or set(data) !=
            {"order", "modified", "tax_profile", "income_account", "evidence"}):
        frappe.throw(frappe._("Revise la orden histórica y su respaldo"))
    evidence = data["evidence"]
    if not isinstance(evidence, str) or not 10 <= len(evidence.strip()) <= 500:
        frappe.throw(frappe._("Indique la referencia del respaldo histórico (10 a 500 caracteres)"))
    order = document("HS Experience Order", data["order"], "approve")
    assert_version(order, data["modified"])
    if (order.property != prop.name or order.company != prop.company or
            order.booking or order.stay or order.folio or order.charge or
            order.pms_receivable or order.sales_invoice or order.item or
            order.status not in ("Reserved", "Confirmed") or
            order.currency != prop.currency or
            any(order.get(field) for field in ("accepted_net", "accepted_tax",
                "accepted_total", "accepted_tax_profile", "income_account", "tax_account"))):
        frappe.throw(frappe._("Solo se puede completar una orden directa pendiente sin desglose previo"))
    product = locked_doc("HS Product", order.pms_product)
    party = locked_doc("HS Party", order.customer)
    if (product.property != prop.name or product.organization != prop.organization or
            product.product_type != "Service" or not product.active or
            party.property != prop.name or party.organization != prop.organization or
            party.party_type not in ("Customer", "Both") or not party.active or
            frappe.db.get_value("HS Experience", order.experience, "property") != prop.name):
        frappe.throw(frappe._("La orden histórica perdió su producto o cliente válido"))
    quantity = _count(order.quantity, frappe._("cantidad"))
    price = money(order.amount, currency=prop.currency)
    if (price <= 0 or money(Decimal(str(order.unit_rate)) * quantity,
                          currency=prop.currency) != price):
        frappe.throw(frappe._("El importe histórico no coincide con la cantidad y tarifa"))
    income = locked_doc("HS Account", data["income_account"])
    if (income.property != prop.name or income.organization != prop.organization or
            not income.active or income.is_group or income.root_type != "Income" or
            income.account_currency != prop.currency):
        frappe.throw(frappe._("Seleccione una cuenta de ingreso en moneda base"))
    tax = tax_for_amount(prop, data["tax_profile"], price)
    if not tax["profile"]:
        frappe.throw(frappe._("Seleccione el perfil tributario histórico"))
    basis = {"property": prop.name, "order": order.name,
        "order_modified": str(order.modified), "product": product.name,
        "product_modified": str(product.modified), "party": party.name,
        "party_modified": str(party.modified), "income_account": income.name,
        "income_modified": str(income.modified), "tax": tax,
        "evidence": evidence.strip()}
    return {"order": order.name, "modified": str(order.modified),
        "currency": prop.currency, "price": tax["price"],
        "net_amount": tax["net"], "tax_amount": tax["tax"],
        "total_amount": tax["total"], "tax_profile": tax["profile"],
        "tax_account": tax["liability_account"],
        "income_account": income.name, "evidence": evidence.strip(),
        "acceptance": hashlib.sha256(canonical(basis).encode()).hexdigest()}


def freeze_legacy_direct(prop, data):
    if not isinstance(data, dict) or set(data) != {
            "order", "modified", "tax_profile", "income_account", "evidence", "acceptance"}:
        frappe.throw(frappe._("Revise la confirmación de la orden histórica"))
    reviewed = legacy_direct_quote(prop, {key: data[key] for key in
        ("order", "modified", "tax_profile", "income_account", "evidence")})
    if data["acceptance"] != reviewed["acceptance"]:
        frappe.throw(frappe._("La orden, perfil o cuenta cambió; revise nuevamente"))
    order = locked_doc("HS Experience Order", reviewed["order"])
    order.accepted_net = reviewed["net_amount"]
    order.accepted_tax = reviewed["tax_amount"]
    order.accepted_total = reviewed["total_amount"]
    order.accepted_tax_profile = reviewed["tax_profile"]
    order.income_account = reviewed["income_account"]
    order.tax_account = reviewed["tax_account"]
    previous = getattr(frappe.local, "hs_legacy_direct_freeze", None)
    frappe.local.hs_legacy_direct_freeze = order.name
    try:
        order.save()
    finally:
        frappe.local.hs_legacy_direct_freeze = previous
    audit(prop, "pms_legacy_direct_experience_reviewed", order,
        reason=reviewed["evidence"], details={
            "price": reviewed["price"], "net": reviewed["net_amount"],
            "tax": reviewed["tax_amount"], "total": reviewed["total_amount"],
            "tax_profile": reviewed["tax_profile"],
            "income_account": reviewed["income_account"],
            "tax_account": reviewed["tax_account"]})
    return {"order": order.name, "modified": str(order.modified),
        "net_amount": reviewed["net_amount"], "tax_amount": reviewed["tax_amount"],
        "total_amount": reviewed["total_amount"]}


def direct_delivery_quote(prop, data):
    if provider() == "erpnext":
        require(prop.name, "finance")
        if (not isinstance(data, dict) or set(data) -
                {"order", "receivable_account"} or not data.get("order")):
            frappe.throw(frappe._("Revise la entrega de la experiencia directa"))
        if (data.get("receivable_account") and
                data["receivable_account"] != prop.receivable_account):
            frappe.throw(frappe._("La cuenta por cobrar cambió tras el corte"))
        order = document("HS Experience Order", data["order"], "finance")
        if (order.property != prop.name or order.booking or
                order.status != "Confirmed" or order.charge or
                order.pms_receivable or order.sales_invoice):
            frappe.throw(frappe._("Seleccione una experiencia directa pendiente"))
        invoice = _direct_erp_invoice(prop, order)
        basis = {"property": prop.name, "property_modified": str(prop.modified),
            "order": order.name, "order_modified": str(order.modified),
            "customer": order.customer, "item": order.item,
            "income_account": order.income_account,
            "tax_account": order.tax_account,
            "receivable_account": invoice.debit_to,
            "posting_date": str(invoice.posting_date),
            "due_date": str(invoice.due_date),
            "net": str(money(invoice.net_total, currency=prop.currency)),
            "tax": str(money(invoice.total_taxes_and_charges,
                              currency=prop.currency)),
            "total": str(money(invoice.grand_total, currency=prop.currency))}
        return {"order": order.name, "modified": str(order.modified),
            "customer": order.customer, "product": order.item,
            "receivable_account": invoice.debit_to,
            "income_account": order.income_account,
            "currency": prop.currency, "price": str(order.amount),
            "net_amount": basis["net"], "tax_amount": basis["tax"],
            "total_amount": basis["total"],
            "acceptance": hashlib.sha256(canonical(basis).encode()).hexdigest()}
    from hospitality_suite.standalone_accounting import account, require_pms
    from hospitality_suite.standalone_tax import tax_for_amount
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) != {"order", "receivable_account"}:
        frappe.throw(frappe._("Revise la entrega y contabilización de la experiencia"))
    order = document("HS Experience Order", data["order"], "finance")
    if (order.property != prop.name or order.booking or order.status != "Confirmed" or
            order.pms_receivable or order.charge):
        frappe.throw(frappe._("Seleccione una experiencia directa confirmada y pendiente"))
    if not order.accepted_total:
        frappe.throw(frappe._("Revise el desglose histórico de la experiencia antes de entregarla"))
    customer = locked_doc("HS Party", order.customer)
    if (customer.property != prop.name or customer.organization != prop.organization or
            not customer.active or customer.party_type not in ("Customer", "Both")):
        frappe.throw(frappe._("El cliente de la orden ya no está disponible"))
    product = locked_doc("HS Product", order.pms_product)
    from hospitality_suite.item_configuration import _pms_service
    _pms_service(prop, product.name, frappe._("Experiencia"))
    if not product.tax_profile:
        frappe.throw(frappe._("Configure el impuesto del producto de la experiencia"))
    income = account(prop, order.income_account or product.income_account)
    receivable = account(prop, data["receivable_account"])
    if (receivable.root_type != "Asset" or receivable.account_type != "Receivable" or
            receivable.account_currency != prop.currency or receivable.is_cash or
            receivable.is_bank):
        frappe.throw(frappe._("Seleccione una cuenta por cobrar PMS en moneda base"))
    tax = tax_for_amount(prop,
        order.accepted_tax_profile or product.tax_profile, order.amount)
    if (order.accepted_total and
            (Decimal(tax["net"]) != Decimal(str(order.accepted_net or 0)) or
             Decimal(tax["tax"]) != Decimal(str(order.accepted_tax or 0)) or
             Decimal(tax["total"]) != Decimal(str(order.accepted_total)) or
             income.name != order.income_account or
             tax["liability_account"] != order.tax_account)):
        frappe.throw(frappe._("La experiencia no conserva su precio e impuesto aceptados"))
    basis = {"property": prop.name, "order": order.name,
             "order_modified": str(order.modified), "customer": customer.name,
             "customer_modified": str(customer.modified), "product": product.name,
             "product_modified": str(product.modified), "receivable_account": receivable.name,
             "income_account": income.name, "tax": tax}
    return {"order": order.name, "modified": str(order.modified),
            "customer": customer.name, "product": product.name,
            "receivable_account": receivable.name, "income_account": income.name,
            "currency": prop.currency, "price": tax["price"],
            "net_amount": tax["net"], "tax_amount": tax["tax"],
            "total_amount": tax["total"], "tax_profile": tax["profile"],
            "acceptance": hashlib.sha256(canonical(basis).encode()).hexdigest()}


def _direct_erp_invoice(prop, order):
    """Bill the frozen PMS direct sale after authority moves to ERPNext."""
    ready(prop)
    item = locked_doc("Item", order.item)
    customer = locked_doc("Customer", order.customer)
    net = money(order.accepted_net, currency=prop.currency)
    tax = money(order.accepted_tax, currency=prop.currency)
    total = money(order.accepted_total, currency=prop.currency)
    qty = _count(order.quantity, frappe._("una cantidad"))
    if (item.disabled or not item.is_sales_item or item.is_stock_item or
            not customer or net <= 0 or tax < 0 or net + tax != total):
        frappe.throw(frappe._("La experiencia migrada perdió su precio aceptado"))
    for account_name, root in ((order.income_account, "Income"),
                               (order.tax_account, "Liability") if tax else (None, None)):
        if not account_name:
            if root:
                frappe.throw(frappe._("La experiencia migrada perdió su cuenta tributaria"))
            continue
        account = frappe.db.get_value("Account", account_name,
            ["company", "root_type", "is_group", "account_currency"], as_dict=True)
        if (not account or account.company != prop.company or
                account.root_type != root or account.is_group or
                account.account_currency != prop.currency):
            frappe.throw(frappe._("La cuenta migrada de la experiencia ya no es válida"))
    from hospitality_suite.credit import invoice_due_date
    invoice = frappe.new_doc("Sales Invoice")
    invoice.flags.dont_auto_add_taxes = True
    invoice.update(dict(company=prop.company, customer=order.customer,
        posting_date=nowdate(), due_date=invoice_due_date(prop, order.customer),
        currency=prop.currency, conversion_rate=1,
        debit_to=prop.receivable_account, cost_center=prop.cost_center,
        selling_price_list=prop.price_list, price_list_currency=prop.currency,
        plc_conversion_rate=1,
        hs_property=prop.name, update_stock=0,
        remarks="Experiencia directa PMS " + order.name))
    invoice.append("items", dict(item_code=item.name, qty=qty, warehouse=prop.warehouse,
        rate=float(net / qty), income_account=order.income_account,
        cost_center=prop.cost_center, description=frappe.db.get_value(
            "HS Experience", order.experience, "experience_name")))
    invoice.set_missing_values()
    invoice.set("taxes", [])
    if tax:
        invoice.append("taxes", dict(charge_type="Actual",
            account_head=order.tax_account,
            description="Impuesto aceptado en PMS " + order.name,
            tax_amount=float(tax), cost_center=prop.cost_center))
    invoice.calculate_taxes_and_totals()
    if (money(invoice.net_total, currency=prop.currency) != net or
            money(invoice.total_taxes_and_charges, currency=prop.currency) != tax or
            money(invoice.grand_total, currency=prop.currency) != total):
        frappe.throw(frappe._("ERPNext no conserva el precio e impuesto aceptados"))
    return invoice


def update_direct_order(prop, data):
    return update_order(prop, data, direct=True)


def update_order(prop, data, *, direct=False):
    doc = document("HS Experience Order", data["order"], "finance" if direct else "service")
    if (bool(doc.booking) == direct or doc.property != prop.name):
        frappe.throw(frappe._("La orden no corresponde a este flujo de experiencias"))
    assert_version(doc, data.get("modified"))
    target = data.get("status")
    if target not in {"Reserved": ("Confirmed", "Cancelled"),
                      "Confirmed": ("Delivered", "Cancelled")}.get(doc.status, ()):
        frappe.throw(frappe._("Transición de experiencia inválida"))
    if target == "Cancelled":
        note = str(data.get("reason") or "").strip()
        if not note:
            frappe.throw(frappe._("Indique el motivo de cancelación"))
        doc.cancel_reason = note[:500]
    if target == "Confirmed":
        from hospitality_suite.time import to_site
        date = data.get("scheduled_at")
        if not date:
            frappe.throw(frappe._("Indique la fecha y hora de la experiencia"))
        doc.scheduled_at = to_site(date, prop)
        doc.participants = _count(data.get("participants") or doc.quantity, frappe._("participantes"))
        doc.notes = str(data.get("notes") or "")[:500]
    if target == "Delivered":
        if direct:
            reviewed = direct_delivery_quote(prop, {"order": doc.name,
                **({"receivable_account": data["receivable_account"]}
                   if data.get("receivable_account") else {})})
            if data.get("acceptance") != reviewed["acceptance"]:
                frappe.throw(frappe._("El cliente, impuesto o cuentas cambiaron; revise la entrega"))
            if provider() == "pms":
                from hospitality_suite.standalone_receivables import _create
                from hospitality_suite.standalone_accounting import account
                from uuid import uuid4
                result = _create(prop, party=reviewed["customer"],
                    reference=f"EXP-{doc.name}-{uuid4().hex[:8]}",
                    description=frappe.db.get_value("HS Experience", doc.experience, "experience_name"),
                    value=Decimal(str(doc.amount)),
                    receivable=account(prop, reviewed["receivable_account"]),
                    income=account(prop, reviewed["income_account"]),
                    experience_order=doc.name,
                    tax_profile=reviewed["tax_profile"])
                if (doc.accepted_total and
                        (Decimal(result["net_amount"]) !=
                            Decimal(str(doc.accepted_net or 0)) or
                         Decimal(result["tax_amount"]) !=
                            Decimal(str(doc.accepted_tax or 0)) or
                         Decimal(result["amount"]) !=
                            Decimal(str(doc.accepted_total)))):
                    frappe.throw(frappe._("El cargo no conserva el precio aceptado"))
                doc.pms_receivable = result["receivable"]
            else:
                invoice = post_standard(_direct_erp_invoice(prop, doc), prop)
                doc.sales_invoice = invoice.name
        else:
            stay_name = data.get("stay")
            if not stay_name:
                active = current_all("HS Stay", {"property": prop.name, "booking": doc.booking,
                                                 "status": "Active"}, pluck="name")
                if len(active) != 1:
                    frappe.throw(frappe._("Seleccione la estancia que recibe la experiencia"))
                stay_name = active[0]
            stay = document("HS Stay", stay_name, "service")
            if stay.booking != doc.booking or stay.status != "Active":
                frappe.throw(frappe._("La estancia no corresponde a la reserva o ya terminó"))
            folio_name = data.get("folio")
            if not folio_name:
                folios = current_all("HS Folio", {"property": prop.name, "stay": stay.name,
                                                  "status": "Open"}, pluck="name")
                if len(folios) != 1:
                    frappe.throw(frappe._("Seleccione la cuenta que recibe el cargo"))
                folio_name = folios[0]
            folio = document("HS Folio", folio_name, "service")
            if folio.status != "Open" or not (folio.stay == stay.name or folio.booking == doc.booking):
                frappe.throw(frappe._("La cuenta no corresponde a la estancia o está cerrada"))
            if folio.currency != doc.currency or folio.customer != doc.customer:
                frappe.throw(frappe._("Revise pagador y moneda antes de cargar la experiencia"))
            description = frappe.db.get_value("HS Experience", doc.experience, "experience_name")
            if provider() == "pms":
                from hospitality_suite.item_configuration import _pms_service
                from hospitality_suite.standalone_tax import tax_for_amount
                product = locked_doc("HS Product", doc.pms_product)
                _pms_service(prop, product.name, frappe._("Experiencia"))
                if not product.tax_profile:
                    frappe.throw(frappe._("Configure el impuesto del producto de la experiencia"))
                tax_for_amount(prop, product.tax_profile, doc.amount)
                entry = insert("HS Charge", prop, stay=stay.name, folio=folio.name,
                               item=product.name, description=description,
                               quantity=doc.quantity, rate=doc.unit_rate, amount=doc.amount,
                               currency=prop.currency, business_date=prop.business_date,
                               kind="Service", status="Pending",
                               quote_snapshot=canonical(dict(experience_order=doc.name,
                                   experience=doc.experience, accepted_rate=str(doc.unit_rate),
                                   accepted_amount=str(doc.amount))))
            else:
                from hospitality_suite.operations import charge
                entry = charge(prop, stay, folio, doc.item, doc.amount, "Service", description,
                               snapshot=dict(experience=doc.experience, unit_rate=str(doc.unit_rate)),
                               quantity=doc.quantity)
            doc.stay, doc.folio, doc.charge = stay.name, folio.name, entry.name
    doc.status = target
    doc.save()
    audit(prop, "Experience " + target, doc, data.get("reason"))
    return dict(order=doc.name, status=doc.status, charge=doc.charge,
                pms_receivable=doc.pms_receivable,
                sales_invoice=doc.sales_invoice,
                modified=str(doc.modified))


def commission_quote(prop, data):
    if provider() == "pms":
        from hospitality_suite.standalone_agency_commissions import quote
        return quote(prop, data)
    require(prop.name, "commission")
    booking = document("HS Booking", data["booking"], "commission")
    if (not booking.travel_agent or booking.status != "Completed" or
            booking.agent_commission_invoice or booking.pms_agent_commission):
        frappe.throw(frappe._("La reserva no tiene una comisión pendiente de liquidar"))
    agent_doc = agent(prop, booking.travel_agent, active=False, action="commission")
    if not agent_doc.supplier or not current_all("HS Supplier", {"property": prop.name,
            "supplier": agent_doc.supplier, "active": 1}):
        frappe.throw(frappe._("Vincule la agencia a un proveedor activo del establecimiento"))
    if not prop.agent_commission_item or not prop.expense_account:
        frappe.throw(frappe._("Configure artículo y cuenta de gasto para comisiones"))
    expense_account=locked_doc("Account",prop.expense_account)
    if expense_account.company!=prop.company or expense_account.root_type!="Expense" or expense_account.is_group:
        frappe.throw(frappe._("La cuenta de comisión debe ser un gasto imputable de la compañía"))
    item = locked_doc("Item", prop.agent_commission_item)
    if item.disabled or item.is_stock_item or not item.is_purchase_item:
        frappe.throw(frappe._("El artículo de comisión debe ser comprable y sin inventario"))
    stays = current_all("HS Stay", {"property": prop.name, "booking": booking.name}, pluck="name")
    if not stays or current_all("HS Stay", {"property": prop.name, "booking": booking.name,
                                "status": "Active"}, pluck="name"):
        frappe.throw(frappe._("Todas las estancias deben estar finalizadas"))
    charges = current_all("HS Charge", {"property": prop.name, "stay": ["in", stays]},
                          fields=["name", "kind", "amount", "status", "applies_to_charge", "sales_invoice"])
    lodging = {row.name for row in charges if row.kind == "Lodging" and not row.applies_to_charge}
    relevant = [row for row in charges if row.name in lodging or row.applies_to_charge in lodging]
    if not relevant or any(row.status != "Invoiced" or not row.sales_invoice or
                           frappe.db.get_value("Sales Invoice", row.sales_invoice, "docstatus") != 1 for row in relevant):
        frappe.throw(frappe._("Facture todos los cargos de alojamiento antes de liquidar la comisión"))
    source_invoices={row.sales_invoice for row in relevant}
    if frappe.db.exists("Sales Invoice", {"return_against": ["in", list(source_invoices)], "docstatus": 1}):
        frappe.throw(frappe._("Revise las notas de crédito del alojamiento antes de liquidar la comisión en ERPNext"))
    base = money(sum(decimal(row.amount) for row in relevant), currency=prop.currency)
    if base <= 0:
        frappe.throw(frappe._("No hay alojamiento facturado con base positiva"))
    amount = money(base * _percent(booking.agent_commission_pct) / 100, currency=prop.currency)
    if amount <= 0:
        frappe.throw(frappe._("La comisión acordada no genera importe a pagar"))
    return dict(booking=booking.name, modified=str(booking.modified), agent=agent_doc.name,
                supplier=agent_doc.supplier, item=item.name, expense_account=prop.expense_account,
                base=str(base), percent=str(booking.agent_commission_pct), amount=str(amount), currency=prop.currency)


def settle_commission(prop, data):
    if provider() == "pms":
        from hospitality_suite.standalone_agency_commissions import settle
        return settle(prop, data)
    require(prop.name, "commission")
    ready(prop)
    q = commission_quote(prop, data)
    booking = document("HS Booking", q["booking"], "commission")
    assert_version(booking, data.get("modified"))
    inv = frappe.new_doc("Purchase Invoice")
    inv.update(dict(company=prop.company, supplier=q["supplier"], posting_date=nowdate(),
                    due_date=nowdate(), currency=prop.currency, cost_center=prop.cost_center,
                    update_stock=0, remarks=f"Comisión de agencia · {booking.name}"))
    inv.append("items", dict(item_code=q["item"], qty=1, rate=float(decimal(q["amount"])), warehouse=prop.warehouse,
                              expense_account=q["expense_account"], cost_center=prop.cost_center,
                              description=f"{q['agent']} · {booking.name} · {q['percent']} % sobre {q['base']}"))
    inv.set_missing_values()
    inv.calculate_taxes_and_totals()
    post_standard(inv, prop)
    booking.agent_commission_invoice = inv.name
    booking.save()
    audit(prop, "Settle agent commission", booking, details=dict(purchase_invoice=inv.name, **q))
    return dict(booking=booking.name, invoice=inv.name, amount=q["amount"], currency=q["currency"])


def board(prop):
    require(prop.name)
    agents = frappe.get_all("HS Travel Agent", filters={"property": prop.name, "company": prop.company},
                            fields=["name", "agent_name", "agent_type", "contact_name", "contact_phone",
                                    "contact_email", "commission_pct", "supplier", "pms_supplier",
                                    "active", "modified"], limit=500)
    experiences = frappe.get_all("HS Experience", filters={"property": prop.name, "company": prop.company},
                                 fields=["name", "experience_name", "experience_category", "item", "pms_product", "duration",
                                         "description", "image_url", "show_on_booking_page", "active", "modified"], limit=500)
    orders = frappe.get_all("HS Experience Order", filters={"property": prop.name, "company": prop.company},
                            fields=["name", "experience", "booking", "stay", "folio", "customer", "item",
                                    "pms_product", "quantity",
                                    "participants", "scheduled_at", "unit_rate", "amount", "currency", "status",
                                    "charge", "pms_receivable", "sales_invoice",
                                    "accepted_net", "accepted_tax", "accepted_total",
                                    "accepted_tax_profile", "income_account", "tax_account",
                                    "notes", "cancel_reason", "modified"], limit=500, order_by="creation desc")
    contribution=frappe.db.sql("""SELECT travel_agent, COUNT(*) AS bookings,
        COALESCE(SUM(amount),0) AS accepted_lodging,
        COALESCE(SUM(agent_commission_estimate),0) AS estimated_commission
        FROM `tabHS Booking` WHERE property=%s AND company=%s AND travel_agent IS NOT NULL
        AND status IN ('Confirmed','Checked In','Completed') GROUP BY travel_agent""",
        (prop.name,prop.company),as_dict=True)
    order_totals=frappe.db.sql("""SELECT status, COUNT(*) AS orders,
        COALESCE(SUM(amount),0) AS amount FROM `tabHS Experience Order`
        WHERE property=%s AND company=%s GROUP BY status""",(prop.name,prop.company),as_dict=True)
    return dict(agents=agents, experiences=experiences, orders=orders,
                contribution=contribution, order_totals=order_totals)


def pms_snapshot(property_name):
    from hospitality_suite.standalone_accounting import require_pms
    from hospitality_suite.security import ACTIONS, is_system
    prop = require(property_name)
    require_pms(prop)
    roles = set(frappe.get_roles())
    if not is_system() and not roles.intersection(
            ACTIONS["reserve"] + ACTIONS["commission"] + ACTIONS["finance"] +
            ACTIONS["setup"] + ACTIONS["approve"]):
        frappe.throw(frappe._("No tiene permiso para agencias y experiencias"), frappe.PermissionError)
    financial = is_system() or bool(roles.intersection(
        ACTIONS["commission"] + ACTIONS["finance"] + ACTIONS["setup"] +
        ACTIONS["approve"]))
    result = board(prop)
    result["currency"] = prop.currency
    result["products"] = frappe.get_all("HS Product", filters={"property": prop.name,
        "organization": prop.organization, "product_type": "Service", "active": 1},
        fields=["name", "product_name", "sales_rate", "tax_profile"],
        order_by="product_name asc", limit_page_length=500)
    result["suppliers"] = frappe.get_all("HS Party", filters={"property": prop.name,
        "organization": prop.organization, "party_type": ["in", ["Supplier", "Both"]],
        "active": 1}, fields=["name", "party_name"],
        order_by="party_name asc", limit_page_length=500)
    result["customers"] = frappe.get_all("HS Party", filters={"property": prop.name,
        "organization": prop.organization, "party_type": ["in", ["Customer", "Both"]],
        "active": 1}, fields=["name", "party_name"],
        order_by="party_name asc", limit_page_length=500) if financial else []
    result["receivable_accounts"] = frappe.get_all("HS Account", filters={
        "property": prop.name, "organization": prop.organization, "root_type": "Asset",
        "account_type": "Receivable", "account_currency": prop.currency,
        "is_group": 0, "active": 1},
        fields=["name", "account_code", "account_name"],
        order_by="account_code asc") if financial else []
    result["income_accounts"] = frappe.get_all("HS Account", filters={
        "property": prop.name, "organization": prop.organization,
        "root_type": "Income", "account_currency": prop.currency,
        "is_group": 0, "active": 1},
        fields=["name", "account_code", "account_name"],
        order_by="account_code asc") if financial else []
    result["tax_profiles"] = frappe.get_all("HS PMS Tax Profile", filters={
        "property": prop.name, "organization": prop.organization, "active": 1},
        fields=["name", "label", "treatment", "rate", "included_in_price"],
        order_by="label asc") if financial else []
    result["bookings"] = frappe.get_all("HS Booking", filters={"property": prop.name,
        "status": ["in", ["Confirmed", "Checked In", "Completed"]]},
        fields=["name", "customer", "status", "travel_agent", "pms_agent_commission"],
        order_by="creation desc", limit_page_length=500)
    result["stays"] = frappe.get_all("HS Stay", filters={"property": prop.name,
        "status": "Active"}, fields=["name", "booking", "room"],
        order_by="creation desc", limit_page_length=500)
    result["folios"] = frappe.get_all("HS Folio", filters={"property": prop.name,
        "status": "Open"}, fields=["name", "booking", "stay", "customer", "label"],
        order_by="creation desc", limit_page_length=500)
    result["property_modified"] = str(prop.modified)
    result["commission_expense_account"] = prop.pms_commission_expense_account if financial else None
    result["commission_payable_account"] = prop.pms_commission_payable_account if financial else None
    result["commission_accounts"] = frappe.get_all("HS Account", filters={
        "property": prop.name, "organization": prop.organization, "active": 1,
        "is_group": 0, "account_currency": prop.currency,
        "root_type": ["in", ["Expense", "Liability"]]},
        fields=["name", "account_code", "account_name", "root_type", "account_type"],
        order_by="account_code asc") if financial else []
    result["methods"] = frappe.get_all("HS Payment Method", filters={
        "property": prop.name}, fields=["name", "mode_of_payment", "currency", "is_cash"],
        order_by="mode_of_payment asc") if financial else []
    result["shifts"] = frappe.get_all("HS Shift", filters={"property": prop.name,
        "cashier": frappe.session.user, "status": "Open"},
        fields=["name", "opened_at"], order_by="opened_at desc") if financial else []
    if financial:
        from hospitality_suite.standalone_agency_commissions import outstanding
        result["commissions"] = frappe.get_all("HS PMS Agency Commission", filters={
            "property": prop.name}, fields=["name", "booking", "agent", "agent_name",
                "supplier", "base_amount", "percent", "amount", "currency",
                "business_date", "expense_account", "payable_account",
                "status", "journal", "reversal_journal", "modified"],
            order_by="creation desc", limit_page_length=500)
        for row in result["commissions"]:
            row["outstanding"] = str(outstanding(prop, row.name))
    else:
        result["commissions"] = []
    return result


def erp_snapshot(property_name):
    from hospitality_suite.security import ACTIONS, is_system

    prop = require(property_name)
    if provider() != "erpnext":
        frappe.throw(frappe._("Las experiencias ERPNext no están activas en este sitio"))
    roles = set(frappe.get_roles())
    if not is_system() and not roles.intersection(
            ACTIONS["reserve"] + ACTIONS["service"] + ACTIONS["commission"] +
            ACTIONS["finance"] + ACTIONS["setup"] + ACTIONS["approve"]):
        frappe.throw(frappe._("No tiene permiso para agencias y experiencias"), frappe.PermissionError)
    result = board(prop)
    result["currency"] = prop.currency
    linked = frappe.get_all("HS Supplier", filters={"property": prop.name,
        "company": prop.company, "active": 1}, fields=["supplier"],
        limit_page_length=500)
    supplier_names = sorted({row.supplier for row in linked if row.supplier})
    result["suppliers"] = frappe.get_all("Supplier",
        filters={"name": ["in", supplier_names], "disabled": 0},
        fields=["name", "supplier_name"], order_by="supplier_name asc",
        limit_page_length=500) if supplier_names else []
    result["bookings"] = frappe.get_all("HS Booking", filters={
        "property": prop.name, "company": prop.company,
        "status": ["in", ["Confirmed", "Checked In", "Completed"]]},
        fields=["name", "customer", "status", "travel_agent",
                "agent_commission_invoice", "pms_agent_commission"],
        order_by="creation desc", limit_page_length=500)
    result["stays"] = frappe.get_all("HS Stay", filters={
        "property": prop.name, "company": prop.company, "status": "Active"},
        fields=["name", "booking", "room"], order_by="creation desc",
        limit_page_length=500)
    result["folios"] = frappe.get_all("HS Folio", filters={
        "property": prop.name, "company": prop.company, "status": "Open"},
        fields=["name", "booking", "stay", "customer", "label"],
        order_by="creation desc", limit_page_length=500)
    return result
