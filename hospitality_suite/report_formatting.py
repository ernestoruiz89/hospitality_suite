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
LABELS.update(source_payment="Movimiento original",expense_category="Categoría de gasto",supplier="Proveedor",purchase_invoice="Factura de compra",fee_amount="Comisión",withholding_amount="Retención",net_amount="Neto bancario",reference="Referencia bancaria",settlement_direction="Flujo bancario")
LABELS.update(warehouse="Almacén",purpose="Uso operativo",classification="Clasificación",balance_quantity="Existencia tras movimiento",posting_time="Hora contable",cost_center="Centro de costo",expense_account="Cuenta de gasto")
LABELS.update(equipment="Equipo",blocks_room="Bloquea habitación")
LABELS.update(relationship="Participación en la estancia")
LABELS.update(company="Compañía",property="Establecimiento",time_zone="Zona horaria",adjustment_type="Tipo de ajuste",duration_minutes="Duración (min)",
              total_rooms="Habitaciones habilitadas",available_capacity="Cupo simultáneo disponible",candidate_rooms="Habitaciones candidatas",clean_candidates="Candidatas limpias ahora",selected_room_available="Habitación seleccionada disponible")
LABELS.update(revenue_net="Ingreso neto facturado",source_type="Origen de producción")
LABELS.update(pending_amount="Importe sin facturar",records="Registros de origen")
LABELS.update(guest="Huésped")
LABELS.update(invoice_number="Número de factura",account_label="Cuenta",recorded_at="Fecha y hora")
LABELS.update(base_currency="Moneda base")
NUMBERS={"amount","quantity","grand_total","outstanding_amount","base_amount","expected_amount","counted_amount","difference","cost","expected","actual","pending","outstanding","fee_amount","withholding_amount","net_amount"}
NUMBERS.add("balance_quantity")
NUMBERS.update({"duration_minutes","total_rooms","available_capacity","clean_candidates"})
NUMBERS.add("revenue_net")
NUMBERS.update({"pending_amount","records"})
MONEY_FIELDS=NUMBERS-{"quantity","duration_minutes","total_rooms","available_capacity","clean_candidates","balance_quantity","records"}


def label(key):
    return LABELS.get(key,key)


def display(key,value,record=None):
    if record and key in record.get("_display",{}):
        return record["_display"][key]
    if key=="selected_room_available" and value is not None:
        return "Sí" if value else "No"
    if key=="cleaning_status":
        return {"Clean":"Limpia","Dirty":"Pendiente de limpieza","Cleaning":"En limpieza","Inspection":"Pendiente de inspección"}.get(value,value)
    if key in ("status","kind","type","cleaning_status","settlement_direction","purpose","classification","adjustment_type"):
        from hospitality_suite.printing import hs_label
        return hs_label(value)
    return value


def xlsx_data(records,headers):
    from hospitality_suite.pricing import decimal,currency_precision
    rows=[[label(k) for k in headers]]
    for record in records:
        row=[]
        for key in headers:
            value=display(key,record.get(key),record)
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
    formats={}
    precisions={}
    for i,record in enumerate(records,1):
        for j,key in enumerate(headers):
            if key in MONEY_FIELDS:
                currency=record.get("base_currency") if key=="base_amount" else record.get("currency")
                if currency not in precisions:
                    precisions[currency]=currency_precision(currency)
                precision=precisions[currency]
                if precision not in formats:
                    formats[precision]=len(styles["styles"])
                    styles["styles"].append({"num_format":"#,##0"+("."+"0"*precision if precision else ""),"font_name":"Arial","font_size":10})
                styles["cell_styles"][(i,j)]=[formats[precision]]
    return rows,widths,styles


def pdf_html(title,scope,records,headers,note):
    """Wide reports use readable column groups with repeated source keys."""
    from html import escape
    from hospitality_suite.pricing import money
    anchors=(["name"]+(["room"] if "room" in headers else [])) if "name" in headers else (["property",headers[0]] if "property" in headers and headers[0]!="property" else [headers[0]])
    remaining=[k for k in headers if k not in anchors]
    width=max(1,8-len(anchors))
    bands=[headers] if len(headers)<=8 else [anchors+remaining[i:i+width] for i in range(0,len(remaining),width)]
    html="<style>body{font-family:Arial,sans-serif;color:#173c32;font-size:11px}h1{font-size:24px}h2{font-size:14px}table{width:100%;table-layout:fixed;border-collapse:collapse}th{background:#eaf0e9;text-align:left}th,td{padding:5px;border-bottom:1px solid #dce5dc;word-wrap:break-word;overflow-wrap:break-word}thead{display:table-header-group}tr{page-break-inside:avoid}.numeric{text-align:right;white-space:nowrap}.new-band{page-break-before:always}</style>"
    money_fields=MONEY_FIELDS
    for index,band in enumerate(bands):
        html+=f'<section class="{"new-band" if index else ""}"><h1>{escape(title)}</h1><p>{escape(scope)} · {len(records)} registros autorizados</p><p>{escape(note)}</p>'
        if len(bands)>1:
            html+=f'<h2>Detalle {index+1} de {len(bands)}</h2><p>Las referencias se repiten para relacionar las columnas de cada detalle.</p>'
        html+='<table><thead><tr>'+''.join(f'<th>{escape(label(k))}</th>' for k in band)+'</tr></thead><tbody>'
        for row in records:
            html+='<tr>'
            for key in band:
                value=display(key,row.get(key),row)
                if value is None:
                    value=''
                if key in money_fields and value!='':
                    value=str(money(value,currency=row.get('base_currency') if key=='base_amount' else row.get('currency')))
                html+=f'<td class="{"numeric" if key in NUMBERS else ""}">{escape(str(value))}</td>'
            html+='</tr>'
        html+='</tbody></table></section>'
    return html
