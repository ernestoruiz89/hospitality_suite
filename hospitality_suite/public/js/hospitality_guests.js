/* One guest identity across corrections and uncertain network responses. */
(() => {
  const suite=window.hospitality_suite,Desk=suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  const keys=["full_name","email","phone","identity_type","identity_number","nationality","address_line1","city","country"];
  const clean=values=>Object.fromEntries(keys.map(key=>[key,values[key]??""]));
  const copy=value=>JSON.parse(JSON.stringify(value));
  const business=error=>Boolean(error?._server_messages||error?._error_message||error?.responseJSON?._server_messages||error?.responseJSON?._error_message);
  class GuestSession{
    constructor(property,send,info=null){Object.assign(this,{property,send,guest:info?.guest,modified:info?.modified,related:copy(info?.related_versions||{}),createdDuringFlow:!info});}
    async settle(){
      if(!this.pending)return null;
      const pending=this.pending;
      try{
        const result=await this.send(pending.method,pending.args);
        if(!result?.guest||!result.modified)throw Error("Incomplete guest response");
        this.guest=result.guest;this.modified=result.modified;this.related=copy(result.related_versions||{});this.pending=null;
        return {fingerprint:pending.fingerprint,result};
      }catch(error){if(business(error))this.pending=null;throw error;}
    }
    async save(values,reason=""){
      const data=clean(values),fingerprint=JSON.stringify({data,reason}),settled=await this.settle();
      if(settled?.fingerprint===fingerprint)return settled.result;
      const args={property_name:this.property,data:JSON.stringify(data),request_key:frappe.utils.get_random(24)};
      if(this.guest)Object.assign(args,{name:this.guest,modified:this.modified,related_versions:JSON.stringify(this.related),reason:reason||(this.createdDuringFlow?__("Corrección durante el registro antes de cerrar el formulario"):"")});
      this.pending={method:this.guest?"update_guest":"create_guest",args:copy(args),fingerprint};
      return (await this.settle()).result;
    }
  }
  suite.GuestSession=GuestSession;
  Desk.prototype.guest_policy_text=function(required=this.prop.guest_id_required){return required?
    __("Este establecimiento requiere identificación. Complete el número; los demás datos adicionales son opcionales."):
    __("Este establecimiento no exige identificación. Registre únicamente los datos necesarios.");};
  const button=Desk.prototype.button;
  Desk.prototype.button=function(action,...args){return action==="guest_edit"&&!this.allowed("guest")?"":button.call(this,action,...args);};
  Desk.prototype.action_guest=function(){this.guestRequestSequence=(this.guestRequestSequence||0)+1;return this.guest_editor(null,this.property);};
  Desk.prototype.action_guest_edit=async function(name){
    if(!this.allowed("guest"))return;
    const property=this.property,token=this.guestRequestSequence=(this.guestRequestSequence||0)+1;
    const info=await this.call("guest_detail",{name});
    if(this.property!==property||this.guestRequestSequence!==token||info.property!==property)return;
    return this.guest_editor(info,property);
  };
  Desk.prototype.guest_editor=async function(info,property){
    if(!this.allowed("guest")||this.property!==property)return;
    const required=info?info.guest_id_required:Boolean(this.prop.guest_id_required),values=info?.values||{};
    const f=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),fieldtype,default:values[fieldname]||"",...extra});
    const same=()=>{if(this.property!==property)throw Error("Property changed");};
    const session=new GuestSession(property,(method,args)=>{same();return this.call(method,args);},info);
    const fields=[f("guest_policy",__("Política de identificación"),"HTML",{options:`<p role="note" class="hs-guest-policy">${e(this.guest_policy_text(required))}</p>`}),
      f("full_name",__("Nombre completo"),"Data",{reqd:1}),f("phone",__("Teléfono (opcional)")),f("email",__("Correo (opcional)"),"Data",{options:"Email"}),
      f("identity_type",__("Tipo de identificación (opcional)")),f("identity_number",required?__("Número de identificación"):__("Número de identificación (opcional)"),"Data",{reqd:required?1:0}),
      f("nationality",__("Nacionalidad (opcional)")),f("address_line1",__("Dirección (opcional)")),f("city",__("Ciudad")),f("country",__("País"),"Link",{options:"Country"})];
    if(info){
      fields.push(f("payer_summary",__("Cliente vinculado"),"HTML",{options:`<p>${e(__("Cliente vinculado"))}: <strong>${e(info.customer_label)}</strong></p>`}),
        f("reason",__("Motivo de la corrección"),"Small Text",{reqd:1,description:__("Indique la razón del cambio, sin copiar identificaciones.")}));
      if(info.shared_contact||info.shared_address)fields.push(f("shared_notice",__("Datos compartidos"),"HTML",{options:`<p>${e(__("Los datos compartidos se conservarán para las otras personas. Esta corrección guardará los datos propios de esta ficha."))}</p>`}));
    }
    return this.dialog(info?__("Actualizar huésped"):__("Registrar huésped"),fields,async(v,d)=>{
      same();await session.save(v,v.reason||"");d.hide();if(this.property===property)await this.load();
    },info?__("Guardar cambios"):__("Registrar huésped"));
  };
})();
