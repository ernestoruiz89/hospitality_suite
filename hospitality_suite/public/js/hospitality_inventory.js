/* Keep location queries scoped to the current Page and show service actions by state. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??''));
  const classifications={Merchandise:__('Mercancía para venta'),Cleaning:__('Consumible de limpieza'),Linen:__('Ropa de cama'),Parts:__('Repuesto'),Asset:__('Activo fijo')};
  const services=Desk.prototype.render_services;
  Desk.prototype.render_services=function(el){
    services.call(this,el);
    const warehouses=this.data.warehouses||[],property=this.property;
    const section=$('<section class="hs-section"></section>').appendTo(el);
    const view={property,section,request:0,warehouse:this.data.default_warehouse||warehouses[0]?.name};
    this._inventoryView=view;
    section.html(`<h2>${e(__('Existencias por ubicación'))}</h2>`+(warehouses.length?
      `<label class="hs-stock-location">${e(__('Almacén'))}<select class="form-control hs-stock-warehouse" aria-label="${e(__('Almacén de existencias'))}">${warehouses.map(row=>`<option value="${e(row.name)}" ${row.name===view.warehouse?'selected':''}>${e(row.warehouse_name)}</option>`).join('')}</select></label>`:'')+
      '<div class="hs-inventory-results" data-hs-inventory-results aria-live="polite"></div>');
    section.find('.hs-stock-warehouse').on('change',event=>{view.warehouse=event.target.value;this.load_inventory_status(view);});
    section.on('click','[data-hs-inventory-retry]',()=>this.load_inventory_status(view));
    this.load_inventory_status(view);
  };
  Desk.prototype.load_inventory_status=async function(view){
    const request=++view.request,warehouse=view.warehouse,property=view.property;
    const current=()=>this._inventoryView===view&&this.property===property&&view.request===request&&view.warehouse===warehouse;
    const results=view.section.find('[data-hs-inventory-results]');
    if(!warehouse){results.html(`<p>${e(__('Configure un almacén para consultar existencias.'))}</p>`);return;}
    results.attr('aria-busy','true').html(`<p role="status">${e(__('Consultando existencias…'))}</p>`);
    try{
      const data=await this.call('inventory_status',{property_name:property,warehouse_name:warehouse});
      if(!current())return;
      if(data.warehouse!==warehouse)throw Error('Inventory context mismatch');
      const rows=data.items||[];
      results.html(rows.length?this.table([__('Artículo'),__('Clasificación'),__('Disponible'),__('Mínimo'),__('Cantidad a reponer'),__('Alerta')],rows.map(row=>[
        e(row.item_name),e(classifications[row.purpose]||row.purpose),e(row.stock_managed===false?__('Registro de activos'):row.actual_qty),
        e(row.minimum??__('Sin configurar')),e(row.reorder_quantity??'—'),row.needs_restock?e(__('Reponer')):'—'
      ])):`<p>${e(__('No hay existencias ni mínimos configurados en este almacén.'))}</p>`);
    }catch{
      if(!current())return;
      results.html(`<p role="alert">${e(__('No se pudieron consultar las existencias de esta ubicación.'))}</p><button type="button" class="btn btn-secondary" data-hs-inventory-retry>${e(__('Reintentar consulta'))}</button>`);
    }finally{if(current())results.attr('aria-busy','false');}
  };
  Desk.prototype.action_service_status=async function(id){
    const service=(this.data.services||[]).find(row=>row.name===id);
    if(!service){frappe.msgprint(__('Actualice la página para consultar el servicio.'));return;}
    if(service.status==='Delivered'&&!this.allowed('approve')){frappe.msgprint(__('La devolución requiere autorización de gerencia o administración.'));return;}
    if(!service.stay)return this.action_return_direct_sale(id);
    const transitions={Requested:['In Progress','Delivered','Cancelled'],'In Progress':['Delivered','Cancelled'],Delivered:['Returned']};
    const options=transitions[service.status];
    if(!options){frappe.msgprint(__('Este servicio ya terminó; no tiene acciones pendientes.'));return;}
    const labels={'In Progress':__('En preparación'),'Delivered':__('Entregado'),'Cancelled':__('Cancelado'),'Returned':__('Devuelto')};
    const actions={'In Progress':__('Iniciar preparación'),Delivered:__('Confirmar entrega'),Cancelled:__('Cancelar solicitud'),Returned:__('Confirmar devolución')};
    const key=frappe.utils.get_random(24),dialog=await this.dialog(__('Actualizar servicio'),[
      {fieldname:'context',fieldtype:'HTML',options:`<p><strong>${e(this.itemName(service.item))}</strong> · ${e(__('Cantidad'))}: ${e(service.quantity)}</p>`},
      {fieldname:'status',label:__('Acción del servicio'),fieldtype:'Select',reqd:1,default:options[0],options:options.map(value=>({value,label:labels[value]}))},
      {fieldname:'reason',label:__('Motivo de devolución'),fieldtype:'Small Text'}
    ],async(values,d)=>{await this.mutate('update_service',{...values,service:id,modified:service.modified},key);d.hide();},actions[options[0]]);
    const update=()=>{const status=dialog.get_value('status');dialog.set_df_property('reason','hidden',!['Cancelled','Returned'].includes(status));dialog.set_df_property('reason','reqd',status==='Returned');dialog.set_df_property('reason','label',status==='Returned'?__('Motivo de devolución'):__('Observaciones de cancelación'));dialog.get_primary_btn().text(actions[status]);};
    dialog.fields_dict.status.df.onchange=update;update();return dialog;
  };
})();
