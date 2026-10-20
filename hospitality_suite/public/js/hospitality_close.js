/* Read the saved close snapshot; dates and totals never come from live re-sums. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  Desk.prototype.close_summary_html=function(period,blockers=[]){
    let html=`<p>${e(__("Período operativo:"))} ${e(period.local_starts_at||"")} → ${e(period.local_ends_at||"")} · ${e(period.time_zone||this.prop.time_zone)}</p>`;
    html+=`<p>${e(__("La preparación del cierre genera las noches programadas de esta fecha y las vencidas. Los importes de fechas futuras se muestran por separado. La fecha operativa avanza al confirmar."))}</p>`;
    html+=`<p>${e(__("Indicadores calculados a la hora de cada revisión o cierre."))}</p>`+this.table([__("Indicador"),__("Valor")],[[__("Habitaciones-noche"),e(period.room_nights??"—")],[__("Horas ocupadas"),e(period.occupied_hours??"—")],[__("ADR"),e(period.ADR??"—")+" "+e(period.currency||"")],[__("RevPAR"),e(period.RevPAR??"—")+" "+e(period.currency||"")]]);
    const finance=period.financial;
    if(finance){
      html+=`<p>${e(__("Fecha contable de facturación:"))} ${e(finance.posting_date)} · ${e(__("Fecha operativa de movimientos:"))} ${e(finance.business_date)}</p><p>${e(__("Saldos capturados al ejecutar, de todas las fechas. Las monedas permanecen separadas. Anticipos y garantías no son ingreso de alojamiento."))}</p>`;
      html+=`<p>${e(__("Los créditos a favor se muestran por separado; no compensan facturas sin conciliación."))}</p>`;
      for(const group of this.data.close_financial_groups||[]){
        const hasAmounts=finance.currencies.some(row=>group.metrics.some(metric=>Number(row[metric.key]||0)!==0));
        html+=`<details class="hs-close-group"${hasAmounts?" open":""}><summary>${e(group.title)}</summary>`;
        html+=finance.currencies.length?this.table([__("Concepto"),__("Importe"),__("Moneda")],finance.currencies.flatMap(row=>group.metrics.map(metric=>[e(metric.label),e(row[metric.key]),e(row.currency)]))):this.empty(__("Sin movimientos ni saldos para mostrar."));
        html+='</details>';
      }
      if(finance.sources.unattributed_movements.length)html+=`<p role="alert">${e(__("Hay {0} movimientos históricos sin fecha operativa acreditada; revise sus documentos de origen.",[finance.sources.unattributed_movements.length]))}</p>`;
    }else html+=`<p>${e(__("Este cierre histórico no conserva el resumen financiero ampliado."))}</p>`;
    html+=`<h4>${e(__("Pendientes conservados"))}</h4>`+(blockers.length?`<ul>${blockers.map(row=>`<li>${e(__(row.type))}: ${e(row.documents.length)}</li>`).join("")}</ul>`:`<p>${e(__("Sin pendientes registrados."))}</p>`);
    return html;
  };
  Desk.prototype.action_daily_close=async function(){
    const result=await this.mutate("daily_close",{confirm:false}),key=frappe.utils.get_random(24);
    const dialog=await this.dialog(__("Cierre del día"),[{fieldname:"review",fieldtype:"HTML",options:this.close_summary_html(result.period,result.blockers)}],async(v,d)=>{
      await this.mutate("daily_close",{confirm:true,review_acceptance:result.review_acceptance},key);d.hide();
    },__("Confirmar cierre"),"extra-large");
    if(result.blockers.length||!this.allowed("approve"))dialog.get_primary_btn().prop("disabled",true);
    return dialog;
  };
  Desk.prototype.action_view_close=async function(id){
    const close=(this.data.closes||[]).find(row=>row.name===id);
    if(!close){frappe.msgprint(__("Actualice la página para consultar el cierre"));return;}
    const period=JSON.parse(close.summary||"{}"),blockers=JSON.parse(close.blockers||"[]");
    return this.dialog(__("Resumen conservado · {0}",[close.business_date]),[{fieldname:"saved_close",fieldtype:"HTML",options:this.close_summary_html(period,blockers)}],async(v,d)=>d.hide(),__("Cerrar"),"extra-large");
  };
})();
