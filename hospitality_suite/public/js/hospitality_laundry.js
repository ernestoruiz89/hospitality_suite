/* Guest laundry: the property's rate card, bag counts, delivery and folio charges. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const e=value=>frappe.utils.escape_html(String(value??""));
  const f=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),fieldtype,...extra});
  const choice=(name,label,rows,labelKey="name")=>f(name,label,"Select",{reqd:1,_hsDataOptions:true,
    options:[{value:"",label:__("Seleccione…")},...rows.map(row=>({value:row.name,label:row[labelKey]||row.name}))]});
  const services=["Wash & Iron","Dry Clean","Iron Only"];
  const statusLabels={Requested:__("Recogida solicitada"),Collected:__("Recogida"),"In Process":__("En proceso"),Ready:__("Lista"),Delivered:__("Entregada"),Cancelled:__("Cancelada")};
  const order=(desk,id)=>(desk.data.laundry?.orders||[]).find(row=>row.name===id);
  const rateLabel=(desk,row)=>`${row.garment} · ${row.service_type} · ${desk.amount(row.rate,row.currency)}${row.express_rate?` / ${desk.amount(row.express_rate,row.currency)} ${__("exprés")}`:""}`;

  Desk.prototype.render_laundry=function(el){
    const laundry=this.data.laundry||{orders:[],rates:[],stays:[]};
    const open=laundry.orders.filter(o=>!["Delivered","Cancelled"].includes(o.status));
    const recent=laundry.orders.filter(o=>["Delivered","Cancelled"].includes(o.status)).slice(0,25);
    const active=laundry.stays||[];
    const card=o=>{
      const pieces=(o.items||[]).reduce((sum,row)=>sum+Number(row.quantity||0),0);
      const pending=(o.items||[]).reduce((sum,row)=>sum+Number(row.quantity||0)-Number(row.returned_quantity||0),0);
      const detail=(o.items||[]).map(row=>`${e(row.quantity)} × ${e(row.garment)} · ${e(row.service_type)}${o.status==="Ready"?` (${e(row.returned_quantity)}/${e(row.quantity)} ${e(__("devueltas"))})`:""}`).join("<br>");
      const next=o.status==="Requested"?this.button("laundry_collect",__("Recoger y contar"),o.name,"primary"):
        o.status==="Collected"?this.button("laundry_advance",__("Enviar a proceso"),o.name):
        o.status==="In Process"?this.button("laundry_advance",__("Marcar lista"),o.name):
        this.button("laundry_return",__("Contar devolución"),o.name)+
          (this.allowed("service")?this.button("laundry_deliver",__("Entregar y cargar al folio"),o.name,"primary"):"");
      return `<article class="hs-task"><div class="hs-task-top"><strong>${e(o.name)} · ${e(__("Habitación"))} ${e(this.roomName(o.room))}</strong><span class="hs-badge">${e(statusLabels[o.status]||o.status)}</span></div>
        <p>${e(o.stay)} · ${pieces} ${e(__("piezas"))}${o.express?` · ${e(__("Exprés"))}`:""}${o.complimentary?` · ${e(__("Cortesía"))}`:""}</p>
        ${detail?`<p>${detail}</p>`:""}${o.ready_by?`<p class="hs-note">${e(__("Entrega prevista"))}: ${e(this.date(o.ready_by))}</p>`:""}
        <p>${e(__("Cotización"))}: ${e(this.amount(o.total,o.currency))}${o.status==="Ready"?` · ${pending} ${e(__("piezas pendientes"))}`:""}</p>
        ${o.ready_by&&["Collected","In Process","Ready"].includes(o.status)&&moment.tz(o.ready_by,this.data.system_timezone).valueOf()<this.serverNow()?`<p class="hs-note">${e(__("Entrega atrasada"))}</p>`:""}
        ${o.notes?`<p>${e(o.notes)}</p>`:""}${o.shortage_note?`<p>${e(__("Faltante"))}: ${e(o.shortage_note)}</p>`:""}
        <div class="hs-dialog-actions">${next}${this.button("laundry_print",__("Imprimir comprobante"),o.name)}${this.button("laundry_cancel",__("Cancelar"),o.name)}</div></article>`;
    };
    el.html(`<div class="hs-toolbar"><div><h2>${e(__("Lavandería de huéspedes"))}</h2><p>${e(__("Recogida, lavado, devolución y cargo al folio."))}</p></div>
      ${active.length?this.button("laundry_request",__("Solicitar recogida"),"","primary")+this.button("laundry_collect_now",__("Recoger ahora")):""}</div>
      <div class="hs-metrics"><article><span>${e(__("Solicitudes pendientes"))}</span><strong>${open.filter(o=>o.status==="Requested").length}</strong></article>
      <article><span>${e(__("Bolsas en proceso"))}</span><strong>${open.filter(o=>["Collected","In Process"].includes(o.status)).length}</strong></article>
      <article><span>${e(__("Listas para entregar"))}</span><strong>${open.filter(o=>o.status==="Ready").length}</strong></article>
      <article><span>${e(__("Cargos entregados · 30 días"))}</span><strong>${e(this.amount(laundry.last_30_days?.charges||0,laundry.last_30_days?.currency))}</strong></article></div>
      <section class="hs-section"><div class="hs-toolbar"><h2>${e(__("Pedidos abiertos"))}</h2></div>
        <div class="hs-task-grid">${open.length?open.map(card).join(""):this.empty(__("No hay pedidos de lavandería pendientes"))}</div></section>
      <section class="hs-section"><h2>${e(__("Entregas recientes"))}</h2>${this.table([__("Orden"),__("Habitación"),__("Estado"),__("Piezas"),__("Cotizado"),__("Cargado al folio")],recent.map(o=>[
        e(o.name),e(this.roomName(o.room)),e(statusLabels[o.status]||o.status),e((o.items||[]).reduce((n,row)=>n+Number(row.returned_quantity||0),0)),
        e(this.amount(o.total,o.currency)),e(this.amount(o.billed_total,o.currency))+" "+this.button("laundry_print",__("Imprimir"),o.name)]))}</section>
      <section class="hs-section"><h2>${e(__("Últimos 30 días por servicio"))}</h2>${this.table([__("Servicio"),__("Piezas devueltas"),__("Cargos registrados")],(laundry.last_30_days?.by_service||[]).map(r=>[
        e(r.service_type),e(r.pieces),e(this.amount(r.charges,laundry.last_30_days.currency))]))}</section>
      <section class="hs-section"><div class="hs-toolbar"><div><h2>${e(__("Tarifario por prenda"))}</h2><p>${e(__("Cada tarifa se vincula a un artículo de venta sin inventario de ERPNext."))}</p></div>
        ${this.allowed("setup")?this.button("laundry_rate",__("Añadir tarifa")):""}</div>
        ${this.table([__("Prenda"),__("Servicio"),__("Normal"),__("Exprés"),__("Estado"),__("Acción")],laundry.rates.map(r=>[
          e(r.garment),e(r.service_type),e(this.amount(r.rate,r.currency)),e(r.express_rate?this.amount(r.express_rate,r.currency):"—"),
          r.active?e(__("Activa")):e(__("Inactiva")),this.allowed("setup")?this.button("laundry_rate",__("Editar"),r.name):"—"]))}</section>`);
  };

  Desk.prototype.action_laundry_request=async function(){
    const key=frappe.utils.get_random(24),stays=(this.data.laundry?.stays||[]).map(s=>({...s,label:`${this.roomName(s.room)} · ${s.name}`}));
    return this.dialog(__("Solicitar recogida de lavandería"),[choice("stay",__("Estancia y habitación"),stays,"label"),
      f("express",__("Servicio exprés"),"Check"),f("notes",__("Observaciones para recogida"),"Small Text")],
      async(v,d)=>{await this.mutate("laundry_request",v,key);d.hide();},__("Registrar solicitud"));
  };
  Desk.prototype.action_laundry_collect=async function(id){
    const o=order(this,id),rates=(this.data.laundry?.rates||[]).filter(r=>r.active);
    if(!rates.length){frappe.msgprint(__("Configure primero el tarifario de lavandería."));return;}
    const key=frappe.utils.get_random(24),options=rates.map(r=>({value:r.name,label:rateLabel(this,r)}));
    const stays=(this.data.laundry?.stays||[]).map(s=>({...s,label:`${this.roomName(s.room)} · ${s.name}`}));
    return this.dialog(`${__("Recoger y contar")}${o?` · ${this.roomName(o.room)}`:""}`,[
      ...(!o?[choice("stay",__("Estancia y habitación"),stays,"label"),f("express",__("Servicio exprés"),"Check")]:[]),
      f("items",__("Prendas y servicios"),"Table",{reqd:1,in_place_edit:true,data:[{rate:"",quantity:1}],fields:[
        f("rate",__("Prenda y servicio"),"Select",{reqd:1,in_list_view:1,_hsDataOptions:true,options:[{value:"",label:__("Seleccione…")},...options]}),
        f("quantity",__("Cantidad"),"Int",{reqd:1,in_list_view:1,default:1})]}),
      ...(this.allowed("approve")?[f("complimentary",__("Cortesía sin cargo"),"Check")]:[]),
      f("notes",__("Observaciones"),"Small Text",{default:o?.notes||""})],
      async(v,d)=>{await this.mutate("laundry_collect",{order:id||undefined,modified:o?.modified,...v},key);d.hide();},__("Confirmar prendas"));
  };
  Desk.prototype.action_laundry_collect_now=function(){return this.action_laundry_collect("");};
  Desk.prototype.action_laundry_advance=async function(id){
    const o=order(this,id),target=o.status==="Collected"?"In Process":"Ready";
    await this.mutate("laundry_advance",{order:id,modified:o.modified,status:target},frappe.utils.get_random(24));
  };
  Desk.prototype.action_laundry_return=async function(id){
    const o=order(this,id),key=frappe.utils.get_random(24),fields=o.items.flatMap((row,index)=>[
      f(`piece_${index}`,`${row.garment} · ${row.service_type} (${row.quantity} ${__("recogidas")})`,"Int",{reqd:1,default:row.returned_quantity||0})]);
    return this.dialog(`${__("Contar devolución")} · ${o.name}`,fields,async(v,d)=>{
      const counts={};o.items.forEach((row,index)=>{counts[row.name]=Number(v[`piece_${index}`]);});
      await this.mutate("laundry_return",{order:id,modified:o.modified,counts},key);d.hide();},__("Guardar conteo"));
  };
  Desk.prototype.action_laundry_deliver=async function(id){
    const o=order(this,id),key=frappe.utils.get_random(24);
    const pending=o.items.reduce((n,row)=>n+Number(row.quantity)-Number(row.returned_quantity||0),0);
    const bill=o.complimentary?0:o.items.reduce((n,row)=>n+Number(row.rate)*Number(row.returned_quantity||0),0);
    return this.dialog(`${__("Entregar lavandería")} · ${o.name}`,[
      f("review",__("Resumen antes de confirmar"),"HTML",{options:`<p>${e(__("Piezas faltantes"))}: <strong>${e(pending)}</strong></p><p>${e(__("Cargo previsto al folio"))}: <strong>${e(this.amount(bill,o.currency))}</strong></p>`}),
      ...(pending?[f("shortage_note",__("Explicación de piezas faltantes; requiere Gerencia"),"Small Text",{reqd:1})]:[])],
      async(v,d)=>{await this.mutate("laundry_deliver",{order:id,modified:o.modified,...v},key);d.hide();},__("Entregar y registrar cargo"));
  };
  Desk.prototype.action_laundry_cancel=async function(id){
    const o=order(this,id),key=frappe.utils.get_random(24);
    return this.dialog(`${__("Cancelar lavandería")} · ${o.name}`,[f("reason",__("Motivo"),"Small Text",{reqd:1})],
      async(v,d)=>{await this.mutate("laundry_cancel",{order:id,modified:o.modified,...v},key);d.hide();},__("Cancelar orden"));
  };
  Desk.prototype.action_laundry_rate=async function(id){
    const old=(this.data.laundry?.rates||[]).find(r=>r.name===id),key=frappe.utils.get_random(24);
    return this.dialog(old?__("Editar tarifa de lavandería"):__("Nueva tarifa de lavandería"),[
      f("garment",__("Prenda"),"Data",{reqd:1,default:old?.garment||""}),
      f("service_type",__("Servicio"),"Select",{reqd:1,options:services.map(value=>({value,label:({"Wash & Iron":__("Lavar y planchar"),"Dry Clean":__("Lavado en seco"),"Iron Only":__("Solo planchado")})[value]})),default:old?.service_type||services[0]}),
      f("item",__("Artículo de venta sin inventario"),"Link",{options:"Item",reqd:1,default:old?.item||"",get_query:()=>({filters:{is_sales_item:1,is_stock_item:0,disabled:0}})}),
      f("rate",__("Tarifa normal"),"Currency",{reqd:1,default:old?.rate||0}),
      f("express_rate",__("Tarifa exprés (opcional)"),"Currency",{default:old?.express_rate||0}),
      f("active",__("Activa"),"Check",{default:old?old.active:1})],
      async(v,d)=>{await this.mutate("laundry_rate",{...v,rate_name:old?.name,modified:old?.modified,
        express_rate:Number(v.express_rate)>0?v.express_rate:null},key);d.hide();},__("Guardar tarifa"));
  };
  Desk.prototype.action_laundry_print=function(id){
    if(order(this,id))window.open(`/printview?doctype=HS%20Laundry%20Order&name=${encodeURIComponent(id)}&format=${encodeURIComponent("HS Comprobante de lavandería")}`,"_blank","noopener");
  };
})();
