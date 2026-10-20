/* Native POS receipts belong to the shift; ERPNext remains their only ledger. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  const render=Desk.prototype.render_cashier;
  Desk.prototype.render_cashier=function(el){
    render.call(this,el);
    const rows=this.data.native_pos||[];
    if(!rows.length)return;
    const detail=rows.map(row=>{
      const shift=this.data.shifts.find(value=>value.name===row.shift),label=shift?`${this.date(shift.opened_at)} · ${shift.cashier}`:__("Sin turno asignado");
      return [e(this.date(row.creation)),e(label),this.invoiceLink(row.name),e(!row.mapped?__("Sin clasificar"):row.is_cash?__("Efectivo"):__("Medio no efectivo")),this.amount(row.amount,row.currency),e(!row.shift?__("Revisar turno"):!row.mapped?__("Revisar medio de pago"):__("Contabilizado"))];
    });
    el.append(`<h2 class="hs-section-title">${e(__("Cobros POS de ERPNext"))}</h2><p>${e(__("Importes netos de vuelto y devoluciones. El efectivo se incluye en el esperado del turno; los medios no efectivos quedan fuera del efectivo físico."))}</p>${this.table([__("Fecha"),__("Turno"),__("Factura"),__("Medio"),__("Importe"),__("Estado")],detail)}`);
  };
})();
