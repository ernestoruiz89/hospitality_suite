/* Refund reviews preserve the original receipt key while showing human labels. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  Desk.prototype.paymentSourceLabel=function(row){
    const labels={Payment:__("Cobro"),Advance:__("Anticipo"),Guarantee:__("Garantía"),"Guarantee Applied":__("Garantía aplicada")};
    return `${labels[row.kind]||__("Movimiento")} · ${this.date(row.creation)} · ${this.amount(row.amount,row.currency)} · ${row.payment_entry||row.journal_entry||""}`;
  };
  Desk.prototype.refundSummary=function(quote){
    const refund=quote.refund;if(!refund)return "";
    const label=refund.mode==="Applied Advance"?__("Devolución de anticipo aplicado"):refund.mode==="Unallocated Advance"?__("Devolución de anticipo disponible"):refund.mode==="Applied Guarantee"?__("Devolución de garantía aplicada a factura"):refund.mode==="Unallocated Guarantee Application"?__("Devolución de garantía aplicada, aún sin facturar"):__("Devolución de cobro facturado");
    return `<p><strong>${e(label)}</strong></p>${refund.credit_note?`<p>${e(__("Nota de crédito de origen:"))} ${e(refund.credit_note)}</p>`:""}<p>${e(__("Valor que se liquida en la cuenta del cliente:"))} ${e(this.amount(refund.party_amount,refund.party_currency))}</p><p>${e(__("Diferencia de cambio en moneda base:"))} ${e(this.amount(refund.exchange_difference,quote.base_currency))}</p>`;
  };
  const dialog=Desk.prototype.dialog;
  Desk.prototype.dialog=async function(title,fields,...args){
    const source=fields.find(df=>df.fieldname==="source_payment"&&Array.isArray(df.options));
    const refundForm=fields.some(df=>df.fieldname==="kind"&&Array.isArray(df.options)&&df.options.some(option=>(option.value||option)==="Refund"));
    if(source&&refundForm){
      const labels={Payment:__("Cobro"),Advance:__("Anticipo"),Guarantee:__("Garantía"),"Guarantee Applied":__("Garantía aplicada")};
      source.options=source.options.flatMap(option=>{
        if(!option.value)return [option];
        const row=(this.data.payments||[]).find(row=>row.name===option.value);
        if(!row||row.status!=="Posted"||!labels[row.kind])return [];
        return [{...option,label:this.paymentSourceLabel(row)}];
      });
      fields.push({fieldname:"refund_help",fieldtype:"HTML",options:`<p>${e(__("Para devolver un anticipo o garantía ya aplicados a una factura, seleccione su nota de crédito. Deje la nota vacía para devolver fondos aún sin asignar a facturas. El servidor comprueba los fondos originales y el crédito disponible antes de confirmar."))}</p><p>${e(__("Use Devolución con el movimiento Garantía aplicada. Devolución de garantía corresponde al importe que aún permanece retenido."))}</p>`});
    }
    return dialog.call(this,title,fields,...args);
  };
})();
