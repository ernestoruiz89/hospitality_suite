/* Quantity and physical room options are different answers to the same query. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const e=value=>frappe.utils.escape_html(String(value??""));
  const field=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),fieldtype,...extra});
  const unavailable=new Set(["Reserved","Occupied","Blocked","Buffer","Inactive","Category Full"]);
  const state=status=>status==="Available"?{css:"is-available",text:__("Disponible"),icon:"✓"}:
    unavailable.has(status)?{css:"is-unavailable",text:__("No disponible"),icon:"×"}:{css:"is-unknown",text:__("Por revisar"),icon:"?"};
  const badge=status=>`<span class="hs-room-availability"><span aria-hidden="true">${status.icon}</span> ${e(status.text)}</span>`;
  Desk.prototype.availability_states=function(result){
    const rows=result.room_states||[];if(!rows.length)return "";
    const cleaning={Clean:__("Limpia"),Dirty:__("Sucia"),Cleaning:__("En limpieza"),Inspection:__("Pendiente de inspección")};
    return `<details class="hs-interval-states"><summary>${e(__("Estado de las habitaciones en estas fechas ({0})",[rows.length]))}</summary><p>${e(__("El estado corresponde al intervalo consultado. La limpieza se muestra como está ahora; debe verificarse antes de la entrada."))}</p><ul>${rows.map(row=>{
      const status=state(row.status);
      return `<li class="hs-room-state ${status.css}"><div class="hs-room-state-heading"><strong>${e(row.room_number)}</strong>${badge(status)}</div><span>${e(row.label||status.text)}</span><small>${e(__("Limpieza actual"))}: ${e(cleaning[row.cleaning_status]||__("Por revisar"))}</small></li>`;
    }).join("")}</ul></details>`;
  };
  Desk.prototype.availability_result=function(result){
    const headline=result.enough?
      (result.quantity===1?__("Hay cupo para 1 habitación"):__("Hay cupo para {0} habitaciones",[result.quantity])):
      (result.quantity===1?__("No alcanza el cupo para 1 habitación"):__("No alcanza el cupo para {0} habitaciones",[result.quantity]));
    const selectable=result.enough&&this.allowed("reserve");
    const rooms=(result.rooms||[]).map((room,index)=>`<li class="${selectable?"":"hs-room-option is-available"}">${selectable?`<button type="button" class="btn btn-default hs-available-room is-available" data-availability-room="${index}" aria-label="${e(__("Reservar habitación {0}",[room.room_number]))} · ${e(__("Disponible"))}"><strong>${e(room.room_number)}</strong>${badge(state("Available"))}</button>`:`<strong>${e(room.room_number)}</strong>${badge(state("Available"))}`}</li>`).join("");
    return `<section class="hs-availability-answer ${result.enough?"is-available":"is-unavailable"}"><h3>${e(headline)}</h3><p>${e(result.category_label)} · ${e(__("Personas por habitación: {0}",[result.people]))}</p><p>${e(this.date(result.starts_at))} → ${e(this.date(result.ends_at))}</p><p>${e(__("Cupo disponible: {0} · Habitaciones solicitadas: {1}",[result.available,result.quantity]))}</p>${result.needs_assignment_review?`<p class="hs-availability-warning">${e(__("Hay cupo por categoría, pero no hay suficientes habitaciones libres durante todo el intervalo. Recepción debe revisar la asignación física."))}</p>`:""}${result.available>0&&rooms?`<details><summary>${e(__("Ver opciones de habitación ({0})",[result.physical_available]))}</summary><p>${e(__("Puede elegir entre estas habitaciones, hasta el cupo disponible. La limpieza se verifica antes del ingreso."))}</p><ul>${rooms}</ul></details>`:""}${this.availability_states(result)}<small>${e(__("Esta consulta no reserva habitaciones. El cupo se vuelve a comprobar al confirmar una reserva."))}</small></section>`;
  };
  Desk.prototype.action_availability=async function(){
    const property=this.property,now=(this.data.property_now||this.data.server_time).slice(0,19).replace("T"," ");
    const end=moment(now).add(this.prop.mode==="Motel"?3:24,"hours").format("YYYY-MM-DD HH:mm:ss");
    const categories=this.data.categories,fields=[
      field("category",__("Categoría"),"Select",{reqd:1,_hsDataOptions:true,default:categories.length===1?categories[0].name:"",options:[{value:"",label:__("Seleccione…")},...categories.map(r=>({value:r.name,label:r.category_name}))]}),
      field("quantity",__("Cantidad de habitaciones"),"Int",{reqd:1,default:1,_hsBounds:{min:1,integer:true}}),
      field("people",__("Personas por habitación"),"Int",{reqd:1,default:1,_hsBounds:{min:1,integer:true}}),
      field("_availability_column","","Column Break"),
      field("starts_at",__("Entrada ({0})",[this.prop.time_zone]),"Data",{reqd:1,_hsDateTime:true,default:now}),
      field("ends_at",__("Salida prevista"),"Data",{reqd:1,_hsDateTime:true,default:end}),
      field("_availability_section","","Section Break"),
      field("_availability_result","","HTML",{options:`<p>${e(__("Elija las fechas y la cantidad que necesita; pulse Buscar disponibilidad."))}</p>`})];
    let sequence=0,shown=true,accepted=null,opening=false;
    const put=(dialog,html,busy=false)=>dialog.fields_dict._availability_result.$wrapper.attr({role:"status","aria-live":"polite","aria-busy":String(busy)}).html(html);
    const dialog=await this.dialog(__("Buscar disponibilidad"),fields,async(values,d)=>{
      if(this.property!==property){put(d,`<p>${e(__("El establecimiento cambió. Cierre esta ventana y abra una nueva consulta."))}</p>`);return;}
      accepted=null;
      const token=++sequence,current=()=>shown&&token===sequence&&this.property===property;
      put(d,`<p>${e(__("Consultando disponibilidad…"))}</p>`,true);
      try{
        const {category,quantity,people,starts_at,ends_at}=values;
        const result=await this.call("availability_search",{property_name:property,category,quantity,people,starts_at,ends_at});
        if(!current())return;
        if(result.property!==property)throw Error("Availability context mismatch");
        accepted=result;
        put(d,this.availability_result(result));
        d.fields_dict._availability_result.$wrapper[0]?.scrollIntoView({block:"nearest"});
      }catch(error){if(current())put(d,`<p role="alert">${e(__("No se pudo consultar. Revise los filtros y pulse Buscar disponibilidad para reintentar."))}</p>`);}
    },__("Buscar disponibilidad"),"large");
    dialog.$wrapper.addClass("hs-availability-dialog");
    dialog.$wrapper.on("input.hsAvailability change.hsAvailability","input,select",()=>{
      sequence++;accepted=null;
      put(dialog,`<p>${e(__("Datos cambiados. Pulse Buscar disponibilidad para actualizar el resultado."))}</p>`);
    });
    dialog.$wrapper.on("click.hsAvailabilityRoom","[data-availability-room]",async event=>{
      if(!shown||opening||this.property!==property||!accepted||!this.allowed("reserve"))return;
      const index=Number(event.currentTarget.dataset.availabilityRoom);
      if(!Number.isInteger(index)||index<0)return;
      const prefill=this.availability_booking_values(accepted,index);
      if(!prefill)return;
      opening=true;dialog.hide();
      try{await this.reservation(prefill.rooms[0].room,false,prefill);}
      catch(error){frappe.msgprint(__("No se pudo abrir la reserva. Vuelva a consultar la disponibilidad e intente nuevamente."));}
    });
    dialog.$wrapper.one("hide.bs.modal.hsAvailability",()=>{shown=false;sequence++;accepted=null;});
    return dialog;
  };
  Desk.prototype.availability_booking_values=function(result,index){
    const quantity=Number(result.quantity),people=Number(result.people),selected=result.rooms?.[index];
    if(!result.enough||result.property!==this.property||!selected||!Number.isInteger(quantity)||quantity<1||quantity>result.available||quantity>this.data.rooms.length||!Number.isInteger(people)||people<1)return null;
    const room=this.data.rooms.find(row=>row.name===selected.name&&row.category===result.category);
    if(!room||!result.starts_at||!result.ends_at||result.time_zone!==this.prop.time_zone)return null;
    const local=value=>moment.tz(value,this.data.system_timezone).tz(this.prop.time_zone).format("YYYY-MM-DDTHH:mm:ssZ");
    return {property:this.property,starts_at:local(result.starts_at),ends_at:local(result.ends_at),
      rooms:Array.from({length:quantity},(_,i)=>({category:result.category,room:i===0?room.name:"",people,extra_beds:0}))};
  };
})();
