/* Native Desk Pages. Server-confirmed operations, keyboard controls and scoped refresh. */
window.hospitality_suite = window.hospitality_suite || {};
(() => {
  const esc = (value) => frappe.utils.escape_html(String(value ?? ""));
  // A denied/full browser store must never prevent operational Pages from opening.
  const memory=new Map(),unsaved=new Set();
  const storage={getItem(key){if(unsaved.has(key))return memory.get(key)??null;try{return localStorage.getItem(key)??memory.get(key)??null;}catch{return memory.get(key)??null;}},
    setItem(key,value){memory.set(key,String(value));try{localStorage.setItem(key,String(value));unsaved.delete(key);}catch{unsaved.add(key);}}};
  window.hospitality_suite.ui_storage=storage;
  const serverMessage=error=>Boolean(error?._server_messages||error?._error_message||error?.responseJSON?._server_messages||error?.responseJSON?._error_message);
  const labels = {Clean:__("Limpia"), Dirty:__("Sucia"), Cleaning:__("En limpieza"), Inspection:__("Pendiente de inspección"),
    Active:__("Alojado"), "Checked Out":__("Salida registrada"), Confirmed:__("Confirmada"), Hold:__("Retención temporal"),
    Invoiced:__("Facturado"), Reversed:__("Revertido"), Draft:__("Borrador"), "Checked In":__("Entrada registrada"), Completed:__("Completada"), Cancelled:__("Cancelada"), "No Show":__("No presentada"),
    Pending:__("Pendiente"), Scheduled:__("Programado"), "In Progress":__("En proceso"), Open:__("Abierto"), Closed:__("Cerrado"), Review:__("Por revisar"),Resolved:__("Resuelto"),Failed:__("Fallida"),
    Requested:__("Solicitado"), Delivered:__("Entregado"), Returned:__("Devuelto"), Posted:__("Contabilizado"), Payment:__("Cobro"), Advance:__("Anticipo"), Guarantee:__("Garantía"),
    "Guarantee Refund":__("Devolución de garantía"), "Guarantee Applied":__("Garantía aplicada (sin nuevo ingreso)"), Refund:__("Devolución"), Normal:__("Normal"), High:__("Alta"), Urgent:__("Urgente"),
    Priced:__("Con precio"), Missing:__("Sin precio"), Inactiva:__("Inactiva"), "Fuera de servicio":__("Fuera de servicio"), "Sin ocupación":__("Sin ocupación")};
  const title = (s) => __(labels[s] || s);
  const field = (fieldname, label, fieldtype="Data", extra={}) => ({fieldname,label:__(label),fieldtype:["Date","Datetime"].includes(fieldtype)?"Data":fieldtype,_hsDateTime:fieldtype==="Datetime",_hsDate:fieldtype==="Date",...extra});
  const select = (name,label,rows,labelKey="name",required=true) => field(name,label,"Select",{reqd:required,_hsDataOptions:true,options:[{value:"",label:__("Seleccione…")},...rows.map(r=>({value:r.name,label:r[labelKey] || r.name}))]});
  // Native Select inserts option labels as HTML and translates every label.
  // Operational selectors need text nodes and must preserve master-data names.
  const safeSelectOptions=function(value){
    let rows=this.df.options||[];if(typeof rows==="string")rows=rows.split("\n");
    const fingerprint=JSON.stringify(rows);if(fingerprint===this.last_options)return;
    this.last_options=fingerprint;
    if(!this.$input)return;
    const selected=this.$input.val();this.$input.empty();
    for(const raw of rows){
      const object=raw!==null&&typeof raw==="object",code=object?(raw.value??""):raw??"",label=object?(raw.label??code):code;
      const display=this.df._hsDataOptions?String(label):__(String(label),null,this.df.context||this.df.parent||this.doctype);
      const option=$("<option>").text(display).attr("value",code).prop("disabled",Boolean(object&&raw.disabled)).prop("selected",Boolean(object&&raw.selected));
      this.$input.append(option);
    }
    if(value===undefined&&selected&&rows.some(r=>String(typeof r==="object"?(r.value??""):r)===String(selected)))this.$input.val(selected);
    this.$input.trigger("select-change");
  };
  window.hospitality_suite.safe_select_options=safeSelectOptions;
  // FieldGroup evaluates dependencies with get_values(true). Its required-field
  // refresh can replace a focused input before its blur has committed the value.
  // A Data control commits on a debounce, so a just-blurred required editor
  // can also still have an empty model. Keep those pending inputs across the
  // read, including controls in another tab. Native dependency changes win.
  const preserveEditingValue=(dialog,read)=>function(...args){
    const active=typeof document==='undefined'?null:document.activeElement;
    const editable=(control,input)=>Boolean(control&&!control.df.hidden&&!control.df.hidden_due_to_dependency&&!control.df.read_only&&input?.isConnected&&!input.disabled&&!input.readOnly);
    const saved=Object.values(dialog.fields_dict||{}).flatMap(control=>{
      const input=control.$input?.[0],focused=input===active;
      if(!editable(control,input)||!(focused?input.getClientRects?.().length:control.df.reqd&&!control.value&&(input.value||input.checked)))return [];
      return [{control,input,focused,value:input.value,checked:input.checked,selection:focused&&typeof input.selectionStart==='number'?[input.selectionStart,input.selectionEnd]:null}];
    });
    try{return read.apply(this,args);}
    finally{for(const {control,input,focused,value,checked,selection} of saved)if(editable(control,input)&&control.$input?.[0]===input&&(focused?input.getClientRects?.().length:!control.value)){
      if(['checkbox','radio'].includes(input.type))input.checked=checked;else input.value=value;
      if(selection&&document.activeElement===input)input.setSelectionRange?.(...selection);
    }}
  };
  window.hospitality_suite.preserve_editing_value=preserveEditingValue;
  const modeOptions=options=>(Array.isArray(options)?options:String(options||"").split("\n")).map(option=>{
    const code=typeof option==="object"?option.value:option;
    const label={Hotel:__("Hotel"),Motel:__("Por tiempo"),Mixed:__("Hotel y por tiempo")}[code];
    return label?{...(typeof option==="object"?option:{}),value:code,label}:option;
  });
  window.hospitality_suite.mode_options=modeOptions;
  const actionOwners=new Map();let ownerSequence=0,actionObserver;
  const actionOwner=desk=>{
    if(!desk.actionOwner){desk.actionOwner=`hs-page-${++ownerSequence}`;actionOwners.set(desk.actionOwner,desk);}
    if(!actionObserver&&typeof MutationObserver!=="undefined"&&typeof document!=="undefined"&&document.body){
      // Frappe can recreate an HTML field after the action's finally block.
      // Newly inserted dialog buttons must use the owner's current state.
      actionObserver=new MutationObserver(records=>{
        for(const record of records)for(const node of record.addedNodes){
          if(node.nodeType!==1)continue;
          const buttons=[...(node.matches('button[data-hs-owner]')?[node]:[]),...node.querySelectorAll('button[data-hs-owner]')];
          for(const button of buttons){const owner=actionOwners.get(button.getAttribute('data-hs-owner'));if(owner)button.disabled=!navigator.onLine||owner.page_busy();}
        }
      });
      actionObserver.observe(document.body,{childList:true,subtree:true});
    }
    return desk.actionOwner;
  };
  class Desk {
    constructor(wrapper, route) {
      this.wrapper = wrapper;
      this.route = route;
      this.page = frappe.ui.make_app_page({parent:wrapper,title:__("Hospitality Suite"),single_column:true,hide_sidebar:true});
      this.root = $('<div class="hs-app"></div>').appendTo(this.page.main);
      this.property = storage.getItem("hs-property") || "";
      this.query = "";
      this.busy = false;
      this.load();
      frappe.realtime.on("hospitality_changed", (event) => {if (event.property === this.property) this.scheduleRefresh();});
      if (frappe.realtime.socket){
        frappe.realtime.socket.on("connect",()=>{this.connection();this.scheduleRefresh();});
        for(const event of ["disconnect","connect_error"])frappe.realtime.socket.on(event,()=>this.connection());
      }
      window.addEventListener("online",()=>this.action_reload());
      window.addEventListener("offline",()=>this.connection());
      window.addEventListener("focus",()=>this.resumeClock());
      document.addEventListener("visibilitychange",()=>this.resumeClock(true));
      $(wrapper).on("show",()=>this.scheduleRefresh());
      this.timer=setInterval(()=>{if($(wrapper).is(":visible")) this.updateTimers();},30000);
    }
    async call(method,args={}) {return (await frappe.call({method:`hospitality_suite.api.${method}`,args})).message;}
    async load() {
      const sequence=this.loadSequence=(this.loadSequence||0)+1;
      let selected=this.property;
      this.refreshPending=false;
      this.loading=true;
      try {
        this.root.attr("aria-busy","true");
        this.connection();
        if(!this.data) this.root.html(`<div class="hs-loading" role="status">${frappe.utils.escape_html(__("Cargando la operación…"))}</div>`);
        const initial=!this.data;
        let data=await this.call("bootstrap",{property_name:initial?undefined:selected || undefined});
        if(sequence!==this.loadSequence)return;
        if(selected && !data.properties.some(p=>p.name===selected)) selected="";
        if(!selected && data.properties.length) {selected=data.properties[0].name;data=await this.call("bootstrap",{property_name:selected});}
        else if(initial && selected)data=await this.call("bootstrap",{property_name:selected});
        if(sequence!==this.loadSequence)return;
        this.property=selected;
        this.data=data;
        this.syncClock(data.server_time,data.system_timezone);
        this.prop=data.properties.find(p=>p.name===this.property);
        storage.setItem("hs-property",this.property);
        this.render();
      } catch(error) {
        if(sequence!==this.loadSequence)return;
        this.root.html(`<div class="hs-empty" role="alert"><h2>${frappe.utils.escape_html(__("No se pudo actualizar la operación"))}</h2><p>${frappe.utils.escape_html(__("Compruebe su conexión e intente nuevamente. Los movimientos requieren confirmación del servidor."))}</p><button class="btn btn-primary" data-act="reload">${frappe.utils.escape_html(__("Reintentar"))}</button></div>`);
        this.bind();
      } finally {if(sequence===this.loadSequence){this.loading=false;this.root.attr("aria-busy",String(this.page_busy()));this.connection();if(this.refreshPending&&!this.page_busy())this.scheduleRefresh();}}
    }
    page_busy(){return Boolean(this.busy||this.loading||this.actionPending);}
    scheduleRefresh() {this.refreshPending=true;clearTimeout(this.refreshTimer);this.refreshTimer=setTimeout(()=>{if(!this.page_busy() && $(this.wrapper).is(":visible"))this.load();},500);}
    allowed(action){return this.data.actions.includes(action);}
    action_owner(){return actionOwner(this);}
    button(action,label,id="",kind="secondary") {return `<button type="button" class="btn btn-${kind} hs-action" data-act="${esc(action)}" data-id="${esc(id)}" data-hs-owner="${this.action_owner()}"${this.page_busy()?" disabled":""}>${esc(__(label))}</button>`;}
    badge(status) {return `<span class="hs-badge hs-${esc(status.toLowerCase().replaceAll(" ","-"))}">${esc(title(status))}</span>`;}
    roomName(name) {return this.data.rooms.find(r=>r.name===name)?.room_number || name;}
    guestName(name) {return this.prop.discreet_mode ? __("Huésped registrado") : (this.data.guests || []).find(g=>g.name===name)?.full_name || __("Huésped registrado");}
    itemName(name) {const row=(this.data.items||[]).find(r=>r.name===name);return (row?.display_name??row?.item_name)||__("Artículo del catálogo");}
    bookingLabel(name) {const booking=(this.data.bookings||[]).find(r=>r.name===name);if(!booking)return __("Reserva registrada");const who=this.prop.discreet_mode?__("Huésped registrado"):booking.guest?this.guestName(booking.guest):(this.data.customers||[]).find(r=>r.name===booking.customer)?.customer_name||__("Cliente registrado");return who+" · "+this.date(booking.starts_at);}
    amount(value,currency) {return format_currency(value,currency || this.prop?.currency);}
    date(value) {return value ? moment.tz(value,this.data.system_timezone).tz(this.prop.time_zone).format("DD/MM/YYYY HH:mm") : "—";}
    empty(message=__("No hay pendientes en esta vista.")){return `<div class="hs-empty"><span class="hs-empty-icon" aria-hidden="true">✓</span><h3>${esc(__(message))}</h3><p>${frappe.utils.escape_html(__("La información se actualiza al registrar movimientos."))}</p></div>`;}
    render() {
      const current=this.data.pages.find(p=>p.route===this.route);
      this.page.set_title(__(current?.title || "Hospitality Suite"));
      this.root.html(`<div class="hs-layout"><aside class="hs-sidebar" aria-label="${frappe.utils.escape_html(__("Navegación de alojamiento"))}"><div class="hs-brand"><span class="hs-brand-mark" aria-hidden="true">H</span><div><strong>${esc(this.prop?.brand_name||"Hospitality")}</strong><small>${frappe.utils.escape_html(__("OPERACIÓN DIARIA"))}</small></div></div><nav>${this.data.pages.map(p=>`<a href="/app/${esc(p.route)}" class="${p.route===this.route?"is-active":""}" ${p.route===this.route?'aria-current="page"':""}>${esc(__(p.title))}</a>`).join("")}</nav><div class="hs-sidebar-foot">${esc(this.prop?.time_zone || __("Configuración inicial"))}<br><span id="hs-connection" role="status"></span></div></aside><main class="hs-main"><header class="hs-header"><div><div class="hs-eyebrow">${esc(__(this.prop?.mode === "Motel" ? __("OPERACIÓN POR TIEMPO") : __("GESTIÓN DE ALOJAMIENTO")))}</div><h1>${esc(__(current?.title || "Hospitality Suite"))}</h1><p>${frappe.utils.escape_html(__("Fecha operativa:"))} <strong>${esc(this.prop?.business_date || __("Pendiente de configurar"))}</strong></p></div><div class="hs-header-actions"><label for="hs-property">${frappe.utils.escape_html(__("Establecimiento"))}</label><select id="hs-property" class="form-control">${this.data.properties.map(p=>`<option value="${esc(p.name)}" ${p.name===this.property?"selected":""}>${esc(p.property_name)}</option>`).join("")}</select>${this.button("reload",__("Actualizar"))}</div></header><div class="hs-content" aria-live="polite"></div><footer class="hs-footer">${frappe.utils.escape_html(__("Hora de referencia del servidor:"))} ${esc(this.data.server_time)} · ${esc(this.prop?.currency || "")}</footer></main></div>`);
      const content=this.root.find(".hs-content");
      if(!this.prop) content.html(`<div class="hs-empty"><h2>${frappe.utils.escape_html(__("Prepare su primer establecimiento"))}</h2><p>${frappe.utils.escape_html(__("Configure compañía, habitaciones y políticas antes de operar."))}</p>${this.data.can_create_property?this.button("new_property",__("Crear establecimiento"),"","primary"):__("Solicite acceso al administrador del sistema.")}</div>`);
      else {
        const name=this.route.replace("hospitality-","");
        (this[`render_${name}`] || this.render_home).call(this,content);
      }
      this.bind();this.connection();this.updateTimers();
    }
    connection() {
      const message=!navigator.onLine?__("Sin conexión · operación pausada"):frappe.realtime.socket?.connected?__("● Tiempo real conectado"):__("Sin tiempo real · pulse Actualizar");
      const progress=this.busy?__("Guardando operación… Espere la confirmación."):this.loading?__("Actualizando información… Espere un momento."):this.actionPending?__("Preparando acción… Espere un momento."):"";
      this.root.find("#hs-connection").text(message);
      let banner=this.root.find(".hs-connection-banner");if(!banner.length)banner=$('<span class="hs-connection-banner" role="status"></span>').appendTo(this.root.find(".hs-header-actions"));
      banner.text(navigator.onLine&&progress?progress:message).attr("data-state",progress?"busy":"ready");
      this.root.attr("aria-busy",String(this.page_busy()));
      this.root.find("[data-act],#hs-property").prop("disabled",!navigator.onLine || this.page_busy());
      // Native dialogs are attached outside the Page root. Release their
      // generated action buttons with the Page that owns them, too.
      if(this.actionOwner&&typeof document!=="undefined")for(const button of document.querySelectorAll(`[data-hs-owner="${this.actionOwner}"]`))button.disabled=!navigator.onLine||this.page_busy();
    }
    async run_action(action,id="",trigger=null) {
      if(this.page_busy() || !navigator.onLine || typeof this[`action_${action}`]!=="function")return;
      let status;
      if(typeof document!=="undefined"&&trigger?.isConnected){
        status=document.createElement("span");status.className="hs-action-status";status.setAttribute("role","status");status.textContent=__("Preparando acción… Espere un momento.");
        trigger.insertAdjacentElement("afterend",status);
      }
      this.actionPending=true;this.connection();
      try{return await this[`action_${action}`](id);}
      catch(error){if(!serverMessage(error))frappe.msgprint({title:__("No se completó la acción"),message:__("Revise los datos y vuelva a intentarlo. No confirme el movimiento hasta recibir respuesta del servidor."),indicator:"red"});}
      finally{status?.remove();this.actionPending=false;this.connection();if(this.refreshPending)this.scheduleRefresh();}
    }
    bind() {
      this.root.off("click").on("click","[data-act]",async(event)=>{
        const button=$(event.currentTarget); const action=button.data("act"), id=String(button.data("id") || "");
        await this.run_action(action,id,event.currentTarget);
      });
      this.root.find("#hs-property").on("change",e=>{this.property=e.target.value;this.data=null;this.load();});
      this.root.find("#hs-search").on("input",e=>{if(this.update_room_filter)this.update_room_filter("query",e.target.value);else{this.query=e.target.value.toLowerCase();this.filterRooms();}});
      this.root.find("#hs-clean-filter").on("change",e=>{if(this.update_room_filter)this.update_room_filter("clean",e.target.value);else{storage.setItem(`hs-clean-${this.property}`,e.target.value);this.filterRooms();}});
      this.root.find("#hs-booking-history").on("change",e=>{this.bookingHistory=e.target.checked;this.render();});
    }
    render_home(el) {
      const occupied=this.data.occupied.length, available=this.data.rooms.filter(r=>r.active && r.cleaning_status==="Clean" && !this.data.occupied.some(s=>s.room===r.name)).length;
      el.html(`<section class="hs-welcome"><div><h2>${frappe.utils.escape_html(__("Todo listo para atender"))}</h2><p>${frappe.utils.escape_html(__("Habitaciones, personas y pendientes en un solo lugar."))}</p></div>${this.allowed("reserve")?this.button("reserve",__("Reservar"),"","primary"):""}</section><div class="hs-metrics">${[[__("Habitaciones ocupadas"),occupied,__("Estancias activas")],[__("Limpias sin ocupación"),available,__("Revise el intervalo antes de asignar")],[__("Limpieza pendiente"),this.data.cleaning.filter(t=>t.status!=="Completed").length,__("Habitaciones por preparar")],[__("Mantenimiento"),this.data.maintenance.filter(t=>t.status!=="Completed").length,__("Incidencias abiertas")]].map(([label,value,help])=>`<article><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(__(help))}</small></article>`).join("")}</div><section class="hs-section"><h2>${frappe.utils.escape_html(__("Accesos para su jornada"))}</h2><div class="hs-shortcuts">${this.data.pages.filter(p=>p.route!==this.route).map(p=>`<a href="/app/${esc(p.route)}"><strong>${esc(__(p.title))}</strong><span>${frappe.utils.escape_html(__("Ver operación →"))}</span></a>`).join("")}</div></section>`);
    }
    render_reception(el) {
      const filter=this.roomFilters?.clean??storage.getItem(`hs-clean-${this.property}`)??"";
      el.html(`<div class="hs-toolbar"><div><label for="hs-search" class="sr-only">${frappe.utils.escape_html(__("Buscar habitación, piso o categoría"))}</label><input id="hs-search" class="form-control" placeholder="${frappe.utils.escape_html(__("Buscar habitación, piso o categoría…"))}" value="${esc(this.query)}"></div><select id="hs-clean-filter" class="form-control" aria-label="${frappe.utils.escape_html(__("Filtrar por limpieza"))}"><option value="">${frappe.utils.escape_html(__("Todos los estados"))}</option>${["Clean","Dirty","Cleaning","Inspection"].map(s=>`<option value="${s}" ${filter===s?"selected":""}>${esc(title(s))}</option>`).join("")}</select>${this.allowed("reserve")?this.button("reserve",__("Reservar"),"","primary")+this.button("walk_in",__("Registrar entrada inmediata")):""}</div>${this.data.occupied.length?`<p class="text-muted hs-countdown-help">${esc(__("Los contadores son orientativos; revise los cargos antes de confirmar."))}</p>`:""}<div class="hs-room-grid">${this.data.rooms.map(room=>{
        const stay=this.data.occupied.find(s=>s.room===room.name), block=this.data.blocks.find(b=>b.room===room.name && b.starts_at<=this.data.server_time && (!b.ends_at || b.ends_at>this.data.server_time));
        const cat=this.data.categories.find(c=>c.name===room.category)?.category_name || "";
        const arrival=(this.data.room_arrivals||[]).find(row=>row.room===room.name);
        const inactive=room.active===0||room.active===false;
        return `<article class="hs-room ${stay?"is-occupied":""} ${block?"is-blocked":""}" data-room="${esc(room.name)}" data-search="${esc([room.room_number,cat,room.floor,room.zone].join(" ").toLowerCase())}" data-clean="${esc(room.cleaning_status)}"><div class="hs-room-top"><span>${frappe.utils.escape_html(__("HABITACIÓN"))}</span><strong>${esc(room.room_number)}</strong><small>${esc(cat)}${room.floor?" · "+esc(__("Piso"))+" "+esc(room.floor):""}</small></div><div class="hs-room-tags">${this.badge(stay?"Active":inactive?"Inactiva":block?"Fuera de servicio":"Sin ocupación")}${this.badge(room.cleaning_status)}</div><div class="hs-room-info">${block&&!block.ends_at?`<p>${esc(__("Hasta reapertura autorizada"))}</p>`:this.roomTiming(stay,arrival)}</div><div class="hs-room-actions">${stay?this.button("detail",__("Ver estancia"),stay.name):inactive?`<small>${esc(__("Habitación desactivada"))}</small>`:block&&!block.ends_at?`<small>${esc(__("Reapertura pendiente"))}</small>`:arrival?this.button("booking",__("Ver reserva"),arrival.booking):this.allowed("reserve")?this.button("reserve",__("Reservar"),room.name):""}</div></article>`;
      }).join("")}</div><p class="hs-filter-empty" hidden>${frappe.utils.escape_html(__("No se encontraron habitaciones con esos filtros."))}</p>`);
      this.filterRooms();
    }
    filterRooms() {let shown=0;const clean=this.root.find("#hs-clean-filter").val()||"";this.root.find(".hs-room").each((_,node)=>{const show=(!this.query||node.dataset.search.includes(this.query))&&(!clean||node.dataset.clean===clean);$(node).toggle(show);if(show)shown++;});this.root.find(".hs-filter-empty").prop("hidden",shown>0);}
    syncClock(serverTime,timeZone) {this.clockAnchor={epoch:moment.tz(serverTime,timeZone).valueOf(),monotonic:performance.now()};}
    serverNow() {return this.clockAnchor?this.clockAnchor.epoch+Math.max(0,performance.now()-this.clockAnchor.monotonic):NaN;}
    resumeClock(force=false) {if(navigator.onLine&&!document.hidden&&$(this.wrapper).is(":visible")&&(force||!this.clockAnchor||performance.now()-this.clockAnchor.monotonic>60000))this.scheduleRefresh();}
    arrivalState(value) {
      const delta=moment.tz(value,this.data.system_timezone).valueOf()-this.serverNow();
      return !Number.isFinite(delta)?__("Llegada por actualizar"):delta<=0?__("Llegada pendiente · hora prevista superada"):
        delta<=3600000?__("Llegada próxima · sin entrada registrada"):__("Próxima llegada pendiente");
    }
    updateTimers() {
      const now=this.serverNow();
      this.root.find("[data-countdown]").each((_,node)=>{
        const delta=moment.tz(node.dataset.countdown,this.data.system_timezone).valueOf()-now;
        if(!Number.isFinite(delta)){node.textContent=__("Tiempo por actualizar");return;}
        const minutes=Math.floor(Math.abs(delta)/60000);
        node.textContent=(delta>0&&delta<=3600000?__("Salida próxima · "):"")+(delta===0?__("Hora prevista de salida alcanzada"):delta>0?
          minutes?__("Tiempo restante: {0} h {1} min",[Math.floor(minutes/60),minutes%60]):__("Tiempo restante: menos de 1 min"):
          minutes?__("Tiempo excedido: {0} min",[minutes]):__("Tiempo excedido: menos de 1 min"));
      });
      if(this.route==="hospitality-reception")this.root.find("[data-room-arrival]").each((_,node)=>{node.textContent=this.arrivalState(node.dataset.roomArrival);});
    }
    table(headers,rows,emptyMessage){return rows.length?`<div class="hs-table-wrap"><table class="hs-table"><thead><tr>${headers.map(h=>`<th scope="col">${esc(__(h))}</th>`).join("")}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map((v,i)=>`<td data-label="${esc(__(headers[i]))}">${v}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`:this.empty(emptyMessage);}
    render_reservations(el) {
      const bookings=(this.data.bookings||[]).filter(b=>b.status!=="Draft"&&(this.bookingHistory||!["Cancelled","No Show","Completed"].includes(b.status)));
      const drafts=this.allowed("reserve")?(this.data.bookings||[]).filter(b=>b.status==="Draft"):[];
      const emptyMessage=this.bookingHistory?__("No hay reservas en el historial."):__("No hay reservas confirmadas ni retenciones vigentes.");
      const listing=this.table([__("Reserva"),__("Llegada / salida"),__("Canal"),__("Estado"),__("Importe"),__("Acciones")],bookings.map(b=>[esc(this.bookingLabel(b.name)),`${esc(this.date(b.starts_at))}<br>${esc(this.date(b.ends_at))}`,esc(b.channel),this.badge(b.status),b.draft_data?esc(__("Sin cotizar")):this.amount(b.amount,b.currency),this.button("booking",__("Ver reserva"),b.name)]),emptyMessage);
      const draftList=drafts.length?`<section class="hs-section"><h2>${esc(__("Borradores por completar"))} (${drafts.length})</h2><p>${esc(__("No ocupan cupo ni fijan precio. Retome uno para completar datos y revisar la cotización."))}</p>${this.table([__("Solicitante"),__("Entrada prevista"),__("Precio"),__("Acciones")],drafts.map(b=>[esc(b.guest?this.guestName(b.guest):(this.data.customers||[]).find(c=>c.name===b.customer)?.customer_name||__("Por definir")),esc(b.starts_at?this.date(b.starts_at):__("Por definir")),esc(__("Sin cotizar")),this.button("booking",__("Retomar borrador"),b.name)]))}</section>`:"";
      el.html(`<div class="hs-toolbar"><div><h2>${frappe.utils.escape_html(__("Reservas vigentes"))}</h2><p>${frappe.utils.escape_html(__("Reservas individuales y grupales; las retenciones liberan cupo al vencer."))}</p><label><input id="hs-booking-history" type="checkbox" ${this.bookingHistory?"checked":""}> ${frappe.utils.escape_html(__("Mostrar historial"))}</label></div>${this.button("reserve",__("Reservar"),"","primary")}${this.button("availability",__("Buscar disponibilidad"))}</div>${draftList}${listing}`);
    }
    render_stays(el) {el.html(`<div class="hs-toolbar"><h2>${frappe.utils.escape_html(__("Huéspedes alojados y cuentas"))}</h2>${this.button("walk_in",__("Registrar entrada inmediata"),"","primary")}</div>${this.table([__("Habitación"),__("Huésped"),__("Salida prevista"),__("Estado"),__("Acciones")],(this.data.stays||[]).map(s=>[esc(this.roomName(s.room)),esc(this.guestName(s.guest)),esc(this.date(s.ends_at)),this.badge(s.status),this.button("detail",__("Ver cuenta"),s.name)]))}`);}
    render_cashier(el) {
      const payments=this.data.payments||[];
      const recent=payments.length||!(this.data.native_pos||[]).length?`<h2 class="hs-section-title">${frappe.utils.escape_html(__("Movimientos recientes"))}</h2>${this.table([__("Origen"),__("Concepto"),__("Importe"),__("Estado"),__("Comprobante")],payments.map(p=>[esc(p.stay?__("Habitación")+" "+this.roomName((this.data.stays||[]).find(t=>t.name===p.stay)?.room):p.booking?this.bookingLabel(p.booking):__("Venta / caja")),esc(title(p.kind)),this.amount(p.amount,p.currency),this.badge(p.status),esc(p.payment_entry||p.journal_entry||"—")+(this.receiptLink?"<br>"+this.receiptLink(p.name):"")]))}`:"";
      el.html(`<div class="hs-toolbar"><div><h2>${frappe.utils.escape_html(__("Turnos y cobros"))}</h2><p>${frappe.utils.escape_html(__("Anticipos, ingresos y garantías conservan su origen contable."))}</p></div>${this.button("open_shift",__("Abrir turno"),"","primary")}${this.button("payment",__("Cobrar"))}</div>${this.table([__("Responsable"),__("Apertura"),__("Moneda"),__("Efectivo esperado"),__("Estado"),__("Acciones")],(this.data.shifts||[]).map(s=>[esc(s.cashier),esc(this.date(s.opened_at)),esc(s.currency),Object.entries(s.expected_by_currency).map(([c,v])=>this.amount(v,c)).join("<br>"),this.badge(s.status),s.status!=="Closed"?this.button("close_shift",__("Arqueo y cierre"),s.name):this.button("print_shift",__("Imprimir"),s.name)]))}${recent}`);
    }
    render_housekeeping(el) {const tasks=this.data.cleaning.filter(t=>t.status!=="Completed");el.html(`<div class="hs-toolbar"><div><h2>${frappe.utils.escape_html(__("Preparar habitaciones"))}</h2><p>${frappe.utils.escape_html(__("Inicie la tarea, complete la revisión y solicite inspección."))}</p></div><span>${tasks.length} ${frappe.utils.escape_html(__("pendientes"))}</span></div><div class="hs-task-grid">${tasks.map(t=>`<article class="hs-task"><div class="hs-task-top"><strong>${frappe.utils.escape_html(__("Habitación"))} ${esc(this.roomName(t.room))}</strong>${this.badge(t.priority)}</div><p>${this.badge(t.status)}</p><p>${esc(t.assigned_to || __("Sin responsable"))}</p><p>${esc(t.notes || __("Limpieza y revisión de habitación"))}</p>${this.button("cleaning",t.status==="Pending"?__("Iniciar limpieza"):t.status==="Inspection"?__("Inspeccionar"):__("Marcar limpia"),t.name,"primary")}</article>`).join("") || this.empty(__("Las habitaciones están al día"))}</div>`);}
    render_maintenance(el) {el.html(`<div class="hs-toolbar"><div><h2>${frappe.utils.escape_html(__("Incidencias y bloqueos"))}</h2><p>${frappe.utils.escape_html(__("Los bloqueos respetan las reservas y estancias existentes."))}</p></div>${this.allowed("maintain")?this.button("maintenance",__("Registrar incidencia"),"","primary"):""}</div>${this.table([__("Habitación"),__("Incidencia"),__("Período"),__("Estado"),__("Acción")],this.data.maintenance.map(t=>[esc(this.roomName(t.room)),esc(t.title),`${esc(this.date(t.starts_at))}<br>${esc(this.date(t.ends_at))}`,this.badge(t.status),t.status!=="Completed"&&this.allowed("maintain")?this.button("maintenance",__("Actualizar"),t.name):"—"]))}`);}
    render_services(el) {el.html(`<div class="hs-toolbar"><div><h2>${frappe.utils.escape_html(__("Consumos y servicios"))}</h2><p>${frappe.utils.escape_html(__("La entrega genera el cargo y, si corresponde, una única salida de inventario."))}</p></div>${this.button("service",__("Agregar consumo"),"","primary")}</div>${this.table([__("Estancia"),__("Artículo"),__("Cantidad"),__("Importe"),__("Estado"),__("Acción")],(this.data.services||[]).map(s=>[esc(s.stay?__("Habitación")+" "+this.roomName((this.data.stays||[]).find(t=>t.name===s.stay)?.room):__("Venta directa")),esc(this.itemName(s.item)),esc(s.quantity),this.amount(s.amount,s.currency),this.badge(s.status),(!["Returned","Cancelled"].includes(s.status)&&(s.status!=="Delivered"||this.allowed("approve")))?this.button("service_status",__("Actualizar"),s.name):"—"]))}`);}
    render_guests(el) {el.html(`<div class="hs-toolbar"><div><h2>${frappe.utils.escape_html(__("Clientes y huéspedes"))}</h2><p>${esc(this.guest_policy_text?.()||__("Consulte el historial autorizado de este establecimiento."))}</p></div>${this.button("guest",__("Registrar huésped"),"","primary")}</div>${this.table([__("Nombre"),__("Cliente pagador"),__("Acciones")],(this.data.guests||[]).map(g=>[esc(g.full_name),esc(g.customer?((this.data.customers||[]).find(c=>c.name===g.customer)?.customer_name||__("Cliente registrado")):__("Sin cliente vinculado")),this.button("guest_edit",__("Actualizar datos"),g.name)+this.button("guest_history",__("Ver historial"),g.name)]))}`);}
    render_management(el) {const s=this.data.summary || {};const metrics=this.prop.mode==="Motel"?[[__("Utilización horaria"),`${s.utilization||0} %`],[__("Rotaciones por habitación"),s.rotations_per_room],[__("Entradas"),s.rotations],[__("Ingreso / hora disponible"),this.amount(s.revenue_per_available_hour)],[__("Duración media"),`${s.average_stay_hours} h`]]:[[__("Habitaciones-noche ocupadas"),s.room_nights],[__("ADR"),this.amount(s.ADR)],[__("RevPAR"),this.amount(s.RevPAR)],[__("Producción alojamiento"),this.amount(s.lodging_production)]];el.html(`<div class="hs-metrics">${metrics.map(([k,v])=>`<article><span>${esc(__(k))}</span><strong>${esc(v)}</strong></article>`).join("")}</div><p class="hs-note">${frappe.utils.escape_html(__("Período operativo:"))} ${esc(s.local_starts_at||s.starts_at||"")} → ${esc(s.local_ends_at||s.ends_at||"")} · ${esc(s.time_zone||this.prop.time_zone)}</p><p class="hs-note">${esc(s.definitions||"")}</p><section class="hs-section"><h2>${frappe.utils.escape_html(__("Reportes y conciliación"))}</h2><div class="hs-shortcuts">${(this.data.reports||[]).map(r=>`<button class="hs-report-link" data-act="report" data-id="${esc(r)}">${esc(__(r))} →</button>`).join("")}</div></section><section class="hs-section"><h2>${frappe.utils.escape_html(__("Auditoría nocturna"))}</h2><p>${frappe.utils.escape_html(__("Prepare los cargos nocturnos de la fecha y revise llegadas, salidas, cuentas y turnos antes de confirmar el cierre."))}</p>${this.allowed("finance")?this.button("daily_close",__("Preparar cierre del día"),"","primary"):`<p>${esc(__("Consulte los cierres guardados en el historial."))}</p>`}</section>`);}
    render_setup(el) {el.html(`<section class="hs-welcome"><div><h2>${frappe.utils.escape_html(__("Configure la operación paso a paso"))}</h2><p>${frappe.utils.escape_html(__("Las cuentas e impuestos se seleccionan explícitamente de ERPNext."))}</p></div>${this.data.can_create_property?this.button("new_property",__("Crear establecimiento"),"","primary"):""}</section><div class="hs-shortcuts">${[["property",__("1. Políticas y contabilidad")],["category",__("2. Categorías")],["room",__("3. Habitaciones")],["rate",__("4. Tarifas")],["payment_method",__("5. Medios de pago")]].map(([id,label])=>`<button class="hs-report-link" data-act="setup" data-id="${id}">${esc(__(label))} →</button>`).join("")}</div><section class="hs-section"><h2>${frappe.utils.escape_html(__("Configuración actual"))}</h2><p>${this.data.rooms.length} ${frappe.utils.escape_html(__("habitaciones ·"))} ${this.data.categories.length} ${frappe.utils.escape_html(__("categorías ·"))} ${(this.data.rates||[]).length} ${frappe.utils.escape_html(__("tarifas"))}</p></section>`);}
    async dialog(titleText,fields,onSubmit,label=__("Guardar"),size="large") {
      // Dialog grids do not automatically fetch native Link titles. Seed the
      // title cache from the authorized bootstrap; keep original Link values.
      for(const [doctype,rows,key] of [["HS Room",this.data.rooms,"room_number"],["HS Category",this.data.categories,"category_name"],["HS Rate",this.data.rates,"title"]]){
        for(const row of rows||[])frappe.utils.add_link_title?.(doctype,row.name,row[key]);
      }
      for(const df of fields)if(df.fieldname==="mode"&&df.fieldtype==="Select")df.options=modeOptions(df.options);
      const layout=this.form_layout?.(fields);
      if(layout){fields=layout.fields;titleText=layout.title||titleText;label=layout.action||label;}
      for(const df of fields.filter(field=>field.fieldtype==="Time")){
        df.fieldtype="Data";df._hsTime=true;df.description=df.description||__("Hora local del establecimiento")+": "+(this.prop?.time_zone||__("Zona elegida al configurar"));
      }
      const selectors=fields.filter(df=>df.fieldtype==="Select").map(df=>({df,options:df.options}));
      for(const {df} of selectors)df.options=[];
      this.prepare_operational_links?.(fields);
      // Native fading backdrops still intercept the next Page click after the
      // form has disappeared. Operational close/open sequences are immediate.
      const d=new frappe.ui.Dialog({title:__(titleText),fields,size,animate:false,primary_action_label:__(label),primary_action:()=>{}});
      d.get_values=preserveEditingValue(d,d.get_values);
      d.$wrapper.addClass("hs-form-dialog");
      d.get_close_btn().attr("aria-label",__("Cerrar formulario"));
      for(const {df,options} of selectors){
        const control=d.fields_dict[df.fieldname];df.options=options;control.df.options=options;control.last_options=null;control.set_options=safeSelectOptions;control.set_options();
        if(df.default!==undefined)await control.set_value(df.default);
      }
      const numeric=["Int","Long Int","LongInt","Float","Currency","Percent","Check"],edits=new Map(),rowEdits=new Map(),rowEditors=new Map();
      const rowControls=row=>[...new Set([...Object.values(row.on_grid_fields_dict||{}),...Object.values(row.grid_form?.fields_dict||{})])];
      // Grid editors are reused/refreshed when focus moves or another row is
      // added. Keep the user's numeric input before those native refreshes.
      d.$wrapper.on("input.hsNumeric change.hsNumeric","input",event=>{
        for(const field of Object.values(d.fields_dict)){
          if(numeric.includes(field.df.fieldtype)&&field.$input?.[0]===event.target)edits.set(field.df.fieldname,field.get_input_value());
          for(const row of field.grid?.grid_rows||[])for(const control of rowControls(row)){
            if(!numeric.includes(control.df.fieldtype)||control.$input?.[0]!==event.target)continue;
            const key=`${field.df.fieldname}|${row.doc.name}`;
            if(!rowEdits.has(key))rowEdits.set(key,new Map());
            if(!rowEditors.has(key))rowEditors.set(key,new Map());
            const raw=control.get_input_value();
            rowEdits.get(key).set(control.df.fieldname,raw);
            rowEditors.get(key).set(control.df.fieldname,control);
            row.doc[control.df.fieldname]=this.form_numeric_error?.(control,raw,{typesOnly:true})?raw:control.get_parsed_value(raw);
          }
        }
      });
      d._hsSubmit=async({validate=true,handler=onSubmit}={})=>{
        if(d._hsBusy)return;d._hsBusy=true;d.get_primary_btn().prop("disabled",true);
        try{
          const pending=[];
          const capture=(control,saved,doc,table)=>{
            if(!control.$input||control.df.read_only||!numeric.includes(control.df.fieldtype))return;
            if(saved?.has(control.df.fieldname)||control.$input.is(":visible"))pending.push({control,doc,table,raw:saved?.has(control.df.fieldname)?saved.get(control.df.fieldname):control.get_input_value()});
          };
          for(const field of Object.values(d.fields_dict)){
            capture(field,edits);
            for(const row of field.grid?.grid_rows||[]){
              const key=`${field.df.fieldname}|${row.doc.name}`,controls=rowControls(row);
              for(const name of new Set(controls.map(control=>control.df.fieldname))){
                const candidates=controls.filter(control=>control.df.fieldname===name),last=rowEditors.get(key)?.get(name);
                const control=candidates.find(control=>control.$input?.is(":visible"))||(candidates.includes(last)?last:candidates[0]);
                capture(control,rowEdits.get(key),row.doc,field);
              }
            }
          }
          // Snapshot everything before awaiting: a control refresh must not
          // overwrite a later control's freshly typed value or an inactive row.
          // Every numeric type must see the raw draft before native parsing.
          // Partial saves omit required/domain checks, but never truncate input.
          if(this.validate_form_dialog&&!this.validate_form_dialog(d,{onlyNumeric:true,typesOnly:!validate,pending}))return;
          for(const value of pending)if(value.doc)value.doc[value.control.df.fieldname]=value.control.get_parsed_value(value.raw);
          for(const {control,raw} of pending)await control.parse_validate_and_set_in_model(raw);
          if(validate&&this.validate_form_dialog&&!this.validate_form_dialog(d))return;
          if(!validate)this.set_form_status?.(d,'ready');
          this.set_form_status?.(d,'busy',__('Procesando… Espere la respuesta antes de volver a confirmar.'));
          // Frappe's get_values may refresh a required input whose model is empty.
          // Synchronize first and validate once, without the default double read.
          const values=validate?d.get_values():Object.fromEntries(Object.values(d.fields_dict)
            .filter(control=>control.get_value&&!["HTML","Button","Tab Break","Section Break","Column Break"].includes(control.df.fieldtype))
            .map(control=>[control.df.fieldname,control.get_value()]));
          if(values){
            // Native get_values accepts numeric zero for a Check as well as
            // amounts. An explicitly required checklist must be checked.
            const unchecked=validate?Object.values(d.fields_dict).filter(control=>control.df.fieldtype==='Check'&&control.df.reqd&&!control.df.hidden&&!control.df.hidden_due_to_dependency&&!control.df.read_only&&control.get_value&&!control.get_value()):[];
            if(unchecked.length){
              frappe.msgprint({title:__('Campos requeridos'),message:__('Marque las casillas obligatorias: {0}',[unchecked.map(control=>esc(__(control.df.label))).join(', ')])});
              this.reveal_form_error?.(d);
            }else await handler(values,d);
          }else this.reveal_form_error?.(d);
        }catch(error){
          this.set_form_status?.(d,'error',serverMessage(error)?__('Revise el aviso del servidor y los datos antes de reintentar.'):__('Sin confirmación del servidor. Mantenga esta ventana y reintente con los mismos datos.'));
          if(!serverMessage(error))frappe.msgprint({title:__("Sin confirmación del servidor"),message:__("Mantenga esta ventana y reintente con los mismos datos. La solicitud conserva su referencia para evitar duplicados."),indicator:"orange"});
        }
        finally{d._hsBusy=false;d.get_primary_btn().prop("disabled",Boolean(d._hsCatalogBlocked));if(d.$wrapper?.[0]?.querySelector('.hs-form-status')?.getAttribute('data-state')==='busy')this.set_form_status?.(d,'ready');}
      };d.get_primary_btn().off("click").on("click",()=>d._hsSubmit());
      for(const df of fields.filter(f=>f._hsDateTime||f._hsTime||f._hsDate)){const c=d.fields_dict[df.fieldname];c.$input.attr({type:df._hsTime?"time":df._hsDate?"date":"datetime-local",step:"1"});if(df.default)c.set_value(df._hsTime?String(df.default).replace(/^(\d):/,"0$1:"):String(df.default).replace(" ","T"));} this.prepare_keyboard_dialog?.(d);d.show();this.configure_form_dialog?.(d,layout);this.prepare_form_validation?.(d);return d;
    }
    async mutate(action,data,key) {
      this.busy=true;this.connection();
      try {const result=await this.call("execute",{property_name:this.property,action,request_key:key||frappe.utils.get_random(24),data:JSON.stringify(data)});frappe.show_alert({message:__("Operación confirmada"),indicator:"green"});await this.load();return result;}
      finally{this.busy=false;this.connection();if(this.refreshPending)this.scheduleRefresh();}
    }
    action_reload(){if(navigator.onLine&&!frappe.realtime.socket?.connected)frappe.realtime.socket?.connect();return this.load();}
    async action_guest() {const key=frappe.utils.get_random(24);return this.dialog(__("Registrar huésped"),[field("full_name",__("Nombre completo"),"Data",{reqd:1}),field("phone",__("Teléfono")),field("email",__("Correo")),field("identity_type",__("Tipo de identificación")),field("identity_number",__("Identificación según política")),field("nationality",__("Nacionalidad"))],async(v,d)=>{await this.call("create_guest",{property_name:this.property,data:JSON.stringify(v),request_key:key});d.hide();await this.load();});}
    async action_guest_history(id){const rows=(this.data.stays||[]).filter(s=>s.guest===id);frappe.msgprint({title:__("Historial de estancias"),message:this.table([__("Habitación"),__("Entrada"),__("Salida"),__("Estado")],rows.map(s=>[esc(this.roomName(s.room)),esc(this.date(s.starts_at)),esc(this.date(s.ends_at)),this.badge(s.status)])),wide:true});}
    async reservation(roomId,walk=false) {
      if(!(this.data.guests||[]).length){frappe.msgprint(__("Registre primero un huésped desde Clientes y huéspedes."));return;}
      const room=this.data.rooms.find(r=>r.name===roomId), now=(this.data.property_now||this.data.server_time).slice(0,19).replace("T"," ");
      const end=moment(now).add(this.prop.mode==="Motel"?3:24,"hours").format("YYYY-MM-DD HH:mm:ss");
      const fields=[field("mode",__("Modalidad"),"Select",{options:["Hotel","Motel"],default:this.prop.mode==="Mixed"?"Hotel":this.prop.mode,read_only:this.prop.mode!=="Mixed",reqd:1}),select("guest",__("Huésped principal"),this.data.guests,"full_name"),select("customer",__("Cliente que paga"),this.data.customers,"customer_name"),field("starts_at",__("Entrada ({0})",[this.prop.time_zone]),"Datetime",{reqd:1,default:now}),field("ends_at",__("Salida prevista"),"Datetime",{reqd:1,default:end}),field("channel",__("Canal"),"Data",{default:"Recepción",description:__("Recepción, teléfono, web, empresa, agencia u otro canal propio")}),field("hold",__("Retener temporalmente"),"Check"),field("rooms",__("Habitaciones solicitadas"),"Table",{reqd:1,in_place_edit:true,data:[{category:room?.category,room:roomId||"",people:1}],fields:[field("category",__("Categoría"),"Link",{options:"HS Category",reqd:1,in_list_view:1,get_query:()=>({filters:{property:this.property}})}),field("room",__("Habitación (opcional)"),"Link",{options:"HS Room",in_list_view:1,get_query:()=>({filters:{property:this.property,active:1}})}),field("people",__("Personas"),"Int",{default:1,reqd:1,in_list_view:1})]}),field("instructions",__("Solicitudes especiales"),"Small Text")];
      return this.dialog(walk?__("Entrada inmediata"):__("Nueva reserva"),fields,async(values,d)=>{
        const calculation=await this.call("preview",{property_name:this.property,data:JSON.stringify(values)});
        const key=frappe.utils.get_random(24);
        const lines=calculation.lines.map(l=>`<li>${esc(l.explanation.join("; "))}</li>`).join("");
        await this.dialog(__("Revisar cotización"),[field("summary",__("Cotización"),"HTML",{options:`<p>${frappe.utils.escape_html(__("Moneda:"))} ${esc(calculation.currency)}</p><h2>${esc(this.amount(calculation.amount,calculation.currency))}</h2><ul>${lines}</ul><p>${frappe.utils.escape_html(__("Impuestos y saldo se calculan con la configuración vigente al facturar."))}</p>`})],async(v,confirm)=>{await this.mutate(walk?"walk_in":"reserve",{...values,acceptance:calculation.acceptance},key);confirm.hide();d.hide();},walk?__("Confirmar entrada"):__("Confirmar reserva"));
      },__("Cotizar"));
    }
    action_reserve(id){return this.reservation(id);}
    action_walk_in(){return this.reservation("",true);}
    async action_booking(id) {
      const b=this.data.bookings.find(r=>r.name===id), key=frappe.utils.get_random(24);
      const options=b.status==="Hold"?["Confirmed","Cancelled"]:b.status==="Confirmed"?["Check In","Cancelled","No Show"]:[];
      if(!options.length){frappe.msgprint({title:__("Reserva"),message:`${esc(this.bookingLabel(id))} · ${esc(title(b.status))}`});return;}
      return this.dialog(__("Gestionar reserva"),[field("status",__("Acción"),"Select",{reqd:1,options:options.map(value=>({value,label:value==="Check In"?__("Registrar entrada"):title(value)}))}),select("guest",__("Huésped"),this.data.guests,"full_name",false),select("room",__("Asignar habitación"),this.data.rooms,"room_number",false),field("reason",__("Motivo"),"Small Text")],async(v,d)=>{await this.mutate(v.status==="Check In"?"check_in":"booking_status",{...v,booking:b.name,modified:b.modified},key);d.hide();},__("Confirmar"));
    }
    async action_detail(id) {
      const info=await this.call("stay_detail",{name:id}), s=info.stay;
      this.current=info;
      const actions=s.status==="Active"?[["service",__("Agregar consumo")],["inspect_departure",__("Inspeccionar salida")],["extend",__("Extender estancia")],["change_room",__("Cambiar habitación")],["folio",__("Separar cuenta")],["companions",__("Acompañantes")],["adjustment",__("Descuento o cortesía")],["invoice",__("Facturar cuenta")],["payment",__("Cobrar")],["checkout",__("Registrar salida")]]:[];
      const d=new frappe.ui.Dialog({title:__("Habitación {0} · {1}",[esc(this.roomName(s.room)),esc(this.guestName(s.guest))]),size:"extra-large",fields:[field("account",__("Cuenta de estancia"),"HTML",{options:`<p>${esc(this.date(s.starts_at))} → ${esc(this.date(s.ends_at))} ${this.badge(s.status)}</p><div class="hs-dialog-actions">${actions.filter(([act])=>!["payment","invoice"].includes(act)||this.allowed("finance")).map(([a,l])=>this.button(a,l,s.name,a==="checkout"?"primary":"secondary")).join("")}</div><h4>${frappe.utils.escape_html(__("Cuentas y saldos"))}</h4>${this.table([__("Cuenta"),__("Pagador"),__("Programado, sin generar"),__("Saldo total")],info.folios.map(f=>[esc(f.label),esc(f.customer),this.amount(f.balance.scheduled||0,f.currency),this.amount(f.balance.outstanding,f.currency)]))}<h4>${frappe.utils.escape_html(__("Cargos"))}</h4>${this.table([__("Descripción"),__("Cuenta"),__("Importe"),__("Estado"),__("Acción")],info.charges.map(c=>[esc(c.description_label??c.description)+(this.priceExplanation?.(c)||""),esc(info.folios.find(f=>f.name===c.folio)?.label||c.folio),this.amount(c.amount,c.currency),this.badge(c.status),["Pending","Scheduled"].includes(c.status)?this.button("move_charge",__("Cambiar cuenta"),c.name):this.invoiceLink(c.sales_invoice)]))}`})]});
      d.show();d.$wrapper.on("click","[data-act]",async(e)=>{const a=$(e.currentTarget).data("act"), id2=String($(e.currentTarget).data("id")||"");d.hide();if(this[`action_${a}`])await this[`action_${a}`](id2);});return d;
    }
    async action_extend(id){const info=this.current?.stay.name===id?this.current:await this.call("stay_detail",{name:id}),key=frappe.utils.get_random(24);return this.dialog(__("Extender estancia"),[field("ends_at",__("Nueva salida"),"Datetime",{reqd:1}),select("folio",__("Cuenta para la extensión"),info.folios,"label"),field("reason",__("Observaciones"),"Small Text")],async(v,d)=>{const q=await this.call("preview",{property_name:this.property,action:"extend",data:JSON.stringify({...v,stay:id})});await this.dialog(__("Confirmar extensión"),[field("quote",__("Detalle"),"HTML",{options:`<p>${esc(q.explanation.join("; "))}</p><h3>${frappe.utils.escape_html(__("Adicional:"))} ${esc(this.amount(q.difference))}</h3>`})],async(x,c)=>{await this.mutate("extend",{...v,stay:id,modified:info.stay.modified,acceptance:q.acceptance},key);c.hide();d.hide();},__("Confirmar extensión"));},__("Cotizar extensión"));}
    async action_change_room(id){const s=this.data.stays.find(r=>r.name===id),key=frappe.utils.get_random(24);return this.dialog(__("Cambiar habitación"),[select("room",__("Nueva habitación"),this.data.rooms.filter(r=>r.name!==s.room),"room_number"),field("reason",__("Motivo"),"Small Text",{reqd:1})],async(v,d)=>{await this.mutate("change_room",{...v,stay:id,modified:s.modified},key);d.hide();});}
    async action_checkout(id){const s=this.data.stays.find(r=>r.name===id),key=frappe.utils.get_random(24);return this.dialog(__("Registrar salida"),[field("review",__("Revisión"),"HTML",{options:`<p>${frappe.utils.escape_html(__("Revise consumos, saldos y garantías antes de confirmar. La salida generará la limpieza de la habitación."))}</p>`}),field("credit_reason",__("Motivo de salida a crédito (requiere autorización)"),"Small Text")],async(v,d)=>{await this.mutate("check_out",{...v,stay:id,modified:s.modified},key);d.hide();},__("Confirmar salida"));}
    async action_folio(id){const key=frappe.utils.get_random(24);return this.dialog(__("Separar cuenta"),[select("customer",__("Cliente o empresa pagadora"),this.data.customers,"customer_name"),field("label",__("Nombre de la cuenta"),"Data",{reqd:1}),field("group",__("Cuenta compartida de todo el grupo"),"Check")],async(v,d)=>{await this.mutate("create_folio",{...v,stay:id},key);d.hide();});}
    async action_move_charge(id){const key=frappe.utils.get_random(24);return this.dialog(__("Cambiar cargo de cuenta"),[select("folio",__("Cuenta destino"),this.current.folios,"label"),field("reason",__("Motivo"),"Small Text",{reqd:1})],async(v,d)=>{await this.mutate("move_charge",{...v,charge:id},key);d.hide();});}
    async action_open_shift(){const key=frappe.utils.get_random(24);return this.dialog(__("Abrir turno"),[field("currency",__("Moneda"),"Link",{options:"Currency",default:this.prop.currency,reqd:1}),field("opening_amount",__("Fondo inicial"),"Currency",{default:0,reqd:1})],async(v,d)=>{await this.mutate("open_shift",v,key);d.hide();});}
    async action_close_shift(id){const s=this.data.shifts.find(r=>r.name===id),key=frappe.utils.get_random(24);const fields=Object.keys(s.expected_by_currency).map(c=>field(`count_${c}`,__("Contado {0} (esperado {1})",[c,s.expected_by_currency[c]]),"Currency",{reqd:1,default:0}));return this.dialog(__("Arqueo y cierre de turno"),[...fields,field("reason",__("Motivo de diferencias"),"Small Text"),field("approve",__("Aprobar diferencia (supervisión)"),"Check")],async(v,d)=>{const denominations={};for(const c of Object.keys(s.expected_by_currency))denominations[c]=[{value:1,count:v[`count_${c}`]}];await this.mutate("close_shift",{shift:id,modified:s.modified,denominations,reason:v.reason,approve:v.approve},key);d.hide();},__("Cerrar turno"));}
    async action_payment(stayId){if(!this.allowed("finance")){frappe.msgprint(__("Solicite el cobro a caja."));return;}const key=frappe.utils.get_random(24);const fields=[select("stay",__("Estancia"),this.data.stays||[],"name",false),select("booking",__("Reserva o grupo"),this.data.bookings||[],"name",false),select("folio",__("Cuenta (para cobro)"),this.data.folios||[],"label",false),select("shift",__("Turno"),this.data.shifts.filter(s=>s.status==="Open")),select("method",__("Medio de pago"),this.data.payment_methods,"mode_of_payment"),field("kind",__("Concepto"),"Select",{options:["Payment","Advance","Guarantee","Refund","Guarantee Refund"].map(value=>({value,label:title(value)})),reqd:1}),field("amount",__("Importe en la moneda del medio"),"Currency",{reqd:1}),field("reference",__("Referencia bancaria")),field("credit_note",__("Nota de crédito para devolución de factura"),"Link",{options:"Sales Invoice"}),select("source_payment",__("Pago original (devolución)"),this.data.payments||[],"name",false),field("reason",__("Motivo de devolución"),"Small Text")];const d=await this.dialog(__("Cobrar o devolver"),fields,async(v,x)=>{await this.mutate("payment",v,key);x.hide();},__("Confirmar movimiento"));if(stayId)d.set_value("stay",stayId);}
    async action_cleaning(id){const t=this.data.cleaning.find(r=>r.name===id),key=frappe.utils.get_random(24);let target=t.status==="Pending"?"In Progress":t.status==="Inspection"?"Completed":this.prop.inspection_required?"Inspection":"Completed";const fields=target!=="In Progress"?[field("bath",__("Baño revisado"),"Check",{reqd:1}),field("bed",__("Cama y ropa revisadas"),"Check",{reqd:1}),field("minibar",__("Minibar revisado"),"Check",{reqd:1}),field("surfaces",__("Superficies y equipo revisados"),"Check",{reqd:1})]:[];return this.dialog(__("Habitación {0} · {1}",[this.roomName(t.room),title(target)]),[...fields,field("notes",__("Observaciones"),"Small Text")],async(v,d)=>{await this.mutate("cleaning",{task:id,status:target,modified:t.modified,notes:v.notes,checklist:{baño:!!v.bath,cama:!!v.bed,minibar:!!v.minibar,superficies:!!v.surfaces}},key);d.hide();},target==="In Progress"?__("Iniciar limpieza"):target==="Inspection"?__("Solicitar inspección"):__("Liberar habitación"));}
    async action_maintenance(id){const key=frappe.utils.get_random(24),t=this.data.maintenance.find(r=>r.name===id);const fields=t?[field("status",__("Estado"),"Select",{options:["In Progress","Completed"].map(value=>({value,label:title(value)})),reqd:1})]:[select("room",__("Habitación"),this.data.rooms,"room_number"),field("title",__("Incidencia"),"Data",{reqd:1}),field("starts_at",__("Inicio de bloqueo"),"Datetime",{reqd:1}),field("ends_at",__("Fin de bloqueo"),"Datetime",{reqd:1}),field("kind",__("Tipo"),"Select",{options:["Corrective","Preventive"],default:"Corrective"})];return this.dialog(t?__("Actualizar mantenimiento"):__("Registrar incidencia"),[...fields,field("notes",__("Observaciones"),"Small Text")],async(v,d)=>{await this.mutate("maintenance",{...v,...(t?{order:id,modified:t.modified}:{})},key);d.hide();});}
    async action_service(id){const key=frappe.utils.get_random(24),fields=[select("stay",__("Estancia"),(this.data.stays||[]).filter(s=>s.status==="Active")),select("folio",__("Cuenta"),(this.data.folios||[]).filter(f=>f.status==="Open"),"label"),this.item_field(__("Artículo"),"sale"),field("quantity",__("Cantidad"),"Float",{default:1,reqd:1}),field("notes",__("Instrucciones"),"Small Text")];const d=await this.dialog(__("Agregar consumo"),fields,async(v,x)=>{await this.mutate("request_service",v,key);x.hide();});if(id)d.set_value("stay",id);}
    async action_service_status(id){const s=this.data.services.find(r=>r.name===id),key=frappe.utils.get_random(24);const options=s.status==="Delivered"?["Returned"]:["In Progress","Delivered","Cancelled"];return this.dialog(__("Actualizar servicio"),[field("status",__("Estado"),"Select",{reqd:1,options:options.map(value=>({value,label:title(value)}))}),field("reason",__("Motivo de devolución"),"Small Text")],async(v,d)=>{await this.mutate("update_service",{...v,service:id,modified:s.modified},key);d.hide();});}
    async action_report(id){const rows=await this.call("report",{property_name:this.property,report_name:id});const headers=rows.length?Object.keys(rows[0]):[];frappe.msgprint({title:__(id),message:this.table(headers,rows.map(r=>headers.map(k=>esc(r[k])))),wide:true});}
    async action_daily_close(){const result=await this.mutate("daily_close",{confirm:false});const key=frappe.utils.get_random(24);return this.dialog(__("Cierre del día"),[field("pending",__("Pendientes"),"HTML",{options:`<p>${frappe.utils.escape_html(__("Período:"))} ${esc(result.period?.local_starts_at||"")} → ${esc(result.period?.local_ends_at||"")} · ${esc(result.period?.time_zone||this.prop.time_zone)}</p><p>${frappe.utils.escape_html(__("La fecha operativa avanza únicamente al confirmar el cierre."))}</p>`+(result.blockers.length?`<ul>${result.blockers.map(b=>`<li>${esc(b.type)}: ${b.documents.length}</li>`).join("")}</ul>`:`<p>${frappe.utils.escape_html(__("No hay pendientes. Puede confirmar el cierre y avanzar la fecha operativa."))}</p>`)})],async(v,d)=>{await this.mutate("daily_close",{confirm:true},key);d.hide();},__("Confirmar cierre"));}
    async action_print_shift(id){window.open(`/printview?doctype=HS%20Shift&name=${encodeURIComponent(id)}&format=HS%20Arqueo`,"_blank","noopener");}
    async action_setup(section){const key=frappe.utils.get_random(24),config=await this.call("configuration",{property_name:this.property}),p=config;let fields=[];if(section==="category")fields=[field("category_name",__("Categoría"),"Data",{reqd:1}),field("capacity",__("Capacidad"),"Int",{default:2,reqd:1}),field("amenities",__("Comodidades"),"Small Text")];if(section==="room")fields=[field("room_number",__("Número de habitación"),"Data",{reqd:1}),select("category",__("Categoría"),this.data.categories,"category_name"),field("floor",__("Piso")),field("zone",__("Zona")),field("beds",__("Camas"),"Int",{default:1}),field("parking",__("Estacionamiento")),field("active",__("Habilitada"),"Check",{default:1})];if(section==="rate")fields=[field("title",__("Nombre de tarifa"),"Data",{reqd:1}),select("category",__("Categoría"),this.data.categories,"category_name"),field("mode",__("Modalidad"),"Select",{options:["Hotel","Motel"],default:p.mode==="Motel"?"Motel":"Hotel"}),field("currency",__("Moneda"),"Link",{options:"Currency",default:p.currency,reqd:1}),field("amount",__("Precio por noche o bloque"),"Currency",{reqd:1}),field("block_hours",__("Horas del bloque"),"Float",{default:3}),field("extra_hour_rate",__("Hora adicional"),"Currency"),field("grace_minutes",__("Tolerancia en minutos"),"Int",{default:0}),field("rounding_minutes",__("Fracción en minutos"),"Int",{default:60}),field("priority",__("Prioridad (mayor gana)"),"Int",{default:10}),field("active",__("Activa"),"Check",{default:1})];if(section==="payment_method")fields=[field("mode_of_payment",__("Medio de pago"),"Link",{options:"Mode of Payment",reqd:1}),field("account",__("Cuenta contable"),"Link",{options:"Account",reqd:1}),field("currency",__("Moneda"),"Link",{options:"Currency",default:p.currency,reqd:1}),field("reference_required",__("Referencia obligatoria"),"Check"),field("is_cash",__("Efectivo"),"Check")];if(section==="property")fields=[field("brand_name",__("Nombre comercial")),field("lodging_charge_policy",__("Cargos de alojamiento"),"Select",{default:p.lodging_charge_policy||"Arrival",options:[{value:"Arrival",label:__("Al ingresar")},{value:"Nightly",label:__("Por noche, en la auditoría del día")}],description:__("Aplica a nuevas estancias de hotel. Facturar o salir liquida también las noches programadas; la modalidad por tiempo conserva el cargo por bloque.")}),field("mode",__("Modalidad"),"Select",{options:["Hotel","Motel","Mixed"],default:p.mode}),field("time_zone",__("Zona horaria"),"Data",{default:p.time_zone,reqd:1}),field("cleaning_minutes",__("Colchón de limpieza (min)"),"Int",{default:30}),field("inspection_required",__("Requiere inspección"),"Check",{default:p.inspection_required}),field("discreet_mode",__("Modo discreto"),"Check",{default:p.discreet_mode}),field("guest_id_required",__("Requerir identificación"),"Check"),field("allow_credit",__("Permitir salida a crédito autorizada"),"Check"),field("cost_center",__("Centro de costo"),"Link",{options:"Cost Center"}),field("warehouse",__("Almacén"),"Link",{options:"Warehouse"}),field("receivable_account",__("Cuenta por cobrar"),"Link",{options:"Account"}),field("guarantee_account",__("Pasivo de garantías"),"Link",{options:"Account"}),field("cash_transfer_account",__("Cuenta de entrega de efectivo"),"Link",{options:"Account"}),field("price_list",__("Lista de precios de servicios"),"Link",{options:"Price List"}),field("laundry_warehouse",__("Almacén de lavandería"),"Link",{options:"Warehouse"}),field("lodging_item",__("Artículo de alojamiento"),"Link",{options:"Item"}),field("tax_template",__("Plantilla tributaria"),"Link",{options:"Sales Taxes and Charges Template"}),field("tax_policy_confirmed",__("Política tributaria revisada"),"Check"),field("financial_enabled",__("Habilitar operaciones financieras"),"Check")];if(section==="property")fields=fields.map(df=>({...df,default:config[df.fieldname]??df.default}));return this.dialog(__("Configuración"),fields,async(v,d)=>{await this.call("save_setup",{property_name:this.property,section,data:JSON.stringify(v),request_key:key,expected_modified:config.modified});d.hide();await this.load();});}
    async action_new_property(){const key=frappe.utils.get_random(24);return this.dialog(__("Crear establecimiento"),[field("property_name",__("Nombre"),"Data",{reqd:1}),field("company",__("Compañía de ERPNext"),"Link",{options:"Company",reqd:1}),field("mode",__("Modalidad"),"Select",{options:["Hotel","Motel","Mixed"],default:"Hotel"}),field("currency",__("Moneda"),"Link",{options:"Currency",default:"NIO",reqd:1}),field("time_zone",__("Zona horaria"),"Data",{default:"America/Managua",reqd:1}),field("close_time",__("Hora de corte"),"Time",{default:"06:00:00",reqd:1,description:__("Hora local según la zona elegida para el establecimiento.")}),field("business_date",__("Fecha operativa inicial"),"Date",{description:__("Opcional. Si se deja vacía, se calcula según la hora local y el corte. Después se avanza mediante el cierre diario.")})],async(v,d)=>{const created=await this.call("create_property",{data:JSON.stringify(v),request_key:key});d.hide();this.property=created.property;this.data=null;await this.load();});}
  }
  hospitality_suite.Desk=Desk;
})();
