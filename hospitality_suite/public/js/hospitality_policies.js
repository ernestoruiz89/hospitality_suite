/* Receipt policy settings and choices; the server authorizes every posting. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const field=(fieldname,label,extra={})=>({fieldname,label:__(label),fieldtype:"Select",reqd:1,...extra});
  const labels={Manual:__("Manual, según el rol de caja"),Approval:__("Con autorización de gerencia"),Disabled:__("No admitir nuevos movimientos")};
  const render=Desk.prototype.render_setup;
  Desk.prototype.render_setup=function(el){
    render.call(this,el);
    el.find(".hs-shortcuts").append(this.button("payment_policies",__("16. Anticipos y garantías")));
  };
  Desk.prototype.action_payment_policies=async function(){
    const config=await this.call("configuration",{property_name:this.property}),key=frappe.utils.get_random(24);
    const options=Object.entries(labels).map(([value,label])=>({value,label}));
    const dialog=await this.dialog(__("Políticas de anticipos y garantías"),[
      field("advance_policy",__("Nuevos anticipos"),{options,default:config.advance_policy||"Manual"}),
      field("guarantee_policy",__("Nuevas garantías"),{options,default:config.guarantee_policy||"Manual"}),
      {fieldname:"policy_help",fieldtype:"HTML",options:`<p>${frappe.utils.escape_html(__("Los importes se revisan en caja. La autorización de gerencia exige un usuario con permiso de aprobación."))}</p><p>${frappe.utils.escape_html(__("Desactivar nuevos movimientos conserva la devolución y aplicación de fondos anteriores. Las devoluciones y aplicaciones de garantías siguen requiriendo aprobación."))}</p>`}
    ],async(values,d)=>{
      await this.call("save_setup",{property_name:this.property,section:"property",data:JSON.stringify({advance_policy:values.advance_policy,guarantee_policy:values.guarantee_policy}),request_key:key,expected_modified:config.modified});
      d.hide();await this.load();
    });
    if(!this.allowed("approve"))dialog.get_primary_btn().prop("disabled",true);
    return dialog;
  };
  const dialog=Desk.prototype.dialog;
  Desk.prototype.dialog=async function(title,fields,...args){
    const kind=fields.find(df=>df.fieldname==="kind"&&df.fieldtype==="Select"&&Array.isArray(df.options));
    if(kind){
      const policies=this.data.payment_policies||{};
      kind.options=kind.options.flatMap(option=>{
        const value=typeof option==="string"?option:option.value,rule=policies[value];
        if(!["Advance","Guarantee"].includes(value))return [option];
        if(rule==="Disabled")return [];
        if(rule==="Approval"&&!this.allowed("approve")){
          const row=typeof option==="string"?{value,label:value}:option;
          return [{...row,label:__("{0} · requiere gerencia",[row.label]),disabled:true}];
        }
        return [option];
      });
    }
    return dialog.call(this,title,fields,...args);
  };
})();
