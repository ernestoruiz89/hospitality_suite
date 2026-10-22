/* Operational room holds, independent of reservations and maintenance orders. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const e=value=>frappe.utils.escape_html(String(value??""));
  const f=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),
    fieldtype:fieldtype==="Datetime"?"Data":fieldtype,_hsDateTime:fieldtype==="Datetime",...extra});
  const reasons={"House Use":__("Uso interno"),"VIP Hold":__("Reserva VIP"),Owner:__("Propietario"),
    Maintenance:__("Mantenimiento"),Other:__("Otro")};
  const reason=value=>reasons[value]||value;
  const state=(desk,row)=>{
    if(row.status==="Released")return __("Liberado");
    const now=desk.serverNow(),start=moment.tz(row.starts_at,desk.data.system_timezone).valueOf(),
      end=moment.tz(row.ends_at,desk.data.system_timezone).valueOf();
    return end<=now?__("Vencido"):start>now?__("Programado"):__("En vigor");
  };

  Desk.prototype.render_room_blocks=function(el){
    const board=this.data.room_blocks||{active:[],recently_released:[]},active=board.active||[],recent=board.recently_released||[];
    const rows=active.map(row=>[e(this.roomName(row.room)),e(reason(row.reason)),
      `${e(this.date(row.starts_at))} → ${e(this.date(row.ends_at))}`,e(state(this,row)),e(row.note||"—"),
      this.button("room_unblock",__("Liberar"),row.name)]);
    el.html(`<div class="hs-toolbar"><div><h2>${e(__("Bloqueos de habitaciones"))}</h2><p>${e(__("Saque una habitación de venta por uso interno, VIP, propietario, mantenimiento u otro motivo."))}</p></div>
      ${this.button("room_block",__("Bloquear habitación"),"","primary")}</div>
      <section class="hs-section"><h2>${e(__("Bloqueos activos y programados"))}</h2>
      <p class="hs-note">${e(__("El fin del intervalo no se incluye. Al vencer, la habitación vuelve a estar disponible sin borrar el registro."))}</p>
      ${this.table([__("Habitación"),__("Motivo"),__("Intervalo"),__("Estado"),__("Nota"),__("Acción")],rows)}</section>
      <section class="hs-section"><h2>${e(__("Liberados recientemente"))}</h2>
      ${this.table([__("Habitación"),__("Motivo"),__("Intervalo"),__("Liberado"),__("Motivo de liberación")],recent.map(row=>[
        e(this.roomName(row.room)),e(reason(row.reason)),`${e(this.date(row.starts_at))} → ${e(this.date(row.ends_at))}`,
        e(this.date(row.released_on)),e(row.release_note||"—")]))}</section>`);
  };
  Desk.prototype["render_room-blocks"]=Desk.prototype.render_room_blocks;

  Desk.prototype.action_room_block=async function(roomId=""){
    const rooms=(this.data.rooms||[]).filter(row=>row.active),key=frappe.utils.get_random(24);
    if(!rooms.length){frappe.msgprint(__("No hay habitaciones activas para bloquear."));return;}
    const start=moment.parseZone(this.data.property_now||this.data.server_time).seconds(0).format("YYYY-MM-DDTHH:mm"),
      end=moment.parseZone(this.data.property_now||this.data.server_time).seconds(0).add(1,"day").format("YYYY-MM-DDTHH:mm");
    return this.dialog(__("Bloquear habitación"),[
      f("room",__("Habitación"),"Select",{reqd:1,_hsDataOptions:true,default:roomId,
        options:[{value:"",label:__("Seleccione…")},...rooms.map(row=>({value:row.name,label:row.room_number}))]}),
      f("reason",__("Motivo"),"Select",{reqd:1,_hsDataOptions:true,default:"House Use",
        options:Object.entries(reasons).map(([value,label])=>({value,label}))}),
      f("starts_at",__("Inicio"),"Datetime",{reqd:1,default:start}),
      f("ends_at",__("Fin (sin incluir)"),"Datetime",{reqd:1,default:end}),
      f("note",__("Nota; obligatoria para Otro"),"Small Text")],
      async(v,d)=>{await this.mutate("room_block",v,key);d.hide();},__("Confirmar bloqueo"));
  };

  Desk.prototype.action_room_unblock=async function(id){
    const block=(this.data.room_blocks?.active||[]).find(row=>row.name===id);
    if(!block)return;
    const key=frappe.utils.get_random(24);
    return this.dialog(`${__("Liberar habitación")} · ${this.roomName(block.room)}`,[
      f("reason",__("Motivo de liberación"),"Small Text",{reqd:1})],
      async(v,d)=>{await this.mutate("room_unblock",{block:id,modified:block.modified,...v},key);d.hide();},
      __("Liberar habitación"));
  };

  const reception=Desk.prototype.render_reception;
  Desk.prototype.render_reception=function(el){
    reception.call(this,el);
    if(this.allowed("block"))el.find(".hs-toolbar").first().append(this.button("room_block",__("Bloquear habitación")));
    for(const node of el.find(".hs-room")){
      const block=this.data.blocks.find(row=>row.kind==="Room Block"&&row.room===node.dataset.room&&
        row.starts_at<=this.data.server_time&&row.ends_at>this.data.server_time);
      if(!block)continue;
      const details=(this.data.room_blocks?.active||[]).find(row=>row.name===block.room_block);
      $(node).find(".hs-room-tags .hs-badge").first().text(__("Bloqueada"));
      $(node).find(".hs-room-info").html(`<p>${e(details?reason(details.reason):__("Bloqueo operativo"))} · ${e(this.date(block.ends_at))}</p>`);
    }
  };
  window.hospitality_suite.room_block_reason=reason;
})();
