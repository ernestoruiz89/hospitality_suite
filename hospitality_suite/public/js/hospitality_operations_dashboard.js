/* Tickets, enterprise credit, portfolio and administrator health views. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const e=value=>frappe.utils.escape_html(String(value??""));
  const f=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),fieldtype:["Date","Datetime"].includes(fieldtype)?"Data":fieldtype,_hsDateTime:fieldtype==="Datetime",_hsDate:fieldtype==="Date",...extra});
  const choose=(name,label,rows,text="name",required=false)=>f(name,label,"Select",{reqd:required,_hsDataOptions:true,options:[{value:"",label:__("Seleccione…")},...rows.map(row=>({value:row.name,label:row[text]||row.name}))]});
  const ticketLabels={"Guest Request":__("Solicitud"),Housekeeping:__("Limpieza"),Maintenance:__("Mantenimiento"),Complaint:__("Queja"),Other:__("Otro")};
  const eventLabels={Created:__("Creado"),Assigned:__("Asignado"),Started:__("Iniciado"),Resolved:__("Resuelto"),Reopened:__("Reabierto"),Cancelled:__("Cancelado"),Note:__("Nota"),"Due Changed":__("Plazo cambiado")};
  const creditLabels={Available:__("Disponible"),"Not Authorized":__("Sin autorización"),"Currency Review":__("Revisar monedas"),Overdue:__("Vencido"),"Over Limit":__("Sobre límite")};
  const healthLabels={OK:__("Correcto"),Warning:__("Atención"),Error:__("Error"),Unknown:__("No comprobado")};
  const safeCurrent=(desk,el,route,prop)=>desk.route===route&&desk.property===prop&&el?.[0]?.isConnected;

  Desk.prototype.render_tickets=function(el){
    if(this.ticketProperty!==this.property){this.ticketProperty=this.property;this.ticketOffset=0;}
    const view=this.ticketView||"open";
    const tabs=[["open",__("Pendientes")],["mine",__("Mis tickets")],["unassigned",__("Sin responsable")],["overdue",__("Vencidos")],["resolved",__("Resueltos")],["all",__("Todos")]];
    el.html(`<div class="hs-toolbar"><div><h2>${e(__("Solicitudes y seguimiento"))}</h2><p>${e(__("Responsable, plazo e historial por ticket."))}</p></div>${this.allowed("ticket")?this.button("ticket_new",__("Crear ticket"),"","primary"):""}</div><div class="hs-shortcuts">${tabs.map(([code,label])=>this.button("ticket_filter",label,code,view===code?"primary":"secondary")).join("")}</div><section class="hs-section hs-ticket-results" aria-live="polite"><p role="status">${e(__("Consultando tickets…"))}</p></section>`);
    this.load_tickets(el);
  };
  Desk.prototype.load_tickets=async function(el=this.root.find(".hs-content")){
    const property=this.property,view=this.ticketView||"open",offset=this.ticketOffset||0;
    const target=el.find(".hs-ticket-results");
    try{
      const data=await this.call("ticket_board",{property_name:property,view,offset,page_length:40});
      if(!safeCurrent(this,el,"hospitality-tickets",property)||view!==(this.ticketView||"open"))return;
      this.ticketBoard=data;
      const now=Date.parse(String(data.now).replace(" ","T")+"Z");
      const rows=data.rows.map(t=>{
        const overdue=["Open","In Progress"].includes(t.status)&&t.due_at&&Date.parse(String(t.due_at).replace(" ","T")+"Z")<now;
        const buttons=[this.button("ticket_detail",__("Historial"),t.name)];
        if(t.status==="Open")buttons.push(this.button("ticket_step",__("Iniciar"),`start|${t.name}`));
        if(["Open","In Progress"].includes(t.status))buttons.push(this.button("ticket_step",__("Resolver"),`resolve|${t.name}`));
        if(["Open","In Progress"].includes(t.status)&&this.allowed("inspect")){
          buttons.push(this.button("ticket_step",__("Asignar"),`assign|${t.name}`));
          buttons.push(this.button("ticket_step",__("Plazo"),`due|${t.name}`));
        }
        if(["Open","In Progress"].includes(t.status))buttons.push(this.button("ticket_step",__("Nota"),`note|${t.name}`));
        if(t.status==="Resolved"&&this.allowed("inspect"))buttons.push(this.button("ticket_step",__("Reabrir"),`reopen|${t.name}`));
        if(["Open","In Progress"].includes(t.status)&&this.allowed("inspect"))buttons.push(this.button("ticket_step",__("Cancelar"),`cancel|${t.name}`));
        return [e(t.room?this.roomName(t.room):"—"),`<strong>${e(t.subject)}</strong><br><small>${e(ticketLabels[t.category]||t.category)}</small>`,
          this.badge(t.priority),this.badge(t.status),e(data.assignees.find(u=>u.name===t.assigned_to)?.full_name||t.assigned_to||__("Sin responsable")),
          `<span class="${overdue?"hs-ticket-overdue":""}">${e(this.date(t.due_at))}${overdue?` · ${e(__("Vencido"))}`:""}</span>`,buttons.join(" ")];
      });
      target.html(`<p role="status">${e(__("{0} tickets · mostrando {1}–{2}",[data.total,data.total?offset+1:0,offset+rows.length]))}</p>${rows.length?this.table([__("Habitación"),__("Asunto"),__("Prioridad"),__("Estado"),__("Responsable"),__("Plazo"),__("Acciones")],rows):this.empty(__("No hay tickets en esta vista."))}<div class="hs-dialog-actions">${offset?this.button("ticket_page",__("Anterior"),"previous"):""}${data.has_more?this.button("ticket_page",__("Siguiente"),"next"):""}</div>`);
    }catch{if(safeCurrent(this,el,"hospitality-tickets",property))target.html(`<p role="alert">${e(__("No se pudieron consultar los tickets."))}</p>${this.button("ticket_refresh",__("Reintentar"))}`);}
  };
  Desk.prototype.action_ticket_filter=function(view){this.ticketView=view;this.ticketOffset=0;this.render();};
  Desk.prototype.action_ticket_page=function(direction){this.ticketOffset=Math.max(0,(this.ticketOffset||0)+(direction==="next"?40:-40));this.load_tickets();};
  Desk.prototype.action_ticket_refresh=function(){return this.load_tickets();};
  Desk.prototype.action_ticket_new=async function(room){
    const key=frappe.utils.get_random(24),board=this.ticketBoard;
    const fields=[choose("room",__("Habitación"),this.data.rooms,"room_number"),
      f("subject",__("Asunto"),"Data",{reqd:1}),f("description",__("Descripción"),"Small Text",{reqd:1}),
      f("category",__("Categoría"),"Select",{options:Object.entries(ticketLabels).map(([value,label])=>({value,label})),default:"Guest Request"}),
      f("priority",__("Prioridad"),"Select",{options:["Normal","High","Urgent"].map(value=>({value,label:({Normal:__("Normal"),High:__("Alta"),Urgent:__("Urgente")})[value]})),default:"Normal"}),
      choose("assigned_to",__("Responsable"),board?.assignees||[],"full_name"),
      f("due_at",__("Plazo específico (opcional; si se omite se calcula por prioridad)"),"Datetime")];
    const d=await this.dialog(__("Nuevo ticket"),fields,async(values,dialog)=>{await this.mutate("ticket",{kind:"create",...values},key);dialog.hide();},__("Crear ticket"));
    if(room)d.set_value("room",room);
    return d;
  };
  Desk.prototype.action_ticket_detail=async function(name){
    let data=await this.call("ticket_detail",{name,offset:0,page_length:100});
    const html=()=>{
      const ticket=data.ticket,rows=data.events.map(event=>[e(this.date(event.occurred_at)),e(event.actor),e(eventLabels[event.kind]||event.kind),e(event.note||""),e(event.before_value||""),e(event.after_value||"")]);
      return `<p><strong>${e(ticket.subject)}</strong> · ${e(ticketLabels[ticket.category]||ticket.category)} · ${e(ticket.status)}</p><p>${e(ticket.description)}</p><p>${e(__("Responsable:"))} ${e(ticket.assigned_to||__("Sin responsable"))} · ${e(__("Plazo:"))} ${e(this.date(ticket.due_at))}</p>${ticket.resolution?`<p><strong>${e(__("Resolución:"))}</strong> ${e(ticket.resolution)}</p>`:""}<p>${e(__("Eventos {0}–{1} de {2}",[data.total_events?data.offset+1:0,data.offset+rows.length,data.total_events]))}</p>${this.table([__("Fecha"),__("Actor"),__("Cambio"),__("Nota"),__("Anterior"),__("Nuevo")],rows)}<div class="hs-dialog-actions">${data.offset?`<button type="button" class="btn btn-secondary" data-hs-ticket-page="${Math.max(0,data.offset-100)}">${e(__("Más recientes"))}</button>`:""}${data.has_older?`<button type="button" class="btn btn-secondary" data-hs-ticket-page="${data.offset+100}">${e(__("Más antiguos"))}</button>`:""}</div>`;
    };
    const dialog=await this.dialog(__("Historial del ticket"),[f("history",__("Historial"),"HTML",{options:html()})],async(_,d)=>d.hide(),__("Cerrar"),"extra-large");
    dialog.$wrapper.on("click","[data-hs-ticket-page]",async event=>{
      const buttons=dialog.$wrapper.find("[data-hs-ticket-page]").prop("disabled",true);
      try{data=await this.call("ticket_detail",{name,offset:Number(event.currentTarget.dataset.hsTicketPage),page_length:100});dialog.set_df_property("history","options",html());}
      catch{buttons.prop("disabled",false);frappe.msgprint(__("No se pudo consultar esa parte del historial."));}
    });
    return dialog;
  };
  Desk.prototype.action_ticket_step=async function(value){
    const [kind,name]=value.split("|"),result=await this.call("ticket_detail",{name}),ticket=result.ticket,key=frappe.utils.get_random(24);
    const fields=kind==="resolve"?[f("resolution",__("Resolución"),"Small Text",{reqd:1})]:
      kind==="assign"?[choose("assigned_to",__("Responsable"),this.ticketBoard?.assignees||[],"full_name",true)]:
      kind==="due"?[f("due_at",__("Nuevo plazo"),"Datetime",{reqd:1}),f("note",__("Motivo"),"Small Text",{reqd:1})]:
      ["note","reopen","cancel"].includes(kind)?[f("note",__("Motivo o nota"),"Small Text",{reqd:1})]:[];
    const labels={start:__("Iniciar ticket"),resolve:__("Resolver ticket"),assign:__("Asignar responsable"),due:__("Cambiar plazo"),note:__("Agregar nota"),reopen:__("Reabrir ticket"),cancel:__("Cancelar ticket")};
    return this.dialog(labels[kind],fields,async(values,dialog)=>{await this.mutate("ticket",{kind,ticket:name,modified:ticket.modified,...values},key);dialog.hide();},__("Confirmar"));
  };
  Desk.prototype.render_credit=function(el){
    if(this.creditProperty!==this.property){this.creditProperty=this.property;this.creditOffset=0;}
    el.html(`<div class="hs-toolbar"><div><h2>${e(__("Crédito empresarial"))}</h2><p>${e(__("Cuentas por cobrar, cargos sin facturar, vencimientos y límite autorizado."))}</p></div>${this.allowed("setup")?this.button("billing_party",__("Registrar pagador"),"","primary"):""}</div><section class="hs-section hs-credit-results" aria-live="polite"><p role="status">${e(__("Consultando cartera…"))}</p></section>`);
    this.load_credit(el);
  };
  Desk.prototype.load_credit=async function(el){
    const prop=this.property,offset=this.creditOffset||0,target=el.find(".hs-credit-results");
    try{
      const data=await this.call("credit_overview",{property_name:prop,offset,page_length:50});
      if(!safeCurrent(this,el,"hospitality-credit",prop)||offset!==(this.creditOffset||0))return;
      this.creditRows=data.rows;
      target.html(`<p role="status">${e(__("{0} pagadores · mostrando {1}–{2}",[data.total,data.total?offset+1:0,offset+data.rows.length]))}</p>`+(data.rows.length?this.table([__("Empresa o cliente"),__("Estado"),__("Límite"),__("Facturado pendiente"),__("Sin facturar"),__("Vencido"),__("Disponible"),__("Plazo"),__("Acciones")],data.rows.map(row=>[
        e(row.customer_name||row.customer),e(creditLabels[row.status]||row.status),e(this.amount(row.limit,data.currency)),
        e(this.amount(row.receivable,data.currency)),e(this.amount(row.unbilled,data.currency)),
        e(this.amount(row.overdue,data.currency)),e(this.amount(row.available,data.currency)),e(`${row.credit_days} ${__("días")}`),
        this.button("credit_detail",__("Ver facturas"),row.customer)+" "+(this.allowed("setup")?this.button("credit_edit",__("Editar"),row.party):"")
      ])):this.empty(__("No hay pagadores empresariales registrados.")))+`<div class="hs-dialog-actions">${offset?this.button("credit_page",__("Anterior"),"previous"):""}${offset+data.rows.length<data.total?this.button("credit_page",__("Siguiente"),"next"):""}</div>`);
    }catch{if(safeCurrent(this,el,"hospitality-credit",prop))target.html(`<p role="alert">${e(__("No se pudo consultar la cartera."))}</p>`);}
  };
  Desk.prototype.action_credit_page=function(direction){this.creditOffset=Math.max(0,(this.creditOffset||0)+(direction==="next"?50:-50));return this.load_credit(this.root.find(".hs-content"));};
  Desk.prototype.action_credit_detail=async function(customer){
    let data=await this.call("credit_status",{property_name:this.property,customer,offset:0,page_length:100});
    const html=()=>{
      const invoices=data.invoices||[];
      const groups=Object.entries(data.by_currency||{}).map(([currency,value])=>[e(currency),e(this.amount(value.receivable,currency)),e(this.amount(value.unbilled,currency)),e(this.amount(value.overdue,currency))]);
      return `<p>${e(creditLabels[data.status]||data.status)} · ${e(__("Límite:"))} ${e(this.amount(data.limit,data.currency))} · ${e(__("Disponible:"))} ${e(this.amount(data.available,data.currency))}</p><h4>${e(__("Exposición de la empresa por moneda"))}</h4>${this.table([__("Moneda"),__("Por cobrar"),__("Sin facturar"),__("Vencido")],groups)}<h4>${e(__("Facturas de este establecimiento"))}</h4><p>${e(__("{0} facturas · mostrando {1}–{2}",[data.invoice_total,data.invoice_total?data.invoice_offset+1:0,data.invoice_offset+invoices.length]))}</p>${invoices.length?this.table([__("Factura"),__("Moneda"),__("Saldo"),__("Vencimiento"),__("Estado")],invoices.map(row=>[e(row.name),e(row.currency),e(this.amount(row.outstanding,row.currency)),e(row.due_date),e(row.overdue?__("Vencida"):__("Vigente"))])):this.empty(__("No hay facturas pendientes de este establecimiento."))}<div class="hs-dialog-actions">${data.invoice_offset?`<button type="button" class="btn btn-secondary" data-hs-credit-page="${Math.max(0,data.invoice_offset-100)}">${e(__("Anterior"))}</button>`:""}${data.invoice_has_more?`<button type="button" class="btn btn-secondary" data-hs-credit-page="${data.invoice_offset+100}">${e(__("Siguiente"))}</button>`:""}</div>`;
    };
    const dialog=await this.dialog(__("Detalle de crédito"),[f("detail",__("Cartera"),"HTML",{options:html()})],async(_,d)=>d.hide(),__("Cerrar"),"extra-large");
    dialog.$wrapper.on("click","[data-hs-credit-page]",async event=>{
      const buttons=dialog.$wrapper.find("[data-hs-credit-page]").prop("disabled",true);
      try{data=await this.call("credit_status",{property_name:this.property,customer,offset:Number(event.currentTarget.dataset.hsCreditPage),page_length:100});dialog.set_df_property("detail","options",html());}
      catch{buttons.prop("disabled",false);frappe.msgprint(__("No se pudo consultar esa página de facturas."));}
    });
    return dialog;
  };
  Desk.prototype.action_credit_edit=function(name){
    const row=(this.creditRows||[]).find(item=>item.party===name);
    if(!row||!this.allowed("setup"))return;
    const key=frappe.utils.get_random(24);
    const fields=[f("kind",__("Tipo"),"Select",{options:["Company","Agency","Individual"],default:row.kind,reqd:1}),
      f("credit_authorized",__("Autorizar crédito"),"Check",{default:row.grant_authorized?1:0}),
      f("credit_limit",__("Límite en moneda del establecimiento"),"Currency",{default:row.limit}),
      f("credit_days",__("Plazo de pago (días)"),"Int",{default:row.credit_days}),
      f("valid_until",__("Vigente hasta"),"Date",{default:row.valid_until||""}),
      f("reason",__("Motivo del cambio"),"Small Text",{reqd:1})];
    return this.dialog(__("Editar crédito empresarial"),fields,async(values,dialog)=>{
      await this.mutate("billing_party",{party:name,modified:row.modified,...values},key);dialog.hide();
    },__("Guardar condiciones"));
  };
  Desk.prototype.render_portfolio=function(el){
    el.html(`<div class="hs-toolbar"><div><h2>${e(__("Cartera de establecimientos"))}</h2><p>${e(__("Situación operativa y saldos por moneda de las sedes autorizadas."))}</p></div>${this.button("portfolio_refresh",__("Actualizar"))}</div><section class="hs-section hs-portfolio-results" aria-live="polite"><p role="status">${e(__("Consultando establecimientos…"))}</p></section>`);
    this.load_portfolio(el);
  };
  Desk.prototype.action_portfolio_refresh=function(){return this.load_portfolio(this.root.find(".hs-content"));};
  Desk.prototype.load_portfolio=async function(el){
    const prop=this.property,target=el.find(".hs-portfolio-results");
    try{
      const data=await this.call("portfolio_snapshot");
      if(!safeCurrent(this,el,"hospitality-portfolio",prop))return;
      const c=data.counts;
      const metrics=[[__("Sedes"),c.properties],[__("Habitaciones activas"),c.rooms],[__("Ocupadas ahora"),c.occupied],[__("Tickets abiertos"),c.open_tickets],[__("Tickets vencidos"),c.overdue_tickets]];
      const moneyRows=Object.entries(data.totals).map(([currency,v])=>[e(currency),e(this.amount(v.receivable,currency)),e(this.amount(v.unbilled,currency)),e(this.amount(v.overdue,currency))]);
      const propertyRows=data.properties.map(row=>[e(row.property_name),e(({Hotel:__("Hotel"),"Por tiempo":__("Por tiempo"),Mixed:__("Hotel y por tiempo")})[row.mode]||row.mode),e(row.business_date),e(`${row.occupied}/${row.rooms}`),e(row.blocked),e(row.cleaning),e(row.maintenance),e(row.tickets),e(row.overdue_tickets),this.button("portfolio_open",__("Abrir sede"),row.property)]);
      target.html(`<div class="hs-metrics">${metrics.map(([label,value])=>`<article><span>${e(label)}</span><strong>${e(value)}</strong></article>`).join("")}</div><h3>${e(__("Saldos por moneda"))}</h3><p class="hs-note">${e(__("No se convierten ni suman monedas distintas."))}</p>${this.table([__("Moneda"),__("Por cobrar"),__("Sin facturar"),__("Vencido")],moneyRows)}<h3>${e(__("Por establecimiento"))}</h3>${this.table([__("Establecimiento"),__("Modalidad"),__("Fecha operativa"),__("Ocupadas / activas"),__("Bloqueadas"),__("Limpieza"),__("Mantenimiento"),__("Tickets"),__("Vencidos"),__("Acción")],propertyRows)}`);
    }catch{if(safeCurrent(this,el,"hospitality-portfolio",prop))target.html(`<p role="alert">${e(__("No se pudo consultar la cartera de establecimientos."))}</p>`);}
  };
  Desk.prototype.action_portfolio_open=function(property){
    if(!this.data.properties.some(row=>row.name===property))return;
    window.hospitality_suite.ui_storage.setItem("hs-property",property);
    frappe.set_route("hospitality-home");
  };
  Desk.prototype.render_health=function(el){
    el.html(`<div class="hs-toolbar"><div><h2>${e(__("Salud del sistema"))}</h2><p>${e(__("Comprobaciones de solo lectura del sitio y este establecimiento."))}</p></div>${this.button("health_refresh",__("Volver a comprobar"))}</div><section class="hs-section hs-health-results" aria-live="polite"><p role="status">${e(__("Comprobando…"))}</p></section>`);
    this.load_health(el);
  };
  Desk.prototype.action_health_refresh=function(){return this.load_health(this.root.find(".hs-content"));};
  Desk.prototype.load_health=async function(el){
    const prop=this.property,target=el.find(".hs-health-results");
    try{
      const data=await this.call("health_snapshot",{property_name:prop});
      if(!safeCurrent(this,el,"hospitality-health",prop))return;
      target.html(`<p>${e(__("Comprobado:"))} ${e(this.date(data.checked_at))} · <strong>${e(healthLabels[data.status]||data.status)}</strong></p>${this.table([__("Componente"),__("Estado"),__("Detalle")],data.checks.map(c=>[e(c.title),e(healthLabels[c.status]||c.status),e(c.detail)]))}`);
    }catch{if(safeCurrent(this,el,"hospitality-health",prop))target.html(`<p role="alert">${e(__("No se pudo comprobar la salud del sistema."))}</p>`);}
  };
})();
