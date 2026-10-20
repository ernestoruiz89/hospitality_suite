/* Credit notes show the native goods and money effects before posting. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  const f=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),fieldtype,...extra});
  Desk.prototype.creditSummary=function(quote){
    const rows=quote.items.map(row=>[e(row.item_name),e(row.quantity),e(this.amount(row.amount,quote.currency))]);
    const payments=(quote.pos?.payments||[]).map(row=>[e(row.mode_of_payment),e(row.is_cash?__("Efectivo"):__("Medio no efectivo")),e(Number(row.amount)<0?__("Recibir"):__("Devolver")),e(this.amount(Math.abs(Number(row.amount)),row.currency))]);
    const rounding=Number(quote.rounding_adjustment||0)?`<p>${e(__("Redondeo de la nota:"))} ${e(this.amount(quote.rounding_adjustment,quote.currency))}</p>`:"";
    const financial=rounding+(quote.pos?`<p>${e(__("Valor liquidado en la cuenta del cliente:"))} ${e(this.amount(quote.pos.party_amount,quote.pos.party_currency))} · ${e(__("Saldo de la factura que se compensa:"))} ${e(this.amount(quote.pos.offset,quote.pos.party_currency))}</p><p>${e(__("Reversión del ajuste original en moneda base:"))} ${e(this.amount(quote.pos.write_off_base,quote.pos.base_currency))} · ${e(__("Diferencia de cambio y redondeo en moneda base:"))} ${e(this.amount(quote.pos.exchange_difference,quote.pos.base_currency))}</p>`:"");
    return `<h3>${e(__("Nota de crédito:"))} ${e(this.amount(quote.total,quote.currency))}</h3><p>${e(quote.is_pos?__("Esta nota también registra la devolución por los medios originales, neta del vuelto. Revise el dinero antes de confirmar."):__("Esta nota corrige la factura. Las facturas de estancia se devuelven desde Cobrar; para otros orígenes use su flujo de devolución correspondiente."))}</p><p>${e(quote.update_stock?__("ERPNext devolverá las existencias de esta factura."):__("Los consumos entregados conservan su devolución de inventario por separado."))}</p>${this.table([__("Artículo o servicio"),__("Cantidad"),__("Importe")],rows)}${payments.length?this.table([__("Medio"),__("Tipo"),__("Acción"),__("Importe")],payments):""}${financial}`;
  };
  Desk.prototype.action_credit=async function(){
    const key=frappe.utils.get_random(24);
    const fields=[f("invoice",__("Factura de origen"),"Link",{options:"Sales Invoice",reqd:1,get_query:()=>({filters:{hs_property:this.property,docstatus:1,is_return:0}})}),
      f("shift",__("Turno de devolución POS"),"Select",{_hsDataOptions:true,options:[{value:"",label:__("Seleccione si la factura es POS…")},...this.data.shifts.filter(row=>row.status==="Open").map(row=>({value:row.name,label:`${this.date(row.opened_at)} · ${row.cashier} · ${row.currency}`}))]}),
      f("reference",__("Referencia bancaria de devolución (si corresponde)")),f("partial",__("Seleccionar cantidades (devolución parcial)"),"Check"),f("reason",__("Motivo"),"Small Text",{reqd:1})];
    const review=async(values,quote,source,selection)=>this.dialog(__("Revisar nota de crédito"),[f("summary",__("Efectos de la nota"),"HTML",{options:this.creditSummary(quote)})],async(_,confirmation)=>{
      const result=await this.mutate("credit_note",{...values,acceptance:quote.acceptance},key);
      confirmation.hide();selection?.hide();source.hide();
      const journal=result.refund_journal?`<br><a target="_blank" rel="noopener" href="/printview?doctype=Journal%20Entry&name=${encodeURIComponent(result.refund_journal)}&format=Standard">${e(result.refund_journal)}</a>`:"";
      frappe.msgprint({title:__("Nota de crédito registrada"),message:this.invoiceLink(result.credit_note)+journal});
    },__("Confirmar nota de crédito"));
    return this.dialog(__("Nota de crédito"),fields,async(values,source)=>{
      const {partial,...data}=values;
      const quote=await this.call("preview",{property_name:this.property,action:"credit_note",data:JSON.stringify(data)});
      if(!partial)return review(data,quote,source);
      return this.dialog(__("Cantidades a devolver"),[f("items",__("Artículos o servicios"),"Table",{in_place_edit:true,cannot_add_rows:true,cannot_delete_rows:true,
        data:quote.items.map(row=>({...row,quantity:Number(row.quantity)})),fields:[f("invoice_item",__("Línea original"),"Data",{hidden:1,read_only:1}),f("item_name",__("Artículo o servicio"),"Data",{read_only:1,in_list_view:1}),f("quantity",__("Cantidad a devolver (0 = ninguna)"),"Float",{in_list_view:1})]})],async(selected,selection)=>{
          if(selected.items.some(row=>Number(row.quantity)<0))frappe.throw(__("La cantidad a devolver no puede ser negativa"));
          const items=selected.items.filter(row=>Number(row.quantity)>0).map(row=>({invoice_item:row.invoice_item,quantity:row.quantity}));
          const dataWithItems={...data,items},updated=await this.call("preview",{property_name:this.property,action:"credit_note",data:JSON.stringify(dataWithItems)});
          return review(dataWithItems,updated,source,selection);
        },__("Revisar importes"));
    },__("Revisar nota"));
  };
})();
