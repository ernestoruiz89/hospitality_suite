"""Display labels and typed exports; source field names remain stable in the API."""
LABELS={"name":"Referencia","room_number":"Habitación","category":"Categoría","floor":"Piso","zone":"Zona","cleaning_status":"Limpieza","active":"Habilitada",
"customer":"Cliente pagador","posting_date":"Fecha contable","grand_total":"Total","outstanding_amount":"Saldo pendiente","currency":"Moneda","docstatus":"Estado contable",
"hs_stay":"Estancia","hs_folio":"Cuenta","is_return":"Nota de crédito","return_against":"Factura de origen","stay":"Estancia","booking":"Reserva","folio":"Cuenta",
"status":"Estado","starts_at":"Desde","ends_at":"Hasta","actual_check_in":"Entrada real","actual_check_out":"Salida real","room":"Habitación","channel":"Canal",
"amount":"Importe","quantity":"Cantidad","item":"Artículo","kind":"Concepto","sales_invoice":"Factura","business_date":"Fecha operativa","shift":"Turno","method":"Medio de pago",
"base_amount":"Importe en moneda base","payment_entry":"Payment Entry","journal_entry":"Journal Entry","cashier":"Responsable de caja","opened_at":"Apertura","closed_at":"Cierre",
"expected_amount":"Efectivo esperado","counted_amount":"Efectivo contado","difference":"Diferencia","assigned_to":"Responsable","started_at":"Inicio","completed_at":"Finalización",
"title":"Incidencia","cost":"Costo","stock_entry":"Documento de stock","return_stock_entry":"Reversión de stock","charge":"Cargo","action":"Acción","actor":"Usuario",
"occurred_at":"Momento","source_doctype":"Tipo de origen","source_name":"Documento de origen","reason":"Motivo","type":"Tipo","source":"Origen","erp_document":"Documento ERPNext",
"expected":"Esperado","actual":"Según ERPNext","detail":"Detalle","pending":"Sin facturar","outstanding":"Saldo pendiente"}
NUMBERS={"amount","quantity","grand_total","outstanding_amount","base_amount","expected_amount","counted_amount","difference","cost","expected","actual","pending","outstanding"}


def label(key):
    return LABELS.get(key,key)


def display(key,value):
    if key in ("status","kind","type","cleaning_status"):
        from hospitality_suite.printing import hs_label
        return hs_label(value)
    return value


def xlsx_data(records,headers):
    from hospitality_suite.pricing import decimal
    rows=[[label(k) for k in headers]]
    for record in records:
        row=[]
        for key in headers:
            value=display(key,record.get(key))
            if key in NUMBERS and value is not None:
                value=float(decimal(value))
            elif isinstance(value,str) and value.lstrip().startswith(("=","+","-","@")):
                value="'"+value
            row.append(value)
        rows.append(row)
    widths=[max(16,min(65,max(len(str(row[col] or "")) for row in rows)+3)) for col in range(len(headers))]
    styles={"styles":[{"bold":True,"bg_color":"#173C32","font_color":"#FFFFFF","font_name":"Arial","font_size":10},
                      {"num_format":"#,##0.00","font_name":"Arial","font_size":10},{"font_name":"Arial","font_size":10}],
            "row_styles":{0:[0]},"cell_styles":{(i,j):[1 if key in NUMBERS else 2] for i in range(1,len(rows)) for j,key in enumerate(headers)}}
    return rows,widths,styles
