/* Partial reservations stay outside capacity until a current quote is accepted. */
(() => {
  const suite=window.hospitality_suite,Desk=suite.Desk;
  const esc=value=>frappe.utils.escape_html(String(value??""));
  const f=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),fieldtype:fieldtype==="Datetime"?"Data":fieldtype,_hsDateTime:fieldtype==="Datetime",...extra});
  const pick=(name,label,rows,key,required=false)=>f(name,label,"Select",{reqd:required,_hsDataOptions:true,options:[{value:"",label:__("Seleccione…")},...rows.map(row=>({value:row.name,label:row[key]||row.name}))]});
  const businessError=error=>Boolean(error?._server_messages||error?._error_message||error?.responseJSON?._server_messages||error?.responseJSON?._error_message);
  const copy=value=>JSON.parse(JSON.stringify(value));
  const valueKeys=["mode","hold","guest","customer","starts_at","ends_at","channel","instructions"];
  const rowKeys=["category","room","rate","people","extra_beds"];
  const clean=values=>({...Object.fromEntries(valueKeys.map(key=>[key,values[key]??null])),rooms:(values.rooms||[]).map(row=>Object.fromEntries(rowKeys.map(key=>[key,row[key]??null])))});
  // A lost response must be resolved with the original payload/key, including
  // when the operator has since changed fields. The second save reuses the ID.
  class DraftSession {
    constructor(property,send,booking=null,modified=null){Object.assign(this,{property,send,booking,modified});}
    async settle(){
      if(!this.pending)return null;
      const pending=this.pending;
      try{
        const result=await this.send(pending.data,pending.key,this.property);
        this.booking=result.booking;this.modified=result.modified;this.pending=null;
        return pending.fingerprint;
      }catch(error){if(businessError(error))this.pending=null;throw error;}
    }
    async save(values){
      const data=clean(values),fingerprint=JSON.stringify(data);
      if(await this.settle()===fingerprint)return {booking:this.booking,modified:this.modified};
      this.pending={data:{...(this.booking?{booking:this.booking,modified:this.modified}:{}),values:copy(data)},key:frappe.utils.get_random(24),fingerprint};
      await this.settle();return {booking:this.booking,modified:this.modified};
    }
    review(values){return {booking:this.booking,modified:this.modified,values:clean(values)};}
  }
  suite.DraftSession=DraftSession;
  // Browser datetime-local fields cannot express an explicit DST fold. Keep
  // the saved offset when the displayed wall time has not been edited.
  const wall=value=>String(value||"").slice(0,19).replace("T"," ");
  const comparable=value=>{const text=wall(value);return text.length===16?text+":00":text;};
  const originalDate=(value,saved)=>saved&&comparable(value)===comparable(saved)?saved:value||null;
  suite.draft_dates=(values,saved)=>({...values,starts_at:originalDate(values.starts_at,saved.starts_at),ends_at:originalDate(values.ends_at,saved.ends_at)});
  const originalReservation=Desk.prototype.reservation;
  Desk.prototype.reservation=function(room,walk=false,prefill=null){return walk?originalReservation.call(this,room,true):this.booking_draft_editor(null,room,prefill);};
  const originalBooking=Desk.prototype.action_booking;
  Desk.prototype.action_booking=async function(id){
    const b=(this.data.bookings||[]).find(row=>row.name===id);
    if(b?.status!=="Draft")return originalBooking.call(this,id);
    if(!this.allowed("reserve"))return;
    const property=this.property,info=await this.call("booking_detail",{name:id});
    if(this.property===property)return this.booking_draft_editor(info);
  };
  Desk.prototype.booking_draft_editor=async function(info,roomId,prefill=null){
    if(!this.allowed("reserve"))return;
    if(prefill&&prefill.property!==this.property)return;
    const property=this.property,prop={...this.prop},existing=info?.draft,room=this.data.rooms.find(row=>row.name===roomId);
    const now=(this.data.property_now||this.data.server_time).slice(0,19).replace("T"," ");
    const values=existing||{mode:prop.mode==="Motel"?"Motel":"Hotel",starts_at:prefill?.starts_at||now,ends_at:prefill?.ends_at||moment(now).add(prop.mode==="Motel"?3:24,"hours").format("YYYY-MM-DD HH:mm:ss"),channel:"Recepción",rooms:prefill?clean({rooms:prefill.rooms}).rooms:[{category:room?.category,room:roomId||"",people:1,extra_beds:0}]};
    const send=(data,key,p)=>this.call("execute",{property_name:p,action:"save_booking_draft",request_key:key,data:JSON.stringify(data)});
    const session=new DraftSession(property,send,info?.booking.name,info?.booking.modified);
    const scope=()=>({filters:{property}});
    const fields=[f("draft_help",__("Estado del borrador"),"HTML",{options:`<p class="hs-draft-status" role="status">${esc(__(existing?"Borrador guardado. Puede completar datos y revisar el precio.":__("Puede guardar datos incompletos como borrador.")))} ${esc(__("El borrador no ocupa cupo ni fija precio."))}</p>`}),
      {...pick("guest",__("Huésped principal (puede elegirse al ingresar)"),this.data.guests,"full_name"),default:values.guest||""},
      {...pick("customer",__("Cliente que paga"),this.data.customers,"customer_name",true),default:values.customer||""},
      f("starts_at",__("Entrada ({0})",[prop.time_zone]),"Datetime",{reqd:1,default:wall(values.starts_at)}),
      f("ends_at",__("Salida prevista"),"Datetime",{reqd:1,default:wall(values.ends_at)}),
      f("mode",__("Modalidad"),"Select",{reqd:1,options:prop.mode==="Mixed"?["Hotel","Motel"]:[prop.mode],default:values.mode}),
      f("rooms",__("Habitaciones solicitadas"),"Table",{reqd:1,in_place_edit:true,data:copy(values.rooms||[]),fields:[
        f("category",__("Categoría"),"Link",{options:"HS Category",reqd:1,in_list_view:1,get_query:scope}),
        f("room",__("Habitación (opcional)"),"Link",{options:"HS Room",in_list_view:1,get_query:()=>({filters:{property,active:1}})}),
        f("people",__("Personas"),"Int",{reqd:1,default:1,in_list_view:1}),
        f("extra_beds",__("Camas adicionales"),"Int",{default:0}),
        f("rate",__("Tarifa preferida (opcional)"),"Link",{options:"HS Rate",get_query:scope})]}),
      f("channel",__("Canal"),"Data",{default:values.channel||"Recepción"}),
      f("hold",__("Retener temporalmente al aceptar el precio"),"Check",{default:values.hold||0,description:__("Guardar el borrador no inicia la retención.")}),
      f("instructions",__("Solicitudes especiales"),"Small Text",{default:values.instructions||""})];
    const sameProperty=()=>{if(this.property!==property)throw new Error("Property changed");};
    const collected=v=>suite.draft_dates(clean(v),values);
    const refresh=async()=>{if(this.property===property)await this.load();};
    const lock=(d,on)=>{
      if(on){d._hsDraftDisabled=d.$body.find("input,select,textarea,button").filter(":enabled");d._hsDraftDisabled.prop("disabled",true);}
      else d._hsDraftDisabled?.prop("disabled",false);
      d.get_secondary_btn().prop("disabled",on);
    };
    let dialog;
    dialog=await this.dialog(existing?__("Retomar borrador"):__("Nueva reserva"),fields,async(v,d)=>{
      sameProperty();lock(d,true);
      try{
        await session.settle();
        const request=session.booking?session.review(collected(v)):collected(v);
        const q=await this.call("preview",{property_name:property,action:session.booking?"confirm_booking_draft":"reserve",data:JSON.stringify(request)});
        sameProperty();
        const key=frappe.utils.get_random(24),held=Boolean(v.hold),lines=q.lines.map(line=>`<li>${esc(line.explanation.join("; "))}</li>`).join("");
        await this.dialog(__("Revisar cotización"),[f("summary",__("Precio y disponibilidad"),"HTML",{options:`<p>${esc(held?__("Al aceptar se retendrá el cupo temporalmente."):__("Al aceptar se confirmará la reserva."))}</p><h2>${esc(this.amount(q.amount,q.currency))}</h2><ul>${lines}</ul><p>${esc(__("Impuestos y saldo se calculan al facturar."))}</p>`})],async(x,c)=>{
          sameProperty();
          const action=session.booking?"confirm_booking_draft":"reserve";
          const data={...request,...(session.booking?{draft_acceptance:q.draft_acceptance}:{acceptance:q.acceptance})};
          await this.mutate(action,data,key);c.hide();d.hide();
        },held?__("Aceptar retención temporal"):__("Confirmar reserva"));
      }finally{lock(d,false);}
    },__("Revisar precio"));
    dialog.set_secondary_action_label(__("Guardar borrador"));
    dialog.set_secondary_action(()=>dialog._hsSubmit({validate:false,handler:async(v,d)=>{
      sameProperty();lock(d,true);
      try{
        await session.save(collected(v));
        d.$wrapper.find(".hs-draft-status").text(__("Borrador guardado. No ocupa cupo ni fija precio. Puede cerrar y retomarlo en Reservas."));
        d.set_title(__("Retomar borrador"));
        frappe.show_alert({message:__("Borrador guardado"),indicator:"green"});
        await refresh();
      }finally{lock(d,false);}
    }}));
    if(existing){
      const discard=$("<button type='button' class='btn btn-link hs-discard-draft'></button>").text(__("Descartar borrador"));
      dialog.$body.append(discard);
      discard.on("click",()=>{
        if(dialog._hsBusy)return;
        const key=frappe.utils.get_random(24);
        return this.dialog(__("Descartar borrador"),[f("reason",__("Motivo"),"Data",{reqd:1,description:__("Conserva el registro sin generar penalización ni factura.")})],async(v,c)=>{
          sameProperty();await session.settle();
          await this.mutate("discard_booking_draft",{booking:session.booking,modified:session.modified,reason:v.reason},key);
          c.hide();dialog.hide();
        },__("Descartar borrador"),"small");
      });
    }
    return dialog;
  };
})();
