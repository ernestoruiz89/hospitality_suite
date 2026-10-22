/* Short operational queues; dates and balances remain server-authoritative. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  const labels={hosted:__("Alojados"),arrivals:__("Llegadas"),departures:__("Salidas"),accounts:__("Cuentas abiertas")};
  const help={hosted:__("Estancias activas ahora."),arrivals:__("Pendientes hasta esa fecha, también atrasadas. Una fila por habitación."),
    departures:__("Salidas pendientes hasta esa fecha, también atrasadas."),accounts:__("Una fila por cuenta, incluido saldo cero. Las compartidas aparecen una vez.")};
  const empty={hosted:__("No hay huéspedes alojados."),arrivals:__("No hay llegadas pendientes hasta esa fecha."),departures:__("No hay salidas pendientes hasta esa fecha."),accounts:__("No hay cuentas abiertas.")};
  Desk.prototype.roomTiming=function(stay,arrival){
    const current=stay?`<span>${e(__("Entrada prevista"))}</span><strong>${e(this.date(stay.starts_at))}</strong><span>${e(__("Salida prevista"))}</span><strong>${e(this.date(stay.ends_at))}</strong><small data-countdown="${e(stay.ends_at)}"></small>`:"";
    const next=arrival?`<div class="hs-next-arrival"><span data-room-arrival="${e(arrival.starts_at)}">${e(this.arrivalState?this.arrivalState(arrival.starts_at):__("Próxima llegada pendiente"))}</span><strong>${e(this.date(arrival.starts_at))}</strong><small>${e(arrival.status==="Hold"?__("Retención temporal · aún sin entrada"):__("Reserva · aún sin entrada"))}</small></div>`:"";
    return current+next||`<span>${e(__("Consulte la disponibilidad para el período deseado."))}</span>`;
  };
  Desk.prototype.boardRows=function(data){
    const action=row=>this.button("detail",__("Ver estancia"),row.name);
    const cleaning=row=>row.cleaning_status?this.badge(row.cleaning_status):`<small>${e(__("Sin habitación asignada"))}</small>`;
    const account=row=>(row.account_balances||[]).length?(row.account_balances.map(balance=>e(this.amount(balance.outstanding,balance.currency))).join("<br>")+
      (row.shared_account?`<br><small>${e(__("Cuenta compartida"))}</small>`:"")):`<small>${e(__("Sin cuenta abierta"))}</small>`;
    if(data.view==="arrivals")return this.table([__("Habitación / categoría"),__("Huésped / pagador"),__("Entrada prevista"),__("Reserva y limpieza"),__("Cuenta"),__("Acción")],data.rows.map(row=>[
      `${e(row.room_label)}<br><small>${e(row.category_label)}</small>`,`${e(row.guest_label)}<br><small>${e(row.customer_label)}</small>`,e(this.date(row.starts_at)),`${this.badge(row.status)}<br>${cleaning(row)}`,account(row),this.button("booking",__("Gestionar llegada"),row.booking)]));
    if(data.view==="accounts")return this.table([__("Cuenta"),__("Pagador"),__("Habitación / grupo"),__("Saldo total"),__("Acción")],data.rows.map(row=>[
      e(row.label),e(row.customer_label),`${row.shared?e(__("Grupo"))+" · ":""}${e(row.room_label)}`,e(this.amount(row.balance.outstanding,row.currency)),row.detail_stay?this.button("detail",__("Ver cuenta"),row.detail_stay):row.booking?this.button("booking",__("Ver reserva"),row.booking):"—"]));
    if(data.view==="departures")return this.table([__("Habitación"),__("Huésped"),__("Salida prevista"),__("Limpieza"),__("Cuenta"),__("Acción")],data.rows.map(row=>[
      e(row.room_label),e(row.guest_label),`${e(this.date(row.ends_at))}${row.ends_at<data.server_time?"<br>"+this.badge(__("Salida vencida")):""}`,cleaning(row),account(row),action(row)]));
    return this.table([__("Habitación"),__("Huésped"),__("Entrada prevista"),__("Salida prevista"),__("Estado y limpieza"),__("Cuenta"),__("Acción")],data.rows.map(row=>[
      e(row.room_label),e(row.guest_label),e(this.date(row.starts_at)),e(this.date(row.ends_at)),`${this.badge(row.status)}<br>${cleaning(row)}`,account(row),action(row)]));
  };
  Desk.prototype.render_stays=function(el){
    this.boardSelections??={};
    const selection=this.boardSelections[this.property]=this.restore_board_selection?this.restore_board_selection():this.boardSelections[this.property]||{view:"hosted",date:(this.data.property_now||this.data.server_time).slice(0,10),offset:0};
    el.html(`<div class="hs-toolbar hs-board-toolbar">${this.button("walk_in",__("Registrar entrada inmediata"),"","primary")}</div>`+
      `<div class="hs-board-views" role="group" aria-label="${e(__("Vistas de estancias"))}">${Object.entries(labels).map(([view,label])=>`<button type="button" class="btn btn-secondary hs-board-view" data-board-view="${view}" aria-pressed="${view===selection.view}">${e(label)} · …</button>`).join("")}</div>`+
      `<p class="hs-board-period"></p><div class="hs-board-date"><label for="hs-board-date">${e(__("Consultar pendientes hasta"))}</label><input id="hs-board-date" type="date" class="form-control" value="${e(selection.date)}"><small>${e(__("Fecha calendario local. La fecha operativa se conserva."))}</small></div>`+
      `<p class="hs-board-help"></p><section class="hs-board-results" aria-live="polite"></section><div class="hs-board-pagination"></div>`);
    el.find("[data-board-view]").on("click",event=>{selection.view=event.currentTarget.dataset.boardView;selection.offset=0;this.loadBoard(el,selection);});
    el.find("#hs-board-date").on("change",event=>{selection.date=event.target.value;selection.offset=0;this.loadBoard(el,selection);});
    el.find(".hs-board-pagination").on("click","[data-board-offset]",event=>{selection.offset=Number(event.currentTarget.dataset.boardOffset);this.loadBoard(el,selection);});
    this.loadBoard(el,selection);
  };
  Desk.prototype.loadBoard=async function(el,selection){
    this.save_preference?.("stay-board",selection);
    const sequence=this.boardSequence=(this.boardSequence||0)+1,property=this.property,query={property_name:property,...selection};
    const results=el.find(".hs-board-results"),pager=el.find(".hs-board-pagination");
    el.find("[data-board-view]").each((_,node)=>$(node).attr("aria-pressed",String(node.dataset.boardView===selection.view)));
    el.find(".hs-board-date").toggle(["arrivals","departures"].includes(selection.view));
    el.find(".hs-board-period").text(__("Llegadas y salidas hasta {0} · {1}",[selection.date,this.prop?.time_zone||""]));
    el.find(".hs-board-help").text(help[selection.view]);
    results.attr("aria-busy","true").html(`<p role="status">${e(__("Cargando estancias…"))}</p>`);pager.empty();
    const current=()=>this.boardSequence===sequence&&this.property===property;
    try{
      const data=await this.call("stay_board",query);
      if(!current())return;
      if(!data||data.property!==property||data.date!==query.date||data.view!==query.view)throw Error("Unexpected board context");
      el.find("[data-board-view]").each((_,node)=>$(node).text(`${labels[node.dataset.boardView]} · ${data.counts[node.dataset.boardView]}`));
      results.html(data.rows.length?this.boardRows(data):this.empty(empty[data.view]));
      const start=data.total?data.offset+1:0,end=Math.min(data.offset+data.page_length,data.total);
      pager.html(`${data.offset?`<button type="button" class="btn btn-secondary" data-board-offset="${Math.max(0,data.offset-data.page_length)}">${e(__("Anterior"))}</button>`:""}<span>${e(__("Mostrando {0}–{1} de {2}",[start,end,data.total]))}</span>${data.has_more?`<button type="button" class="btn btn-secondary" data-board-offset="${data.offset+data.page_length}">${e(__("Siguiente"))}</button>`:""}`);
    }catch(error){
      if(!current())return;
      results.html(`<div class="hs-empty" role="alert"><p>${e(__("No se pudo consultar esta vista. Compruebe la fecha y vuelva a actualizar."))}</p>${this.button("reload",__("Actualizar"))}</div>`);
    }finally{if(current())results.attr("aria-busy","false");}
  };
})();
