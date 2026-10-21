/* Read the saved close snapshot; dates and totals never come from live re-sums. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  Desk.prototype.close_summary_html=function(period,blockers=[],{live=false}={}){
    const labels=period.close_review,local=value=>String(value||'').replace(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}).*$/,'$3/$2/$1 $4');
    let html=labels?`<p><strong>${e(__('Fecha operativa'))}: ${e(labels.date_label)}</strong> · ${e(__('Hora de corte'))}: ${e(labels.close_time)}<br>${e(labels.starts_at)} → ${e(labels.ends_at)} · ${e(labels.time_zone)}</p>`:`<p>${e(__("Período operativo:"))} ${e(local(period.local_starts_at))} → ${e(local(period.local_ends_at))} · ${e(period.time_zone||this.prop.time_zone)}</p>`;
    html+=this.close_blockers_html(blockers);
    if(live)html+=`<button type="button" class="btn btn-secondary" data-hs-close-refresh>${e(__('Actualizar revisión'))}</button>`;
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
    if(period.audit_review){
      const counts={};for(const row of period.audit_review.rows||[])counts[row.category]=(counts[row.category]||0)+1;
      html+=`<details><summary>${e(__('Registros para revisar'))} (${period.audit_review.rows.length})</summary>`+this.table([__('Clase de registro'),__('Cantidad')],Object.entries(counts).map(([label,count])=>[e(label),count]))+`<button type="button" class="btn btn-secondary" data-hs-audit-review>${e(__('Ver registros'))}</button></details>`;
    }
    return html;
  };
  Desk.prototype.close_blockers_html=function(blockers){
    return `<section class="hs-close-pending"><h3>${e(__('Pendientes conservados'))}</h3>`+(blockers.length?
      `<p role="alert">${e(__('Resuelva estos pendientes y actualice la revisión antes de confirmar.'))}</p><div class="hs-close-pending-grid">${blockers.map((group,index)=>`<article><h4>${e(__(group.type))} (${group.documents.length})</h4><p>${e(group.hint||__('Consulte el documento de origen para resolver el pendiente.'))}</p><button type="button" class="btn btn-secondary" data-hs-close-pending="${index}">${e(__('Ver pendientes'))}</button></article>`).join('')}</div>`:
      `<p>${e(__("Sin pendientes registrados."))}</p>`)+`</section>`;
  };
  Desk.prototype.bind_close_checks=function(dialog,blockers,live=false){
    const property=this.property;
    dialog.$wrapper?.on('click','[data-hs-close-pending]',event=>{if(this.property===property)this.show_close_pending(blockers,Number(event.currentTarget.dataset.hsClosePending));});
    if(live)dialog.$wrapper?.on('click','[data-hs-close-refresh]',()=>{if(this.property===property){dialog.hide();this.action_daily_close();}});
  };
  Desk.prototype.show_close_pending=async function(groups,index){
    const group=groups[index];if(!group)return;
    const items=group.items||[],property=this.property,hasAccounts=items.some(row=>row.stay)&&(this.allowed('finance')||this.allowed('stay'));let offset=0,dialog;
    const pages={'hospitality-reservations':__('Ir a Reservas'),'hospitality-stays':__('Ir a Estancias'),'hospitality-cashier':__('Ir a Caja')};
    const page=Object.hasOwn(pages,group.page)&&(this.data.pages||[]).some(row=>row.route===group.page)?group.page:null;
    const html=()=>`<p>${e(group.hint||__('Este resumen conserva los pendientes de aquella ejecución.'))}</p>`+(items.length?
      this.table([__('Documento'),__('Qué revisar'),...(hasAccounts?[__('Acción')]:[])],items.slice(offset,offset+25).map((row,n)=>[e(row.label),e(row.detail),...(hasAccounts?[row.stay?`<button type="button" class="btn btn-secondary" data-hs-pending-account="${offset+n}">${e(__('Abrir cuenta'))}</button>`:'—']:[])])):
      `<p>${e(__('Este registro anterior conserva las referencias, sin descripciones. Consulte la vista operativa correspondiente.'))}</p>`)+
      `<p role="status">${items.length?offset+1:0}–${Math.min(offset+25,items.length)} / ${items.length||group.documents.length}</p><div class="hs-dialog-actions"><button type="button" class="btn btn-secondary" data-hs-pending-page="previous" ${offset?'':'disabled'}>${e(__('Anterior'))}</button><button type="button" class="btn btn-secondary" data-hs-pending-page="next" ${offset+25<items.length?'':'disabled'}>${e(__('Siguiente'))}</button>${page?`<a class="btn btn-secondary" data-hs-pending-target href="/app/${page}">${e(pages[page])}</a>`:''}${group.type==='Diferencias entre PMS y ERPNext'&&this.allowed('report')?`<button type="button" class="btn btn-secondary" data-hs-pending-reconcile>${e(__('Abrir Conciliación'))}</button>`:''}</div>`;
    dialog=await this.dialog(__(group.type),[{fieldname:'pending',fieldtype:'HTML',options:html()}],async(_,d)=>d.hide(),__('Cerrar'),'large');
    dialog.$wrapper?.on('click','[data-hs-pending-page]',event=>{if(this.property!==property)return;offset=Math.max(0,Math.min(Math.max(0,Math.ceil(items.length/25)-1)*25,offset+(event.currentTarget.dataset.hsPendingPage==='next'?25:-25)));dialog.fields_dict.pending.$wrapper.html(html());});
    dialog.$wrapper?.on('click','[data-hs-pending-account]',event=>{const n=Number(event.currentTarget.dataset.hsPendingAccount);if(this.property===property&&Number.isInteger(n)&&items[n]?.stay&&(this.allowed('finance')||this.allowed('stay')))this.action_detail(items[n].stay);});
    dialog.$wrapper?.on('click','[data-hs-pending-reconcile]',()=>{if(this.property===property&&this.allowed('report'))this.action_report('Conciliación');});
    return dialog;
  };
  Desk.prototype.action_daily_close=async function(){
    if(!this.allowed('finance')){frappe.msgprint(__('Puede consultar los cierres guardados en el historial.'));return;}
    const result=await this.mutate("daily_close",{confirm:false}),key=frappe.utils.get_random(24);
    const dialog=await this.dialog(__("Cierre del día"),[{fieldname:"review",fieldtype:"HTML",options:this.close_summary_html(result.period,result.blockers,{live:true})}],async(v,d)=>{
      await this.mutate("daily_close",{confirm:true,review_acceptance:result.review_acceptance},key);d.hide();
    },__("Confirmar cierre"),"extra-large");
    if(result.blockers.length||!this.allowed("approve"))dialog.get_primary_btn().prop("disabled",true);
    dialog.$wrapper?.on('click','[data-hs-audit-review]',()=>this.show_audit_review(result.period.audit_review));
    this.bind_close_checks(dialog,result.blockers,true);
    return dialog;
  };
  Desk.prototype.action_view_close=async function(id){
    const close=(this.data.closes||[]).find(row=>row.name===id);
    if(!close){frappe.msgprint(__("Actualice la página para consultar el cierre"));return;}
    const period=JSON.parse(close.summary||"{}"),blockers=JSON.parse(close.blockers||"[]");
    return this.show_close_snapshot(period,blockers,__("Resumen conservado · {0}",[close.business_date]));
  };
  Desk.prototype.show_close_snapshot=async function(period,blockers,title){
    const dialog=await this.dialog(title,[{fieldname:"saved_close",fieldtype:"HTML",options:this.close_summary_html(period,blockers)}],async(v,d)=>d.hide(),__("Cerrar"),"extra-large");
    dialog.$wrapper?.on('click','[data-hs-audit-review]',()=>this.show_audit_review(period.audit_review));
    this.bind_close_checks(dialog,blockers);
    return dialog;
  };
})();
