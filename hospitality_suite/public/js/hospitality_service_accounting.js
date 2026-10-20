/* Accounting choices stay scoped to the property and use native account names. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  const fields=["income_account","expense_account","cost_center"],labels={income_account:__("Cuenta de ingresos"),expense_account:__("Cuenta de gastos"),cost_center:__("Centro de costo")};
  const render=Desk.prototype.render_setup;
  Desk.prototype.render_setup=function(el){render.call(this,el);el.find(".hs-shortcuts").append(this.button("service_accounting",__("18. Contabilidad por servicio")));};
  Desk.prototype.action_service_accounting=async function(){
    const config=await this.call("service_accounting_configuration",{property_name:this.property}),key=frappe.utils.get_random(24);
    const accountField=(field,extra={})=>({fieldname:field,label:labels[field],fieldtype:"Link",options:field==="cost_center"?"Cost Center":"Account",
      get_query:()=>({filters:{company:config.company,is_group:0,disabled:0,...(field==="cost_center"?{}:{root_type:field==="income_account"?"Income":"Expense"})}}),...extra});
    return this.dialog(__("Contabilidad por establecimiento y servicio"),[
      {fieldname:"help",fieldtype:"HTML",options:`<p>${e(__("Cada servicio puede usar sus propias cuentas y centro de costo. Si deja un campo vacío, se usa el valor del establecimiento y después el predeterminado de ERPNext. Las notas de crédito conservan la contabilidad de su factura original."))}</p>`},
      {fieldname:"current",fieldtype:"HTML",options:config.services.length?this.table([__("Servicio configurado"),...fields.map(field=>labels[field])],config.services.map(row=>[e(row.item_name||row.item),...fields.map(field=>e(row[field]||config.defaults[field]||__("Predeterminado de ERPNext")))])):""},
      {fieldname:"defaults_section",label:__("Valores del establecimiento"),fieldtype:"Section Break"},
      ...fields.map(field=>accountField(field,{default:config.defaults[field]})),
      {fieldname:"services_section",label:__("Excepciones por artículo o servicio"),fieldtype:"Section Break"},
      {fieldname:"services",fieldtype:"Table",label:__("Servicios"),in_place_edit:true,data:config.services,
        fields:[{fieldname:"item",label:__("Artículo o servicio"),fieldtype:"Link",options:"Item",reqd:1,in_list_view:1,
          get_query:()=>({filters:{is_fixed_asset:0}})},...fields.map(field=>accountField(field,{in_list_view:1}))]},
    ],async(values,dialog)=>{
      const data={modified:config.modified,defaults:Object.fromEntries(fields.map(field=>[field,values[field]||null])),
        services:(values.services||[]).map(row=>Object.fromEntries(["item",...fields].map(field=>[field,row[field]||null])))};
      await this.mutate("service_accounting",data,key);dialog.hide();
    },__("Guardar contabilidad"));
  };
})();
