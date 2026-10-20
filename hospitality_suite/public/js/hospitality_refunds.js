/* Refund reviews preserve the original receipt key while showing human labels. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  Desk.prototype.refundSummary=function(quote){
    const refund=quote.refund;if(!refund)return "";
    const label=refund.mode==="Applied Advance"?__("Devolución de anticipo aplicado"):refund.mode==="Unallocated Advance"?__("Devolución de anticipo disponible"):__("Devolución de cobro facturado");
    return `<p><strong>${e(label)}</strong></p>${refund.credit_note?`<p>${e(__("Nota de crédito de origen:"))} ${e(refund.credit_note)}</p>`:""}<p>${e(__("Valor que se liquida en la cuenta del cliente:"))} ${e(this.amount(refund.party_amount,refund.party_currency))}</p><p>${e(__("Diferencia de cambio en moneda base:"))} ${e(this.amount(refund.exchange_difference,quote.base_currency))}</p>`;
  };
  const dialog=Desk.prototype.dialog;
  Desk.prototype.dialog=async function(title,fields,...args){
    const source=fields.find(df=>df.fieldname==="source_payment"&&Array.isArray(df.options));
    if(source){
      const labels={Payment:__("Cobro"),Advance:__("Anticipo"),Guarantee:__("Garantía")};
      source.options=source.options.flatMap(option=>{
        if(!option.value)return [option];
        const row=(this.data.payments||[]).find(row=>row.name===option.value);
        if(!row||row.status!=="Posted"||!labels[row.kind])return [];
        return [{...option,label:`${labels[row.kind]} · ${this.date(row.creation)} · ${this.amount(row.amount,row.currency)} · ${row.payment_entry||row.journal_entry||""}`}];
      });
      fields.push({fieldname:"refund_help",fieldtype:"HTML",options:`<p>${e(__("Para devolver un anticipo ya aplicado, seleccione su nota de crédito. Si todavía no se aplicó, deje esa nota vacía. El servidor comprueba los fondos originales y el crédito disponible antes de confirmar."))}</p>`});
    }
    return dialog.call(this,title,fields,...args);
  };
})();
