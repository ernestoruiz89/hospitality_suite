/* Agency attribution and experiences share booking and ERPNext service flows. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const e=value=>frappe.utils.escape_html(String(value??""));
  const f=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),
    fieldtype:fieldtype==="Datetime"?"Data":fieldtype,_hsDateTime:fieldtype==="Datetime",...extra});
  const agentTypes=["Travel Agent","OTA","Tour Operator","Corporate Desk"];
  const categories=["Spa","Tour","Dining","Activity","Transport","Other"];
  const statusLabel={Reserved:__("Reservada"),Confirmed:__("Confirmada"),Delivered:__("Entregada"),Cancelled:__("Cancelada")};
  const board=desk=>desk.data.travel_experiences||{agents:[],experiences:[],orders:[],contribution:[]};

  Desk.prototype.render_travel_agents=function(el){
    const agents=board(this).agents,bookings=(this.data.bookings||[]).filter(row=>row.travel_agent),
      contribution=board(this).contribution||[],
      agentName=id=>agents.find(row=>row.name===id)?.agent_name||id;
    el.html(`<div class="hs-toolbar"><div><h2>${e(__("Agencias de viajes"))}</h2><p>${e(__("Origen comercial, comisión acordada y liquidación por reserva."))}</p></div>
      ${this.allowed("setup")?this.button("travel_agent",__("Agregar agencia"),"","primary")+this.button("agent_commission_setup",__("Configurar comisión")):""}</div>
      <section class="hs-section"><h2>${e(__("Agencias"))}</h2>${this.table([__("Agencia"),__("Tipo"),__("Comisión"),__("Proveedor"),__("Estado"),__("Acción")],
        agents.map(row=>[e(row.agent_name),e(__(row.agent_type)),`${e(row.commission_pct)} %`,e(row.supplier||"—"),
          e(row.active?__("Activa"):__("Inactiva")),this.allowed("setup")?this.button("travel_agent",__("Editar"),row.name):"—"]))}</section>
      <section class="hs-section"><h2>${e(__("Contribución acumulada"))}</h2><p class="hs-note">${e(__("Reservas confirmadas o completadas; importes aceptados de alojamiento, sin cobros ni impuestos."))}</p>
        ${this.table([__("Agencia"),__("Reservas"),__("Alojamiento aceptado"),__("Comisión estimada")],
          contribution.map(row=>[e(agentName(row.travel_agent)),e(row.bookings),this.amount(row.accepted_lodging,this.prop.currency),
            this.amount(row.estimated_commission,this.prop.currency)]))}</section>
      <section class="hs-section"><h2>${e(__("Reservas atribuidas"))}</h2>${this.table([__("Reserva"),__("Agencia"),__("Estado"),__("Base aceptada"),__("Comisión estimada"),__("Liquidación")],
        bookings.map(row=>[e(this.bookingLabel(row.name)),e(agentName(row.travel_agent)),e(__(row.status)),
          this.amount(row.amount,row.currency),this.amount(row.agent_commission_estimate,row.currency),
          row.agent_commission_invoice?`<a href="/app/purchase-invoice/${encodeURIComponent(row.agent_commission_invoice)}">${e(row.agent_commission_invoice)}</a>`:
          row.status==="Completed"&&Number(row.agent_commission_estimate)>0&&this.allowed("commission")?
            this.button("agent_commission",__("Liquidar"),row.name):e(__("Pendiente"))]))}</section>`);
  };
  Desk.prototype["render_travel-agents"]=Desk.prototype.render_travel_agents;

  Desk.prototype.action_travel_agent=async function(id=""){
    const row=board(this).agents.find(value=>value.name===id),key=frappe.utils.get_random(24);
    return this.dialog(row?__("Editar agencia"):__("Agregar agencia"),[
      f("agent_name",__("Nombre"),"Data",{reqd:1,default:row?.agent_name}),
      f("agent_type",__("Tipo"),"Select",{options:agentTypes,default:row?.agent_type||"Travel Agent"}),
      f("commission_pct",__("Comisión (%)"),"Percent",{default:row?.commission_pct||0}),
      f("supplier",__("Proveedor ERPNext para liquidar"),"Link",{options:"Supplier",default:row?.supplier}),
      f("contact_name",__("Contacto"),"Data",{default:row?.contact_name}),
      f("contact_phone",__("Teléfono"),"Data",{default:row?.contact_phone}),
      f("contact_email",__("Correo"),"Data",{default:row?.contact_email}),
      f("active",__("Activa"),"Check",{default:row?row.active:1})],
      async(v,d)=>{await this.mutate("travel_agent",{...v,...(row?{agent:row.name,modified:row.modified}:{})},key);d.hide();});
  };

  Desk.prototype.action_agent_commission=async function(id){
    const row=(this.data.bookings||[]).find(value=>value.name===id),key=frappe.utils.get_random(24);
    if(!row)return;
    const q=await this.call("preview",{property_name:this.property,action:"agent_commission",data:JSON.stringify({booking:id})});
    return this.dialog(__("Liquidar comisión de agencia"),[
      f("summary",__("Resumen"),"HTML",{options:`<p>${e(__("Reserva"))}: ${e(this.bookingLabel(id))}</p><p>${e(__("Base facturada"))}: ${e(this.amount(q.base,q.currency))} · ${e(q.percent)} %</p><h3>${e(this.amount(q.amount,q.currency))}</h3><p>${e(__("Se creará una factura de compra al proveedor de la agencia."))}</p>`})],
      async(_,d)=>{await this.mutate("agent_commission",{booking:id,modified:q.modified},key);d.hide();},__("Crear factura de comisión"));
  };

  Desk.prototype.action_agent_commission_setup=async function(){
    const config=await this.call("configuration",{property_name:this.property}),key=frappe.utils.get_random(24);
    return this.dialog(__("Configurar liquidación de agencias"),[
      f("agent_commission_item",__("Artículo de comisión de agencias"),"Link",{options:"Item",default:config.agent_commission_item,
        description:__("Artículo comprable sin inventario.")}),
      f("expense_account",__("Cuenta de gasto de comisiones"),"Link",{options:"Account",default:config.expense_account})],
      async(v,d)=>{await this.call("save_setup",{property_name:this.property,section:"property",
        data:JSON.stringify({agent_commission_item:v.agent_commission_item||null,expense_account:v.expense_account||null}),request_key:key,expected_modified:config.modified});
        d.hide();await this.load();});
  };

  Desk.prototype.render_experiences=function(el){
    const {experiences,orders}=board(this),name=id=>experiences.find(row=>row.name===id)?.experience_name||id;
    const totals=Object.fromEntries((board(this).order_totals||[]).map(row=>[row.status,row]));
    el.html(`<div class="hs-toolbar"><div><h2>${e(__("Experiencias"))}</h2><p>${e(__("Ofrezca experiencias en reservas y cargue al folio solo lo entregado."))}</p></div>
      ${this.allowed("setup")?this.button("experience",__("Agregar experiencia"),"","primary"):""}
      ${this.allowed("reserve")?this.button("experience_order",__("Agregar a reserva")):""}</div>
      <div class="hs-metrics"><article><span>${e(__("Por confirmar"))}</span><strong>${e(totals.Reserved?.orders||0)}</strong></article>
      <article><span>${e(__("Programadas"))}</span><strong>${e(totals.Confirmed?.orders||0)}</strong></article>
      <article><span>${e(__("Entregadas"))}</span><strong>${e(totals.Delivered?.orders||0)}</strong></article>
      <article><span>${e(__("Importe entregado"))}</span><strong>${e(this.amount(totals.Delivered?.amount||0,this.prop.currency))}</strong></article></div>
      <section class="hs-section"><h2>${e(__("Catálogo"))}</h2>${this.table([__("Experiencia"),__("Categoría"),__("Artículo"),__("Duración"),__("Portal"),__("Estado"),__("Acción")],
        experiences.map(row=>[e(row.experience_name),e(__(row.experience_category)),e(row.item),e(row.duration||"—"),
          e(row.show_on_booking_page?__("Sí"):__("No")),e(row.active?__("Activa"):__("Inactiva")),
          this.allowed("setup")?this.button("experience",__("Editar"),row.name):"—"]))}</section>
      <section class="hs-section"><h2>${e(__("Órdenes"))}</h2>${this.table([__("Reserva"),__("Experiencia"),__("Cantidad"),__("Importe"),__("Fecha"),__("Estado"),__("Acción")],
        orders.map(row=>[e(this.bookingLabel(row.booking)),e(name(row.experience)),e(row.quantity),
          this.amount(row.amount,row.currency),e(row.scheduled_at?this.date(row.scheduled_at):"—"),e(statusLabel[row.status]||row.status),
          row.status==="Reserved"||row.status==="Confirmed"?this.allowed("service")?this.button("experience_status",__("Gestionar"),row.name):"—":
          row.charge?e(row.charge):"—"]))}</section>`);
  };

  Desk.prototype.action_experience=async function(id=""){
    const row=board(this).experiences.find(value=>value.name===id),key=frappe.utils.get_random(24);
    return this.dialog(row?__("Editar experiencia"):__("Agregar experiencia"),[
      f("experience_name",__("Nombre"),"Data",{reqd:1,default:row?.experience_name}),
      f("experience_category",__("Categoría"),"Select",{options:categories,default:row?.experience_category||"Other"}),
      f("item",__("Artículo de venta ERPNext"),"Link",{options:"Item",reqd:1,default:row?.item}),
      f("duration",__("Duración"),"Data",{default:row?.duration}),
      f("description",__("Descripción"),"Small Text",{default:row?.description}),
      f("image_url",__("Imagen pública"),"Data",{default:row?.image_url}),
      f("show_on_booking_page",__("Mostrar en portal de reservas"),"Check",{default:row?.show_on_booking_page||0}),
      f("active",__("Activa"),"Check",{default:row?row.active:1})],
      async(v,d)=>{await this.mutate("experience",{...v,...(row?{experience:row.name,modified:row.modified}:{})},key);d.hide();});
  };

  Desk.prototype.action_experience_order=async function(){
    const key=frappe.utils.get_random(24),bookings=(this.data.bookings||[]).filter(row=>["Confirmed","Checked In"].includes(row.status)),
      active=board(this).experiences.filter(row=>row.active);
    return this.dialog(__("Agregar experiencia a reserva"),[
      f("booking",__("Reserva"),"Select",{reqd:1,_hsDataOptions:true,options:bookings.map(row=>({value:row.name,label:this.bookingLabel(row.name)}))}),
      f("experience",__("Experiencia"),"Select",{reqd:1,_hsDataOptions:true,options:active.map(row=>({value:row.name,label:row.experience_name}))}),
      f("quantity",__("Cantidad"),"Int",{reqd:1,default:1})],
      async(v,d)=>{const q=await this.call("preview",{property_name:this.property,action:"experience_order",data:JSON.stringify(v)});
        await this.dialog(__("Confirmar precio de experiencia"),[
          f("summary",__("Precio"),"HTML",{options:`<p>${e(q.line.name)} × ${e(q.line.quantity)}</p><h3>${e(this.amount(q.line.amount,q.currency))}</h3>`})],
          async(_,confirm)=>{await this.mutate("experience_order",{...v,acceptance:q.acceptance},key);confirm.hide();d.hide();},__("Agregar a reserva"));});
  };

  Desk.prototype.action_experience_status=async function(id){
    const row=board(this).orders.find(value=>value.name===id),key=frappe.utils.get_random(24);
    if(!row)return;
    const stays=(this.data.stays||[]).filter(value=>value.booking===row.booking&&value.status==="Active");
    const folios=(this.data.folios||[]).filter(value=>value.status==="Open"&&
      (stays.some(stay=>stay.name===value.stay)||value.booking===row.booking));
    return this.dialog(__("Gestionar experiencia"),[
      f("status",__("Acción"),"Select",{reqd:1,options:row.status==="Reserved"?["Confirmed","Cancelled"]:["Delivered","Cancelled"]}),
      f("scheduled_at",__("Fecha y hora programada"),"Datetime",{default:row.scheduled_at?
        moment.tz(row.scheduled_at,this.data.system_timezone).tz(this.prop.time_zone).format("YYYY-MM-DDTHH:mm"):undefined}),
      f("participants",__("Participantes"),"Int",{default:row.participants||row.quantity}),
      f("stay",__("Estancia que recibe el servicio"),"Select",{_hsDataOptions:true,
        options:[{value:"",label:__("Selección automática si hay una estancia")},...stays.map(value=>({value:value.name,label:this.roomName(value.room)}))]}),
      f("folio",__("Cuenta de estancia"),"Select",{_hsDataOptions:true,
        options:[{value:"",label:__("Cuenta principal si es única")},...folios.map(value=>({value:value.name,label:value.label}))]}),
      f("notes",__("Observaciones"),"Small Text",{default:row.notes}),
      f("reason",__("Motivo de cancelación"),"Small Text")],
      async(v,d)=>{await this.mutate("experience_status",{...v,order:id,modified:row.modified},key);d.hide();});
  };
})();
