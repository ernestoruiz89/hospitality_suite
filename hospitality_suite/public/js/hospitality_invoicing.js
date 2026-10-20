/* Issue a reviewed invoice without requiring a cash movement or guest departure. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  Desk.prototype.action_invoice=async function(id){
    if(!this.allowed("finance"))return;
    const info=await this.call("stay_detail",{name:id}),folios=info.folios.filter(row=>row.status==="Open");
    if(!folios.length){frappe.msgprint(__("La estancia no tiene una cuenta abierta para facturar."));return;}
    const key=frappe.utils.get_random(24);
    return this.dialog(__("Facturar cuenta"),[
      {fieldname:"purpose",fieldtype:"HTML",options:`<p>${e(__("Se emitirá una factura de ERPNext. La estancia permanece activa y no se registra un cobro."))}</p><p>${e(__("Incluye todas las noches programadas y cargos pendientes de la cuenta elegida."))}</p>`},
      {fieldname:"folio",label:__("Cuenta que desea facturar"),fieldtype:"Select",reqd:1,_hsDataOptions:true,
       default:folios.length===1?folios[0].name:"",options:[{value:"",label:__("Seleccione…")},...folios.map(row=>({value:row.name,label:row.label}))]}
    ],async(values,parent)=>{
      const quote=await this.call("preview",{property_name:this.property,action:"invoice",data:JSON.stringify(values)});
      if(!quote.ready){frappe.msgprint(__("Esta cuenta no tiene cargos nuevos para facturar. Consulte sus facturas y saldos."));return;}
      await this.dialog(__("Revisar factura"),[{fieldname:"review",fieldtype:"HTML",options:
        `<p>${e(quote.label)} · ${e(quote.customer)}</p><p>${e(__("Fecha contable:"))} ${e(quote.posting_date)}</p>`+
        `<h2>${e(__("Total a facturar:"))} ${e(this.amount(quote.payable,quote.currency))}</h2>`+
        `<p>${e(__("Neto:"))} ${e(this.amount(quote.net_total,quote.currency))} · ${e(__("Impuestos:"))} ${e(this.amount(quote.taxes,quote.currency))}</p>`+
        (quote.total!==quote.payable?`<p>${e(__("Total antes del redondeo:"))} ${e(this.amount(quote.total,quote.currency))}</p>`:"")+
        this.table([__("Concepto"),__("Importe")],[[__("Anticipos y garantías por aplicar"),e(this.amount(quote.advance,quote.currency))],
          [__("Saldo de la nueva factura"),e(this.amount(quote.outstanding,quote.outstanding_currency))]])+
        `<p>${e(__("Alojamiento programado incluido:"))} ${e(this.amount(quote.scheduled,quote.currency))}</p><p>${e(__("Emitir la factura no agrega un nuevo movimiento de dinero ni registra la salida."))}</p>`}],
        async(values,confirmation)=>{
          const result=await this.mutate("invoice",{folio:quote.folio,invoice_acceptance:quote.acceptance},key);
          confirmation.hide();parent.hide();
          frappe.msgprint({title:__("Factura emitida"),message:`<p>${e(__("Total facturado:"))} ${e(this.amount(quote.payable,quote.currency))}</p><p>${e(__("Saldo pendiente:"))} ${e(this.amount(result.outstanding,quote.outstanding_currency))}</p><p>${e(__("La estancia permanece activa."))}</p>${this.invoiceLink(result.invoice)}`});
        },__("Emitir factura"));
    },__("Revisar factura"));
  };
})();
