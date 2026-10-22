/* User/property-scoped navigation preferences and actionable operational Home. */
(() => {
  const ns=window.hospitality_suite,Desk=ns.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  const normalize=value=>String(value??"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLocaleLowerCase("es").trim();
  const inactive=room=>room.active===0||room.active===false;
  const blocked=(room,data)=>data.blocks.some(b=>b.room===room.name&&b.starts_at<=data.server_time&&(!b.ends_at||b.ends_at>data.server_time));
  const state=(room,data)=>inactive(room)?"inactive":blocked(room,data)?"blocked":data.occupied.some(s=>s.room===room.name)?"occupied":"vacant";
  const cleanStates=["Clean","Dirty","Cleaning","Inspection"],states={vacant:__("Sin ocupación"),occupied:__("Ocupada"),blocked:__("Bloqueada"),inactive:__("Inactiva")};
  const filters=(raw,data)=>{
    const value=raw&&typeof raw==="object"?raw:{};
    return {query:typeof value.query==="string"?value.query.slice(0,120):"",clean:cleanStates.includes(value.clean)?value.clean:"",
      floor:data.rooms.some(r=>String(r.floor||"")===value.floor)?value.floor:"",category:data.categories.some(c=>c.name===value.category)?value.category:"",state:Object.hasOwn(states,value.state)?value.state:""};
  };
  const matches=(room,data,selected)=>{
    const category=data.categories.find(c=>c.name===room.category)?.category_name||"";
    return (!selected.query||normalize([room.room_number,category,room.floor,room.zone].join(" ")).includes(normalize(selected.query)))&&
      (!selected.clean||room.cleaning_status===selected.clean)&&(!selected.floor||String(room.floor||"")===selected.floor)&&
      (!selected.category||room.category===selected.category)&&(!selected.state||state(room,data)===selected.state);
  };
  const selection=(raw,date)=>{
    const value=raw&&typeof raw==="object"?raw:{},parsed=new Date(String(value.date)+"T12:00:00Z"),validDate=typeof value.date==="string"&&/^\d{4}-\d{2}-\d{2}$/.test(value.date)&&Number.isFinite(parsed.valueOf())&&parsed.toISOString().slice(0,10)===value.date;
    return {view:["hosted","arrivals","departures","accounts"].includes(value.view)?value.view:"hosted",date:validDate?value.date:date,
      offset:Number.isInteger(value.offset)&&value.offset>=0?Math.min(value.offset,1000000):0};
  };
  ns.navigation={normalize,filters,matches,state,selection};
  Desk.prototype.preference_key=function(kind){return "hs-ui-v1:"+JSON.stringify([frappe.session?.user||"Guest",this.property,kind]);};
  Desk.prototype.read_preference=function(kind){try{return JSON.parse(ns.ui_storage.getItem(this.preference_key(kind))||"null");}catch{return null;}};
  Desk.prototype.save_preference=function(kind,value){ns.ui_storage.setItem(this.preference_key(kind),JSON.stringify(value));};
  Desk.prototype.calendar_day=function(){const epoch=this.serverNow();return Number.isFinite(epoch)?moment(epoch).tz(this.prop.time_zone).format("YYYY-MM-DD"):(this.data.property_now||this.data.server_time).slice(0,10);};
  Desk.prototype.restore_board_selection=function(){return selection(this.read_preference("stay-board"),this.calendar_day());};
  Desk.prototype.update_room_filter=function(key,value){
    this.roomFilters=filters({...this.roomFilters,[key]:value},this.data);this.query=this.roomFilters.query;
    this.save_preference("room-filters",this.roomFilters);this.filterRooms();
  };
  Desk.prototype.action_clear_room_filters=function(){
    this.roomFilters=filters(null,this.data);this.query="";this.save_preference("room-filters",this.roomFilters);
    this.root.find("#hs-search,#hs-floor,#hs-category,#hs-state,#hs-clean-filter").val("");this.filterRooms();this.root.find("#hs-search").trigger("focus");
  };
  Desk.prototype.filterRooms=function(){
    if(!this.roomFilters)return;
    let shown=0;const selected=this.roomFilters;
    this.root.find(".hs-room").each((_,node)=>{const room=this.data.rooms.find(r=>r.name===node.dataset.room),show=Boolean(room&&matches(room,this.data,selected));$(node).toggle(show);if(show)shown++;});
    this.root.find(".hs-filter-empty").prop("hidden",shown>0);
    this.root.find(".hs-filter-count").text(__("Mostrando {0} de {1} habitaciones",[shown,this.data.rooms.length]));
    this.root.find(".hs-filter-active").text(Object.entries(selected).filter(([key,value])=>key!=="query"&&value).length||__("Todos"));
  };
  const reception=Desk.prototype.render_reception;
  Desk.prototype.render_reception=function(el){
    this.roomFilters=filters(this.read_preference("room-filters"),this.data);this.query=this.roomFilters.query;
    reception.call(this,el);
    const floors=[...new Set(this.data.rooms.map(r=>String(r.floor||"")).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"es",{numeric:true}));
    const pick=(id,label,all,options)=>`<div><label for="${id}">${e(label)}</label><select id="${id}" class="form-control"><option value="">${e(all)}</option>${options.map(([value,text])=>`<option value="${e(value)}">${e(text)}</option>`).join("")}</select></div>`;
    const active=Object.entries(this.roomFilters).some(([key,value])=>key!=="query"&&value);
    el.find(".hs-toolbar").after(`<details class="hs-room-filters" ${active?"open":""}><summary>${e(__("Filtros de habitaciones"))} · <span class="hs-filter-active"></span></summary><div class="hs-filter-fields">${pick("hs-floor",__("Piso"),__("Todos los pisos"),floors.map(x=>[x,x]))}${pick("hs-category",__("Categoría"),__("Todas las categorías"),this.data.categories.map(c=>[c.name,c.category_name]))}${pick("hs-state",__("Estado de la habitación"),__("Cualquier estado"),Object.entries(states))}<div class="hs-clean-slot"><label for="hs-clean-filter">${e(__("Limpieza"))}</label></div></div></details><div class="hs-filter-status"><p class="hs-filter-count" role="status"></p>${this.button("clear_room_filters",__("Restablecer filtros"))}</div>`);
    el.find("#hs-clean-filter").appendTo(el.find(".hs-clean-slot"));
    for(const key of ["floor","category","state"])el.find(`#hs-${key}`).val(this.roomFilters[key]).on("change",event=>this.update_room_filter(key,event.target.value));
    el.find(".hs-filter-empty").append(" "+this.button("clear_room_filters",__("Mostrar todas las habitaciones")));
    this.filterRooms();this.load_room_balances(el);
  };
  Desk.prototype.load_room_balances=async function(el){
    const token=this.balanceView={},property=this.property,stays=new Map(this.data.occupied.map(s=>[s.room,s.name])),currency=this.prop.currency;
    if(!stays.size||!this.allowed("stay")&&!this.allowed("finance"))return;
    const current=()=>this.balanceView===token&&this.property===property;
    try{
      const values=await this.call("room_balances",{property_name:property});if(!current())return;
      el.find(".hs-room").each((_,node)=>{const value=values[stays.get(node.dataset.room)];if(value!==undefined)$(node).find(".hs-room-info").append(`<small>${e(value.shared?__("Saldo compartido de grupo"):__("Saldo"))}: <strong>${e(this.amount(value.amount,currency))}</strong></small>`);});
    }catch{if(current())el.find(".hs-room").each((_,node)=>{if(stays.has(node.dataset.room))$(node).find(".hs-room-info").append(`<small>${e(__("Consulte el saldo actualizado en Ver estancia."))}</small>`);});}
  };
  Desk.prototype.home_board_access=function(){return this.data.pages.some(p=>p.route==="hospitality-stays")&&(this.allowed("stay")||this.allowed("finance")||this.allowed("report"));};
  Desk.prototype.render_home=function(el){
    const rooms=this.data.rooms||[],counts={vacant:0,occupied:0,blocked:0,inactive:0},occupiedRooms=new Set((this.data.occupied||[]).map(row=>row.room));
    for(const room of rooms){const status=inactive(room)?"inactive":blocked(room,this.data)?"blocked":occupiedRooms.has(room.name)?"occupied":"vacant";counts[status]++;}
    const operable=counts.occupied+counts.vacant,ready=rooms.filter(r=>state(r,this.data)==="vacant"&&r.cleaning_status==="Clean").length;
    const toPrepare=counts.vacant-ready,occupancy=operable?Math.round(counts.occupied/operable*100):0;
    const segments=[["occupied",__("Ocupadas"),counts.occupied],["ready",__("Listas"),ready],["prepare",__("Por preparar"),toPrepare],
      ["blocked",__("Bloqueadas"),counts.blocked],["inactive",__("Inactivas"),counts.inactive]];
    const metrics=[[__("Habitaciones ocupadas"),counts.occupied,__("Estancias activas"),"hospitality-reception"],
      [__("Limpias sin ocupación ni bloqueo"),ready,__("Revise fechas antes de asignar"),"hospitality-reception"],
      [__("Limpieza pendiente"),this.data.cleaning.filter(t=>t.status!=="Completed").length,__("Habitaciones por preparar"),"hospitality-housekeeping"],
      [__("Mantenimiento pendiente"),this.data.maintenance.filter(t=>t.status!=="Completed").length,__("Órdenes por completar"),"hospitality-maintenance"]];
    el.html(`<section class="hs-welcome"><div><h2>${e(__("Su jornada de un vistazo"))}</h2><p>${e(__("Panel operativo actual · {0}",[this.prop.property_name||this.property]))}</p></div>${this.allowed("reserve")?this.button("reserve",__("Reservar"),"","primary"):""}</section>`+
      `<section class="hs-section hs-home-capacity" aria-label="${e(__("Ocupación actual"))}"><div class="hs-home-capacity-head"><div><h2>${e(__("Ocupación actual"))}</h2><p>${e(__("{0} de {1} habitaciones operativas ocupadas",[counts.occupied,operable]))}</p></div><strong>${occupancy}%</strong></div>`+
      `<div class="hs-home-capacity-bar" role="img" aria-label="${e(__("Distribución de {0} habitaciones",[rooms.length]))}">${rooms.length?segments.map(([key,,value])=>value?`<span class="is-${key}" style="width:${(value/rooms.length*100).toFixed(2)}%"></span>`:"").join(""):""}</div>`+
      `<div class="hs-home-capacity-legend">${segments.map(([key,label,value])=>`<span><i class="is-${key}" aria-hidden="true"></i>${e(label)} <strong>${value}</strong></span>`).join("")}</div><p class="hs-note">${e(__("La ocupación usa habitaciones activas sin bloqueo; la disponibilidad de fechas se confirma al consultar el intervalo."))}</p></section>`+
      (this.home_board_access()?`<section class="hs-section hs-home-pending" aria-label="${e(__("Llegadas y salidas pendientes"))}"></section>`:"")+
      `<div class="hs-metrics">${metrics.map(([label,value,help,route])=>{const target=this.data.pages.some(p=>p.route===route),tag=target?"a":"article";return `<${tag}${target?` href="/app/${e(route)}"`:""}><span>${e(label)}</span><strong>${value}</strong><small>${e(help)}</small>${target?`<small>${e(__("Abrir vista →"))}</small>`:""}</${tag}>`;}).join("")}</div><section class="hs-section"><h2>${e(__("Accesos para su jornada"))}</h2><div class="hs-shortcuts">${this.data.pages.filter(p=>p.route!==this.route).map(p=>`<a href="/app/${e(p.route)}"><strong>${this.page_icon(p)}${e(__(p.title))}</strong><span>${e(__("Ver operación →"))}</span></a>`).join("")}</div></section>`);
    this.homeContext={el,property:this.property};if(this.home_board_access())this.load_home_pending();
  };
  Desk.prototype.action_home_queue=function(view){
    if(!["arrivals","departures","hosted","accounts"].includes(view)||!this.home_board_access())return;
    this.save_preference("stay-board",{view,date:this.calendar_day(),offset:0});frappe.set_route("hospitality-stays");
  };
  Desk.prototype.action_home_pending=function(){return this.load_home_pending();};
  Desk.prototype.load_home_pending=async function(){
    const context=this.homeContext;if(!context||context.loading||!this.home_board_access())return;
    const date=this.calendar_day(),target=context.el.find(".hs-home-pending"),property=context.property;
    const current=()=>this.homeContext===context&&this.property===property;
    context.loading=true;target.attr("aria-busy","true").html(`<p role="status">${e(__("Consultando llegadas y salidas…"))}</p>`);
    try{
      const data=await this.call("stay_board",{property_name:property,view:"arrivals",date,offset:0,page_length:1});if(!current())return;
      if(data?.property!==property||data?.date!==date||data?.view!=="arrivals"||!["arrivals","departures","hosted","accounts"].every(key=>Number.isInteger(data?.counts?.[key])&&data.counts[key]>=0))throw Error("Unexpected Home context");
      const queues=[["arrivals",__("Llegadas pendientes"),__("Ver llegadas")],["departures",__("Salidas pendientes"),__("Ver salidas")],
        ["hosted",__("Alojados ahora"),__("Ver alojados")],["accounts",__("Cuentas abiertas"),__("Ver cuentas")]];
      target.html(`<h2>${e(__("Operación de hoy"))}</h2><p>${e(__("Pendientes hasta {0} · {1}",[date.split("-").reverse().join("/"),this.prop.time_zone]))}</p><div class="hs-home-queues">${queues.map(([view,label,action])=>`<article class="${["arrivals","departures"].includes(view)&&data.counts[view]?"has-pending":""}"><h3>${e(label)}</h3><strong>${data.counts[view]}</strong>${this.button("home_queue",action,view)}</article>`).join("")}</div><p class="hs-note">${e(__("Las llegadas y salidas incluyen pendientes anteriores. Las cuentas abiertas se cuentan una vez, incluso si son compartidas."))}</p>${this.button("home_pending",__("Actualizar pendientes"))}`);
    }catch{if(current())target.html(`<div role="alert"><p>${e(__("No se pudieron consultar las llegadas y salidas. Vuelva a intentarlo."))}</p>${this.button("home_pending",__("Reintentar pendientes"))}</div>`);}
    finally{context.loading=false;if(current()){this.homeCheckedAt=this.serverNow();target.attr("aria-busy","false");}}
  };
  const timers=Desk.prototype.updateTimers;
  Desk.prototype.updateTimers=function(){
    timers.call(this);
    if(this.route==="hospitality-home"&&this.homeContext&&!this.busy&&this.serverNow()-this.homeCheckedAt>=60000)this.load_home_pending();
  };
})();
