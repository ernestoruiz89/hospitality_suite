/* Reuse Item and Item Price; settings show names and the effective sale price. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  const render=Desk.prototype.render_setup;
  Desk.prototype.render_setup=function(el){render.call(this,el);el.find(".hs-shortcuts").append(this.button("service_items",__("17. Artículos y servicios")));};
  Desk.prototype.action_service_items=async function(){
    const config=await this.call("service_configuration",{property_name:this.property}),key=frappe.utils.get_random(24);
    const summary=this.table([__("Uso"),__("Artículo actual")],config.mappings.map(row=>[e(row.label),e(row.item_name||__("Sin configurar"))]));
    const fields=[{fieldname:"current_items",fieldtype:"HTML",options:summary},
      ...config.mappings.map(row=>({fieldname:row.field,label:row.label,fieldtype:"Link",options:"Item",default:config.values[row.field],get_query:()=>({filters:{disabled:0,is_sales_item:1,is_stock_item:0,is_fixed_asset:0}})})),
      {fieldname:"price_list",label:__("Lista de precios de servicios"),fieldtype:"Link",options:"Price List",default:config.values.price_list},
      {fieldname:"service_help",fieldtype:"HTML",options:`<p>${e(__("Alimentación, minibar, lavandería y otros servicios utilizan los artículos y precios de venta vigentes de ERPNext. Los artículos con inventario generan su entrega; los servicios sin inventario no descuentan existencias."))}</p><p>${e(__("Alojamiento y horas adicionales toman el importe de la tarifa aceptada. La lista de precios se utiliza para los consumos."))}</p><p>${e(__("Para un artículo distinto de horas adicionales, seleccione una unidad que admita fracciones de hora."))}</p>`},
      this.item_field(__("Consultar precio de un servicio"),"sale",{reqd:0}),{fieldname:"service_info",fieldtype:"HTML",options:""}];
    const d=await this.dialog(__("Artículos y servicios"),fields,async(values,active)=>{
      const data=Object.fromEntries(["lodging_item","extra_hour_item","timing_item","price_list"].map(field=>[field,values[field]||null]));
      await this.call("save_setup",{property_name:this.property,section:"property",data:JSON.stringify(data),request_key:key,expected_modified:config.modified});
      active.hide();await this.load();
    });
    let revision=0;
    d.fields_dict.item.df.onchange=async()=>{
      const version=++revision,item=d.get_value("item");
      if(!item){d.fields_dict.service_info.$wrapper.empty();return;}
      d.fields_dict.service_info.$wrapper.text(__("Consultando precio vigente…"));
      try{
        const info=await this.call("service_configuration",{property_name:this.property,item});
        if(version!==revision||!d.$wrapper.is(":visible"))return;
        const row=info.service,status=row.status==="Priced"?this.amount(row.rate,info.currency):row.status==="Missing"?__("Sin precio vigente"):__("Hay precios vigentes superpuestos; revise la lista");
        d.fields_dict.service_info.$wrapper.html(`<p><strong>${e(row.item_name)}</strong> · ${e(status)}</p><p>${e(info.price_list||__("Sin lista de precios"))} · ${e(row.is_stock_item?__("Entrega con inventario"):__("Servicio sin inventario"))}</p><p>${e(__("Precio general en la unidad de inventario; un precio específico del pagador puede prevalecer. La consulta usa la lista guardada. Guarde un cambio de lista y vuelva a abrir para consultar sus precios."))}</p>`);
      }catch(error){if(version===revision)d.fields_dict.service_info.$wrapper.text(__("No se pudo consultar el precio. Vuelva a seleccionar el servicio."));}
    };
    d.$wrapper.on("hidden.bs.modal.hsServiceItems",()=>revision++);
    return d;
  };
})();
