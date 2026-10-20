/* Historical explanations are server projections, never browser price calculations. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  Desk.prototype.priceExplanation=function(charge){
    const p=charge.pricing;
    if(!p)return '';
    return `<details class="hs-price-explanation"><summary>${e(__("Ver cálculo del precio"))}</summary><div><h5>${e(p.title)}${p.mode_label?' · '+e(p.mode_label):''}</h5><p>${e(p.scope)}</p>`+
      `<p><strong>${e(__("Importe de este movimiento"))}: ${e(this.amount(p.recorded_amount,p.currency))}</strong></p>`+
      (p.entries||[]).map(entry=>`<section><strong>${e(entry.label)}</strong><ul>${(entry.details||[]).map(line=>`<li>${e(line)}</li>`).join('')}</ul><p>${e(__("Importe histórico de referencia"))}: ${e(this.amount(entry.amount,entry.currency))}</p></section>`).join('')+
      `<ul>${(p.notes||[]).map(note=>`<li>${e(note)}</li>`).join('')}</ul></div></details>`;
  };
})();
