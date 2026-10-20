/* Quantity and physical room options are different answers to the same query. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const e=value=>frappe.utils.escape_html(String(value??""));
  const field=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),fieldtype,...extra});
  Desk.prototype.availability_result=function(result){
    const headline=result.enough?
      (result.quantity===1?__("Hay cupo para 1 habitación"):__("Hay cupo para {0} habitaciones",[result.quantity])):
      (result.quantity===1?__("No alcanza el cupo para 1 habitación"):__("No alcanza el cupo para {0} habitaciones",[result.quantity]));
    const rooms=(result.rooms||[]).map(room=>`<li>${e(room.room_number)}</li>`).join("");
    return `<section class="hs-availability-answer ${result.enough?"is-available":"is-unavailable"}"><h3>${e(headline)}</h3><p>${e(result.category_label)} · ${e(__("Personas por habitación: {0}",[result.people]))}</p><p>${e(this.date(result.starts_at))} → ${e(this.date(result.ends_at))}</p><p>${e(__("Cupo disponible: {0} · Habitaciones solicitadas: {1}",[result.available,result.quantity]))}</p>${result.needs_assignment_review?`<p class="hs-availability-warning">${e(__("Hay cupo por categoría, pero no hay suficientes habitaciones libres durante todo el intervalo. Recepción debe revisar la asignación física."))}</p>`:""}${result.available>0&&rooms?`<details><summary>${e(__("Ver opciones de habitación ({0})",[result.physical_available]))}</summary><p>${e(__("Puede elegir entre estas habitaciones, hasta el cupo disponible. La limpieza se verifica antes del ingreso."))}</p><ul>${rooms}</ul></details>`:""}<small>${e(__("Esta consulta no reserva habitaciones. El cupo se vuelve a comprobar al confirmar una reserva."))}</small></section>`;
  };
  Desk.prototype.action_availability=async function(){
    const property=this.property,now=(this.data.property_now||this.data.server_time).slice(0,19).replace("T"," ");
    const end=moment(now).add(this.prop.mode==="Motel"?3:24,"hours").format("YYYY-MM-DD HH:mm:ss");
    const categories=this.data.categories,fields=[
      field("category",__("Categoría"),"Select",{reqd:1,_hsDataOptions:true,default:categories.length===1?categories[0].name:"",options:[{value:"",label:__("Seleccione…")},...categories.map(r=>({value:r.name,label:r.category_name}))]}),
      field("quantity",__("Cantidad de habitaciones"),"Int",{reqd:1,default:1}),
      field("people",__("Personas por habitación"),"Int",{reqd:1,default:1}),
      field("_availability_column","","Column Break"),
      field("starts_at",__("Entrada ({0})",[this.prop.time_zone]),"Data",{reqd:1,_hsDateTime:true,default:now}),
      field("ends_at",__("Salida prevista"),"Data",{reqd:1,_hsDateTime:true,default:end}),
      field("_availability_section","","Section Break"),
      field("_availability_result","","HTML",{options:`<p>${e(__("Elija las fechas y la cantidad que necesita; pulse Buscar disponibilidad."))}</p>`})];
    let sequence=0,shown=true;
    const put=(dialog,html,busy=false)=>dialog.fields_dict._availability_result.$wrapper.attr({role:"status","aria-live":"polite","aria-busy":String(busy)}).html(html);
    const dialog=await this.dialog(__("Buscar disponibilidad"),fields,async(values,d)=>{
      if(this.property!==property){put(d,`<p>${e(__("El establecimiento cambió. Cierre esta ventana y abra una nueva consulta."))}</p>`);return;}
      const token=++sequence,current=()=>shown&&token===sequence&&this.property===property;
      put(d,`<p>${e(__("Consultando disponibilidad…"))}</p>`,true);
      try{
        const {category,quantity,people,starts_at,ends_at}=values;
        const result=await this.call("availability_search",{property_name:property,category,quantity,people,starts_at,ends_at});
        if(!current())return;
        if(result.property!==property)throw Error("Availability context mismatch");
        put(d,this.availability_result(result));
        d.fields_dict._availability_result.$wrapper[0]?.scrollIntoView({block:"nearest"});
      }catch(error){if(current())put(d,`<p role="alert">${e(__("No se pudo consultar. Revise los filtros y pulse Buscar disponibilidad para reintentar."))}</p>`);}
    },__("Buscar disponibilidad"),"large");
    dialog.$wrapper.addClass("hs-availability-dialog");
    dialog.$wrapper.on("input.hsAvailability change.hsAvailability","input,select",()=>{
      sequence++;
      put(dialog,`<p>${e(__("Datos cambiados. Pulse Buscar disponibilidad para actualizar el resultado."))}</p>`);
    });
    dialog.$wrapper.one("hide.bs.modal.hsAvailability",()=>{shown=false;sequence++;});
    return dialog;
  };
})();
