/* Historical values are explicit fields; never render arbitrary JSON or provider payloads. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  let sequence=0;
  Desk.prototype.action_view_audit=async function(name){
    const property=this.property,record=await this.call('audit_detail',{property_name:property,name});
    if(this.property!==property)return;
    const parent=`hs-audit-record-${++sequence}`;
    const table=rows=>this.table([__('Dato'),__('Antes'),__('Después')],rows.map(row=>[e(row.label),e(row.before),e(row.after)]));
    const changed=record.values.filter(row=>row.changed),same=record.values.filter(row=>!row.changed);
    const important=['status','docstatus','title','room','amount','grand_total','currency','starts_at','ends_at','expected_amount','counted_amount','difference'];
    const primary=changed.filter(row=>important.includes(row.field)),others=changed.filter(row=>!important.includes(row.field));
    let values=record.historical_values_available?(primary.length?table(primary):''):
      `<p>${e(__('Este registro no conserva el desglose de valores. Consulte el documento de origen y su historial.'))}</p>`;
    if(record.values_document)values=`<p>${e(__('Valores registrados de'))}: ${e(record.values_document)}</p>`+values;
    if(others.length)values+=`<details><summary>${e(__('Otros valores registrados ({0})',[others.length]))}</summary>${table(others)}</details>`;
    if(same.length)values+=`<details><summary>${e(__('Datos que se conservaron ({0})',[same.length]))}</summary>${table(same)}</details>`;
    const dialog=await this.dialog(record.action,[
      {fieldname:'operation_tab',fieldtype:'Tab Break',label:__('Operación'),parent,hidden:0},
      {fieldname:'operation',fieldtype:'HTML',options:`<p><strong>${e(record.action)}</strong></p>`+this.table([__('Dato'),__('Información')],[
        [__('Realizado por'),e(record.actor)],[__('Momento'),e(record.occurred_at)],[__('Fecha operativa'),e(record.business_date)],
        [e(record.document_type),e(record.document)],[__('Motivo'),e(record.reason||__('No se registró un motivo adicional.'))]])+
        (record.close_snapshot?`<button type="button" class="btn btn-secondary" data-hs-audit-close>${e(__('Ver resumen de esta ejecución'))}</button>`:'')},
      {fieldname:'values_tab',fieldtype:'Tab Break',label:__('Valores registrados'),parent,hidden:0},
      {fieldname:'values',fieldtype:'HTML',options:values||`<p>${e(__('No cambiaron los valores registrados.'))}</p>`}
    ],async(_,dialog)=>dialog.hide(),__('Cerrar'),'large');
    const sync=()=>{for(const tab of dialog.tabs||[])tab.tab_link.find('.nav-link').attr('aria-selected',String(tab.is_active()&&!tab.hidden));};
    for(const tab of dialog.tabs||[])tab.tab_link.find('.nav-link').on('click.hsAuditSelection',sync);
    sync();
    if(record.close_snapshot)dialog.$wrapper.on('click','[data-hs-audit-close]',()=>this.show_close_snapshot(record.close_snapshot,record.close_blockers||[],record.action));
    return dialog;
  };

  Desk.prototype.show_audit_review=async function(review){
    const rows=review?.rows||[];let offset=0,dialog;
    const html=()=>`<p>${e(__('Fecha operativa'))}: ${e(review.business_date)} · ${e(__('Registros para revisar'))}: ${rows.length}</p><p class="hs-note">${e(__('Un cambio puede tener varios registros vinculados. Estos conteos no suman importes.'))}</p>`+
      (rows.length?this.table([__('Momento'),__('Acción'),__('Registrado por'),__('Documento'),__('Motivo'),__('Detalle')],rows.slice(offset,offset+25).map(row=>[
        e(row.occurred_at),e(row.action),e(row.actor),e(row.document),e(row.reason||'—'),`<button type="button" class="btn btn-secondary" data-hs-audit="${e(row.name)}">${e(__('Ver cambio'))}</button>`])):this.empty(__('Sin registros excepcionales en esta fecha.')))+
      `<div class="hs-dialog-actions"><button type="button" class="btn btn-secondary" data-audit-page="previous" ${offset===0?'disabled':''}>${e(__('Anterior'))}</button><span role="status">${rows.length?offset+1:0}–${Math.min(offset+25,rows.length)} ${e(__('de'))} ${rows.length}</span><button type="button" class="btn btn-secondary" data-audit-page="next" ${offset+25>=rows.length?'disabled':''}>${e(__('Siguiente'))}</button></div>`;
    dialog=await this.dialog(__('Registros para revisar'),[{fieldname:'records',fieldtype:'HTML',options:html()}],async(_,d)=>d.hide(),__('Cerrar'),'extra-large');
    dialog.$wrapper.on('click','[data-hs-audit]',event=>this.action_view_audit(event.currentTarget.dataset.hsAudit));
    dialog.$wrapper.on('click','[data-audit-page]',event=>{offset=Math.max(0,offset+(event.currentTarget.dataset.auditPage==='next'?25:-25));dialog.set_df_property('records','options',html());});
    return dialog;
  };
})();
