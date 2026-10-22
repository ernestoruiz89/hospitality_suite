/* A room's operational context, loaded only when the user opens it. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const e=value=>frappe.utils.escape_html(String(value??""));
  const choices={all:__("Todas"),arrival:__("Llegan"),departure:__("Salen"),work:__("Trabajo pendiente")};
  const validFilter=value=>Object.hasOwn(choices,value)?value:"all";
  const command=(action,label,id="")=>`<button type="button" class="btn btn-secondary" data-room-cmd="${e(action)}" data-id="${e(id)}">${e(label)}</button>`;
  const status=(value,label)=>`<span class="hs-room-state ${value?"is-on":""}">${e(label)}</span>`;
  const renderTime=(desk,value)=>value?e(desk.date(value)):"—";
  const cleaningLabel=value=>({Clean:__("Limpia"),Dirty:__("Sucia"),Cleaning:__("En limpieza"),Inspection:__("Pendiente de inspección")})[value]||__(value||"—");

  const render=Desk.prototype.render;
  Desk.prototype.render=function(){
    if(this.route!=="hospitality-reception"&&this.roomPanel)this.roomPanel.dialog.hide();
    return render.call(this);
  };

  const reception=Desk.prototype.render_reception;
  Desk.prototype.render_reception=function(el){
    this.roomBoard=null;
    reception.call(this,el);
    this.roomOperationalFilter=validFilter(this.read_preference("room-operational-filter"));
    const chips=Object.entries(choices).map(([key,label])=>`<button type="button" class="hs-room-filter-chip" data-room-filter="${key}" aria-pressed="${key===this.roomOperationalFilter}">${e(label)} <span data-room-count="${key}">—</span></button>`).join("");
    el.find(".hs-filter-status").after(`<div class="hs-room-operational-filters" role="group" aria-label="${e(__("Filtros operativos"))}">${chips}</div><p class="hs-room-board-status" role="status">${e(__("Actualizando estados de habitaciones…"))}</p>`);
    el.find(".hs-room").each((_,node)=>{
      const room=this.data.rooms.find(row=>row.name===node.dataset.room);
      if(!room)return;
      $(node).find(".hs-room-actions").prepend(this.button("room_view",__("Abrir ficha"),room.name));
      $(node).find(".hs-room-tags").append('<span class="hs-room-operational-tags"></span>');
    });
    el.off("click.hsRoomFilter").on("click.hsRoomFilter","[data-room-filter]",event=>{
      this.roomOperationalFilter=validFilter(event.currentTarget.dataset.roomFilter);
      this.save_preference("room-operational-filter",this.roomOperationalFilter);
      this.filterRooms();
    });
    this.loadRoomBoard(el);
    if(this.roomPanel?.property===this.property)this.loadRoomSnapshot(this.roomPanel);
    else if(this.roomPanel)this.roomPanel.dialog.hide();
  };

  const baseFilter=Desk.prototype.filterRooms;
  Desk.prototype.filterRooms=function(){baseFilter.call(this);this.applyRoomOperationalFilter?.();};
  Desk.prototype.applyRoomOperationalFilter=function(){
    if(this.route!=="hospitality-reception")return;
    const selected=validFilter(this.roomOperationalFilter),rows=this.roomBoard?.rooms||[];
    this.root.find("[data-room-filter]").each((_,node)=>node.setAttribute("aria-pressed",String(node.dataset.roomFilter===selected)));
    if(!this.roomBoard){
      this.root.find(".hs-room-filter-chip").prop("disabled",selected!=="all");
      return;
    }
    this.root.find(".hs-room-filter-chip").prop("disabled",false);
    const map=new Map(rows.map(row=>[row.name,row]));
    let shown=0;
    this.root.find(".hs-room").each((_,node)=>{
      const row=map.get(node.dataset.room);
      const room=this.data.rooms.find(item=>item.name===node.dataset.room);
      const baseVisible=Boolean(room&&window.hospitality_suite.navigation.matches(room,this.data,this.roomFilters));
      const match=selected==="all"||Boolean(row?.[selected]);
      $(node).toggle(baseVisible&&match);
      if(baseVisible&&match)shown++;
    });
    this.root.find(".hs-filter-count").text(__("Mostrando {0} de {1} habitaciones",[shown,rows.length]));
    this.root.find(".hs-filter-empty").prop("hidden",shown>0);
  };

  Desk.prototype.loadRoomBoard=async function(el){
    const token=this.roomBoardToken={},property=this.property;
    const current=()=>this.roomBoardToken===token&&this.property===property&&this.route==="hospitality-reception";
    try{
      const data=await this.call("room_board_snapshot",{property_name:property});
      if(!current())return;
      if(data?.property!==property||!Array.isArray(data.rooms)||data.rooms.some(row=>!row.name))throw Error("Invalid room board");
      this.roomBoard=data;
      for(const [key] of Object.entries(choices))el.find(`[data-room-count="${key}"]`).text(key==="all"?data.rooms.length:data.counts?.[key]??"—");
      const map=new Map(data.rooms.map(row=>[row.name,row]));
      el.find(".hs-room").each((_,node)=>{
        const row=map.get(node.dataset.room);
        if(!row)return;
        const tags=[row.arrival&&status(true,row.overdue_arrival?__("Llegada atrasada"):__("Llega")),
          row.departure&&status(true,row.overdue_departure?__("Salida vencida"):__("Sale")),
          row.work&&status(true,__("Trabajo pendiente"))].filter(Boolean).join("");
        $(node).find(".hs-room-operational-tags").html(tags);
      });
      el.find(".hs-room-board-status").text(__("Actualizado: {0}",[this.date(data.checked_at)]));
      this.filterRooms();
    }catch{
      if(current())el.find(".hs-room-board-status").text(__("No se pudieron actualizar los filtros operativos. Pulse Actualizar para reintentar."));
    }
  };

  Desk.prototype.action_room_view=function(room){return this.openRoomPanel(room);};
  Desk.prototype.syncRoomTab=function(context){
    if(this.roomPanel!==context)return;
    const tabs=context.dialog.$wrapper.find("[data-room-tab]");
    tabs.each((_,node)=>{
      const selected=node.dataset.roomTab===context.tab;
      node.setAttribute("aria-selected",String(selected));node.tabIndex=selected?0:-1;
    });
  };
  Desk.prototype.focusRoomTab=function(context){
    context.dialog.$wrapper.find("[data-room-tab]").filter((_,node)=>node.dataset.roomTab===context.tab).trigger("focus");
    this.syncRoomTab(context);
    setTimeout(()=>this.syncRoomTab(context),0);
  };
  Desk.prototype.openRoomPanel=function(room,returnOrigin){
    if(!this.data.rooms.some(row=>row.name===room))return;
    if(this.roomPanel)this.roomPanel.dialog.hide();
    const origin=returnOrigin||document.activeElement,property=this.property;
    const dialog=new frappe.ui.Dialog({title:__("Ficha de habitación {0}",[this.roomName(room)]),size:"extra-large",animate:false,
      fields:[{fieldname:"body",fieldtype:"HTML",options:`<div class="hs-room-panel-body" role="status">${e(__("Cargando habitación…"))}</div>`}]});
    dialog.$wrapper.addClass("hs-room-panel");
    const context={dialog,property,room,tab:"now",sequence:0,sectionSequence:0,origin};
    this.roomPanel=context;
    dialog.$wrapper.one("hide.bs.modal.hsRoomPanel",()=>{
      context.sequence++;context.sectionSequence++;
      if(this.roomPanel===context)this.roomPanel=null;
      if(origin?.isConnected)origin.focus();
      else this.root.find(".hs-room").filter((_,node)=>node.dataset.room===room).find('[data-act="room_view"]').trigger("focus");
    });
    dialog.$wrapper.on("click.hsRoomPanel","[data-room-tab]",event=>{
      event.preventDefault();event.stopPropagation();
      context.tab=event.currentTarget.dataset.roomTab;
      this.renderRoomPanel(context);
      this.focusRoomTab(context);
    });
    dialog.$wrapper.on("keydown.hsRoomPanel","[data-room-tab]",event=>{
      if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;
      const keys=["now","work","schedule","history","details","insights"],at=keys.indexOf(event.currentTarget.dataset.roomTab);
      const next=event.key==="Home"?0:event.key==="End"?keys.length-1:(at+(event.key==="ArrowRight"?1:keys.length-1))%keys.length;
      event.preventDefault();event.stopPropagation();context.tab=keys[next];this.renderRoomPanel(context);
      this.focusRoomTab(context);
    });
    dialog.$wrapper.on("click.hsRoomPanel","[data-room-cmd]",async event=>{
      const action=event.currentTarget.dataset.roomCmd,id=event.currentTarget.dataset.id||"";
      if(!["detail","booking","cleaning","maintenance","reserve","room_history","availability","room_view","ticket_new","ticket_detail","room_block","room_unblock"].includes(action))return;
      dialog.hide();
      const follow=await this.run_action(action,id,event.currentTarget);
      const resume=()=>{
        if(this.property!==property||this.route!=="hospitality-reception"||this.roomPanel)return;
        const visible=$(".modal.show").not(".hs-room-panel");
        if(visible.length){visible.last().one("hidden.bs.modal.hsRoomReturn",resume);return;}
        setTimeout(()=>{
          if(this.property===property&&this.route==="hospitality-reception"&&!this.roomPanel){
            const pending=$(".modal.show").not(".hs-room-panel");
            if(pending.length)pending.last().one("hidden.bs.modal.hsRoomReturn",resume);
            else this.openRoomPanel(room,origin);
          }
        },300);
      };
      if(follow?.$wrapper)follow.$wrapper.one("hidden.bs.modal.hsRoomReturn",resume);
      else resume();
    });
    dialog.$wrapper.on("change.hsRoomPanel","[data-room-schedule-date],[data-room-schedule-days]",()=>this.loadRoomPanelSchedule(context));
    dialog.$wrapper.on("click.hsRoomPanel","[data-room-history-page]",event=>this.loadRoomPanelHistory(context,Number(event.currentTarget.dataset.roomHistoryPage)));
    dialog.$wrapper.on("change.hsRoomPanel","[data-room-history-view],[data-room-history-from],[data-room-history-to]",()=>this.loadRoomPanelHistory(context,0));
    dialog.$wrapper.on("change.hsRoomPanel","[data-room-insight-days]",()=>this.loadRoomPanelInsights(context));
    dialog.show();
    this.loadRoomSnapshot(context);
    return dialog;
  };

  Desk.prototype.loadRoomSnapshot=async function(context){
    const sequence=++context.sequence;
    const current=()=>this.roomPanel===context&&context.sequence===sequence&&this.property===context.property;
    try{
      const data=await this.call("room_snapshot",{property_name:context.property,room:context.room});
      if(!current())return;
      if(data?.property!==context.property||data?.room?.name!==context.room)throw Error("Invalid room snapshot");
      context.data=data;
      this.renderRoomPanel(context);
    }catch{
      if(current())context.dialog.fields_dict.body.$wrapper.html(`<p role="alert">${e(__("No se pudo consultar la habitación. Cierre la ficha y vuelva a intentarlo."))}</p>`);
    }
  };

  Desk.prototype.renderRoomPanel=function(context){
    if(this.roomPanel!==context||!context.data)return;
    const d=context.data,r=d.room;
    const tabs=[["now",__("Ahora")],["work",__("Trabajo")],["schedule",__("Agenda")],["history",__("Historial")],["details",__("Datos")],["insights",__("Indicadores")]];
    const nav=`<div class="hs-room-panel-tabs" role="tablist" aria-label="${e(__("Secciones de la habitación"))}">${tabs.map(([key,label])=>`<button type="button" id="hs-room-tab-${key}" role="tab" data-room-tab="${key}" aria-controls="hs-room-tab-content" aria-selected="${context.tab===key}" tabindex="${context.tab===key?0:-1}">${e(label)}</button>`).join("")}</div>`;
    const head=`<div class="hs-room-panel-head"><div><strong>${e(r.room_number)}</strong><span>${e(r.category_label)}${r.floor?` · ${e(__("Piso"))} ${e(r.floor)}`:""}</span></div><div class="hs-room-panel-states">${status(r.occupied, r.occupied?__("Ocupada"):__("Sin ocupación"))}${status(r.cleaning_status==="Clean",cleaningLabel(r.cleaning_status))}${r.blocked?status(true,r.block_kind==="Room Block"?__("Bloqueada"):__("Fuera de servicio")):""}${!r.active?status(true,__("Inactiva")):""}</div></div><p class="hs-room-panel-checked">${e(__("Actualizado"))}: ${renderTime(this,d.checked_at)} · ${e(d.time_zone)}</p>`;
    let content="";
    if(context.tab==="now"){
      const s=d.current,a=d.next_arrival;
      content=`<section><h3>${e(__("Estancia actual"))}</h3>${s?`<p>${e(s.guest_label||__("Huésped registrado"))} · ${renderTime(this,s.starts_at)} → ${renderTime(this,s.ends_at)}</p>${s.overdue?`<p class="hs-room-alert">${e(__("Salida prevista vencida"))}</p>`:""}${s.account_balances?`<p>${e(s.shared_account?__("Cuenta compartida del grupo"):__("Saldo de cuenta"))}: ${s.account_balances.map(x=>e(this.amount(x.outstanding,x.currency))).join(" · ")||"—"}</p>`:""}${s.name?command("detail",__("Abrir estancia y cuenta"),s.name):""}`:`<p>${e(__("Sin estancia activa"))}</p>`}</section>`+
        `<section><h3>${e(__("Próxima llegada asignada"))}</h3>${a?`<p>${e(a.guest_label||__("Huésped registrado"))} · ${renderTime(this,a.starts_at)} → ${renderTime(this,a.ends_at)}</p>${a.overdue?`<p class="hs-room-alert">${e(__("Llegada pendiente; hora prevista superada"))}</p>`:""}${a.booking?command("booking",__("Gestionar llegada"),a.booking):""}`:`<p>${e(__("No hay llegada asignada pendiente"))}</p>`}</section>`;
    }else if(context.tab==="work"){
      content=`<section><h3>${e(__("Limpieza e inspección"))}</h3>${d.tasks.length?d.tasks.map(t=>`<article class="hs-room-work"><strong>${e(__(t.kind))} · ${e(__(t.status))}</strong><p>${e(__("Prioridad"))}: ${e(__(t.priority))} · ${e(t.assigned_to||__("Sin responsable"))}</p>${d.can.clean?command("cleaning",__("Abrir tarea"),t.name):""}</article>`).join(""):`<p>${e(__("Sin tareas abiertas"))}</p>`}</section>`+
        `<section><h3>${e(__("Mantenimiento"))}</h3>${d.maintenance.length?d.maintenance.map(m=>`<article class="hs-room-work"><strong>${e(m.title)}</strong><p>${e(__(m.status))} · ${e(m.blocks_room?__("Bloquea la habitación"):__("No bloquea la habitación"))}${m.until_reopened?` · ${e(__("Hasta reapertura autorizada"))}`:""}</p><p>${e(__("Responsable"))}: ${e(m.assigned_to||__("Sin responsable"))}</p>${d.can.maintain?command("maintenance",__("Abrir incidencia"),m.name):""}</article>`).join(""):`<p>${e(__("Sin incidencias abiertas"))}</p>`}${d.can.maintain?command("maintenance",__("Registrar incidencia"),r.name):""}</section>`+
        (d.can.ticket?`<section><h3>${e(__("Tickets"))}</h3>${d.tickets.length?d.tickets.map(t=>`<article class="hs-room-work"><strong>${e(t.subject)}</strong><p>${e(__(t.status))} · ${e(__(t.priority))} · ${e(__("Plazo"))}: ${renderTime(this,t.due_at)}</p><p>${e(__("Responsable"))}: ${e(t.assigned_to||__("Sin responsable"))}</p>${command("ticket_detail",__("Ver historial"),t.name)}</article>`).join(""):`<p>${e(__("Sin tickets pendientes"))}</p>`}${command("ticket_new",__("Crear ticket"),r.name)}</section>`:"");
      if(d.can.block)content+=`<section><h3>${e(__("Bloqueos operativos"))}</h3>${d.room_blocks.length?d.room_blocks.map(b=>`<article class="hs-room-work"><strong>${e(window.hospitality_suite.room_block_reason(b.reason))}</strong><p>${renderTime(this,b.starts_at)} → ${renderTime(this,b.ends_at)}</p>${b.note?`<p>${e(b.note)}</p>`:""}${command("room_unblock",__("Liberar bloqueo"),b.name)}</article>`).join(""):`<p>${e(__("Sin bloqueos operativos activos"))}</p>`}${command("room_block",__("Bloquear habitación"),r.name)}</section>`;
    }else if(context.tab==="schedule"){
      const date=context.scheduleDate||d.checked_at.slice(0,10),days=context.scheduleDays||(d.mode==="Por tiempo"?1:7);
      content=`<section><h3>${e(__("Agenda de la habitación"))}</h3><div class="hs-room-panel-controls"><label>${e(__("Desde"))}<input type="date" data-room-schedule-date value="${e(date)}"></label><label>${e(__("Días"))}<select data-room-schedule-days>${(d.mode==="Por tiempo"?[1,2,7]:[7,14,30]).map(n=>`<option value="${n}" ${n===days?"selected":""}>${n}</option>`).join("")}</select></label></div><div class="hs-room-schedule-result" role="status"></div><p class="hs-note">${e(__("Una franja sin asignación no confirma cupo. Consulte el período antes de reservar."))}</p>${d.can.reserve?command("availability",__("Buscar disponibilidad")):""}</section>`;
    }else if(context.tab==="history"){
      const day=d.checked_at.slice(0,10),from=context.historyFrom||moment(day).subtract(7,"days").format("YYYY-MM-DD"),to=context.historyTo||moment(day).add(1,"day").format("YYYY-MM-DD"),view=context.historyView||"activity";
      content=d.can.history?`<section><h3>${e(__("Historial de la habitación"))}</h3><div class="hs-room-panel-controls"><label>${e(__("Desde"))}<input type="date" data-room-history-from value="${e(from)}"></label><label>${e(__("Hasta (sin incluir)"))}<input type="date" data-room-history-to value="${e(to)}"></label><label>${e(__("Vista"))}<select data-room-history-view>${[["activity",__("Actividad")],["changes",__("Cambios de datos")],["periods",__("Estancias y bloqueos")],["all",__("Todo")]].map(([key,label])=>`<option value="${key}" ${key===view?"selected":""}>${e(label)}</option>`).join("")}</select></label></div><div class="hs-room-history-result" role="status"></div></section>`:`<p>${e(__("Su rol no puede consultar este historial."))}</p>`;
    }else if(context.tab==="details"){
      const x=d.details;
      content=`<section><h3>${e(__("Características"))}</h3><dl class="hs-room-facts">${[[__("Piso"),x.floor],[__("Zona"),x.zone],[__("Camas"),x.beds],[__("Estacionamiento"),x.parking],[__("Capacidad"),x.capacity],[__("Camas adicionales"),x.max_extra_beds],[__("Comodidades"),x.amenities]].map(([k,v])=>`<div><dt>${e(k)}</dt><dd>${e(v??"—")}</dd></div>`).join("")}</dl>${x.description?`<p>${e(x.description)}</p>`:""}${x.image&&/^\/files\/[A-Za-z0-9][A-Za-z0-9_.-]{0,180}\.(?:png|jpg|jpeg|webp|gif)$/i.test(x.image)?`<img class="hs-room-image" src="${e(x.image)}" alt="${e(__("Imagen de la categoría"))}">`:""}</section>`;
    }else if(context.tab==="insights"){
      const days=context.insightDays||30;
      content=`<section><h3>${e(__("Uso de esta habitación"))}</h3><label>${e(__("Período"))}<select data-room-insight-days>${[7,30,90].map(n=>`<option value="${n}" ${n===days?"selected":""}>${n} ${e(__("días"))}</option>`).join("")}</select></label><div class="hs-room-insights-result" role="status"></div></section>`;
    }
    context.dialog.fields_dict.body.$wrapper.html(`<div class="hs-room-panel-body">${head}${nav}<div id="hs-room-tab-content" class="hs-room-panel-content" role="tabpanel" aria-labelledby="hs-room-tab-${context.tab}">${content}</div></div>`);
    this.syncRoomTab(context);
    if(context.tab==="schedule")this.loadRoomPanelSchedule(context);
    if(context.tab==="history"&&d.can.history)this.loadRoomPanelHistory(context,0);
    if(context.tab==="insights")this.loadRoomPanelInsights(context);
  };

  Desk.prototype.loadRoomPanelSchedule=async function(context){
    const target=context.dialog.$wrapper.find(".hs-room-schedule-result");
    if(!target.length)return;
    const date=String(context.dialog.$wrapper.find("[data-room-schedule-date]").val()||""),days=Number(context.dialog.$wrapper.find("[data-room-schedule-days]").val());
    context.scheduleDate=date;context.scheduleDays=days;
    const seq=++context.sectionSequence,property=context.property,room=context.room,zone=context.data.time_zone;
    const start=moment.tz(date,"YYYY-MM-DD",zone),end=start.clone().add(days,"days");
    if(!start.isValid()||start.format("YYYY-MM-DD")!==date||!Number.isInteger(days)||days<1||days>30){target.html(`<p role="alert">${e(__("Seleccione fecha y período válidos."))}</p>`);return;}
    const current=()=>this.roomPanel===context&&context.sectionSequence===seq&&this.property===property&&context.tab==="schedule";
    target.attr("aria-busy","true").html(e(__("Consultando agenda…")));
    try{
      const data=await this.call("room_schedule",{property_name:property,room,starts_at:start.format("YYYY-MM-DDTHH:mm:ssZ"),ends_at:end.format("YYYY-MM-DDTHH:mm:ssZ")});
      if(!current())return;
      if(data?.property!==property||data?.room!==room||!Array.isArray(data.rows))throw Error("Invalid schedule");
      const a=start.valueOf(),b=end.valueOf();
      target.html(data.rows.length?`<div class="hs-room-schedule-track" aria-hidden="true">${data.rows.map(row=>{
        const left=Math.max(0,(Date.parse(row.starts_at)-a)/(b-a)*100),right=Math.min(100,(Date.parse(row.ends_at)-a)/(b-a)*100);
        return `<span class="is-${row.kind==="Room Block"?"block":e(row.kind.toLowerCase())}" style="left:${left.toFixed(3)}%;width:${Math.max(.4,right-left).toFixed(3)}%"></span>`;
      }).join("")}</div><div class="hs-room-schedule-list">${data.rows.map(row=>`<article><strong>${row.kind==="Room Block"?e(window.hospitality_suite.room_block_reason(row.block_reason)):e(__(row.kind))}${row.until_reopened?` · ${e(__("Hasta reapertura autorizada"))}`:""}</strong><span>${renderTime(this,row.starts_at)} → ${renderTime(this,row.ends_at)}</span>${row.stay?command("detail",__("Abrir estancia"),row.stay):row.booking?command("booking",__("Abrir reserva"),row.booking):row.maintenance?command("maintenance",__("Abrir incidencia"),row.maintenance):row.room_block&&row.status==="Active"?command("room_unblock",__("Liberar bloqueo"),row.room_block):""}</article>`).join("")}</div>`:`<p>${e(__("Sin asignaciones de esta habitación en el período consultado."))}</p>`);
    }catch{if(current())target.html(`<p role="alert">${e(__("No se pudo consultar la agenda. Vuelva a intentar."))}</p>`);}
    finally{if(current())target.attr("aria-busy","false");}
  };

  Desk.prototype.loadRoomPanelHistory=async function(context,offset=0){
    const target=context.dialog.$wrapper.find(".hs-room-history-result");if(!target.length)return;
    const from=String(context.dialog.$wrapper.find("[data-room-history-from]").val()||""),to=String(context.dialog.$wrapper.find("[data-room-history-to]").val()||""),view=String(context.dialog.$wrapper.find("[data-room-history-view]").val()||"activity");
    context.historyFrom=from;context.historyTo=to;context.historyView=view;
    const seq=++context.sectionSequence,property=context.property,room=context.room;
    const current=()=>this.roomPanel===context&&context.sectionSequence===seq&&this.property===property&&context.tab==="history";
    if(!/^\d{4}-\d{2}-\d{2}$/.test(from)||!/^\d{4}-\d{2}-\d{2}$/.test(to)||to<=from){target.html(`<p role="alert">${e(__("Indique un rango de fechas válido."))}</p>`);return;}
    target.attr("aria-busy","true").html(e(__("Consultando historial…")));
    try{
      const data=await this.call("room_history",{property_name:property,room,starts_at:`${from}T00:00:00`,ends_at:`${to}T00:00:00`,view,offset,page_length:25});
      if(!current())return;
      if(data?.property!==property||data?.room!==room||data?.view!==view||!Array.isArray(data.rows))throw Error("Invalid history");
      target.html(this.room_history_rows(data)+`<div class="hs-history-pagination">${data.offset?`<button type="button" class="btn btn-secondary" data-room-history-page="${Math.max(0,data.offset-25)}">${e(__("Anterior"))}</button>`:""}<span>${e(__("{0} registros",[data.total]))}</span>${data.has_more?`<button type="button" class="btn btn-secondary" data-room-history-page="${data.offset+25}">${e(__("Siguiente"))}</button>`:""}</div>`);
    }catch{if(current())target.html(`<p role="alert">${e(__("No se pudo consultar el historial. Vuelva a intentar."))}</p>`);}
    finally{if(current())target.attr("aria-busy","false");}
  };

  Desk.prototype.loadRoomPanelInsights=async function(context){
    const target=context.dialog.$wrapper.find(".hs-room-insights-result");if(!target.length)return;
    const days=Number(context.dialog.$wrapper.find("[data-room-insight-days]").val());context.insightDays=days;
    const seq=++context.sectionSequence,property=context.property;
    const current=()=>this.roomPanel===context&&context.sectionSequence===seq&&this.property===property&&context.tab==="insights";
    target.attr("aria-busy","true").html(e(__("Calculando indicadores…")));
    try{
      const data=await this.call("room_insights",{property_name:property,days});if(!current())return;
      const row=data?.rooms?.find(item=>item.room===context.room);
      if(data?.property!==property||data.days!==days||!row)throw Error("Invalid room insights");
      const measures=[[__("Horas utilizadas"),`${row.used_hours} h`],[__("Horas fuera de servicio"),`${row.blocked_hours} h`],
        [__("Utilización"),row.utilization_pct===null?__("Sin horas comercializables"):row.utilization_pct===0&&row.used_hours>0?"< 0.1 %":`${row.utilization_pct} %`],
        [__("Rotaciones"),row.rotations],[__("Limpiezas completadas"),row.completed_cleans],
        [__("Limpieza media"),row.avg_clean_minutes===null?__("Sin mediciones válidas"):`${row.avg_clean_minutes} min`]];
      if(data.mode!=="Por tiempo")measures.unshift([__("Noches ocupadas"),row.occupied_nights]);
      target.html(`<p>${e(data.from_date)} → ${e(data.through_date)} · ${e(data.time_zone)} · ${e(__("Actualizado"))}: ${renderTime(this,data.checked_at)}</p><div class="hs-room-insights-grid">${measures.map(([label,value])=>`<div><span>${e(label)}</span><strong>${e(value)}</strong></div>`).join("")}</div><p class="hs-note">${e(data.denominator)}. ${e(__("Los ingresos por habitación requieren atribución histórica de cargos y cambios de cuarto."))}</p>`);
    }catch{if(current())target.html(`<p role="alert">${e(__("No se pudieron calcular los indicadores. Vuelva a intentar."))}</p>`);}
    finally{if(current())target.attr("aria-busy","false");}
  };

  const home=Desk.prototype.render_home;
  Desk.prototype.render_home=function(el){
    home.call(this,el);
    if(this.data.pages.some(p=>p.route==="hospitality-reception"))
      el.append(`<section class="hs-section hs-room-home-links"><h2>${e(__("Habitaciones"))}</h2><div class="hs-dialog-actions">${Object.entries(choices).filter(([key])=>key!=="all").map(([key,label])=>this.button("home_room_filter",label,key)).join("")}</div></section>`);
  };
  Desk.prototype.action_home_room_filter=function(value){
    if(!this.data.pages.some(p=>p.route==="hospitality-reception"))return;
    this.save_preference("room-operational-filter",validFilter(value));
    frappe.set_route("hospitality-reception");
  };

  const timers=Desk.prototype.updateTimers;
  Desk.prototype.updateTimers=function(){
    timers.call(this);
    if(this.route==="hospitality-reception"&&this.roomBoard&&!this.page_busy()&&typeof document!=="undefined"&&!document.hidden&&
       this.serverNow()-Date.parse(this.roomBoard.checked_at)>=30000)this.loadRoomBoard(this.root.find(".hs-content"));
  };
})();
