/* Additional views and operational dialogs share the same authenticated commands. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const e=x=>frappe.utils.escape_html(String(x??""));
  const f=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),fieldtype:fieldtype==="Datetime"?"Data":fieldtype,_hsDateTime:fieldtype==="Datetime",...extra});
  const pick=(name,label,rows,labelKey="name",required=true)=>f(name,label,"Select",{reqd:required,options:[{value:"",label:"Seleccione…"},...rows.map(r=>({value:r.name,label:r[labelKey]||r.name}))]});
  const originalDialog=Desk.prototype.dialog;
  const button=Desk.prototype.button;
  const actions={reserve:"reserve",walk_in:"stay",extend:"stay",change_room:"stay",folio:"stay",move_charge:"stay",checkout:"stay",guest:"guest",open_shift:"finance",close_shift:"finance",payment:"finance",service:"service",service_status:"service",cleaning:"clean",incident:"incident",linen:"clean",setup:"setup",new_property:"setup",daily_close:"report",portal_convert:"reserve",withdrawal:"finance",guarantee:"approve",credit:"approve",billing_party:"setup",inspect_departure:"inspect",policies:"setup",denominations:"setup",adjustment:"approve",maintenance_parts:"maintain",maintenance_evidence:"maintain",incident_evidence:"incident",resolve_incident:"inspect",return_parts:"approve"};
  Desk.prototype.button=function(action,...args){if(actions[action]&&!this.allowed(actions[action]))return "";return button.call(this,action,...args);};
  Desk.prototype.dialog=async function(title,fields,submit,label,size){
    const dialog=await originalDialog.call(this,title,fields,submit,label,size);
    for(const df of fields){const control=dialog.fields_dict[df.fieldname];if(control?.$input)control.$input.attr("aria-label",__(df.label));}
    return dialog;
  };
  const reception=Desk.prototype.render_reception;
  Desk.prototype.render_reception=function(el){
    reception.call(this,el);
    const floors=[...new Set(this.data.rooms.map(r=>r.floor).filter(Boolean))].sort();
    el.find(".hs-toolbar").prepend(`<select class="form-control hs-extra-filter" id="hs-floor" aria-label="Filtrar por piso"><option value="">Todos los pisos</option>${floors.map(x=>`<option>${e(x)}</option>`).join("")}</select><select class="form-control hs-extra-filter" id="hs-category" aria-label="Filtrar por categoría"><option value="">Todas las categorías</option>${this.data.categories.map(c=>`<option value="${e(c.name)}">${e(c.category_name)}</option>`).join("")}</select>`);
    el.find(".hs-room").each((index,node)=>{node.dataset.floor=this.data.rooms[index].floor||"";node.dataset.category=this.data.rooms[index].category;});
    for(const key of ["floor","category"]){el.find(`#hs-${key}`).val(localStorage.getItem(`hs-${key}-${this.property}`)||"").on("change",event=>{localStorage.setItem(`hs-${key}-${this.property}`,event.target.value);this.filterRooms();});}
    this.filterRooms();
    if(this.allowed("stay")||this.allowed("finance"))this.call("room_balances",{property_name:this.property}).then(values=>{el.find(".hs-room").each((index,node)=>{const stay=this.data.occupied.find(s=>s.room===this.data.rooms[index].name);if(stay&&values[stay.name]!==undefined)$(node).find(".hs-room-info").append(`<small>${values[stay.name].shared?"Saldo compartido de grupo":"Saldo"}: <strong>${e(this.amount(values[stay.name].amount))}</strong></small>`);});}).catch(()=>{});
  };
  const filter=Desk.prototype.filterRooms;
  Desk.prototype.filterRooms=function(){filter.call(this);const floor=this.root.find("#hs-floor").val(),cat=this.root.find("#hs-category").val();this.root.find(".hs-room:visible").each((_,node)=>{if((floor&&node.dataset.floor!==floor)||(cat&&node.dataset.category!==cat))$(node).hide();});this.root.find(".hs-filter-empty").prop("hidden",this.root.find(".hs-room:visible").length>0);};
  const reservations=Desk.prototype.render_reservations;
  Desk.prototype.render_reservations=function(el){
    reservations.call(this,el);
    const start=(this.data.property_now||this.data.server_time).slice(0,10);
    el.prepend(`<section class="hs-section hs-calendar-section"><div class="hs-toolbar"><h2>Calendario por habitación</h2><label for="hs-calendar-date" class="sr-only">Fecha del calendario</label><input id="hs-calendar-date" type="date" class="form-control" value="${e(start)}" style="max-width:170px"></div><div class="hs-calendar" role="status">Cargando calendario…</div></section>`);
    el.find("#hs-calendar-date").on("change",event=>this.drawCalendar(el,event.target.value));
    this.drawCalendar(el,start);
    const portal=this.data.portal_requests||[];
    if(portal.length)el.append(`<section class="hs-section"><h2>Solicitudes del portal</h2>${this.table(["Solicitante","Fechas","Importe","Acción"],portal.map(r=>[e(r.full_name),`${e(this.date(r.starts_at))}<br>${e(this.date(r.ends_at))}`,this.amount(r.amount,r.currency),this.button("portal_convert","Revisar solicitud",r.name)]))}</section>`);
  };
  Desk.prototype.drawCalendar=async function(el,date){
    const hourly=this.prop.mode==="Motel",start=moment(date),end=start.clone().add(hourly?1:7,"days");
    try{
      const rows=await this.call("calendar",{property_name:this.property,starts_at:start.format("YYYY-MM-DD HH:mm:ss"),ends_at:end.format("YYYY-MM-DD HH:mm:ss")});
      const count=hourly?12:7,minutes=hourly?120:1440;
      const heads=Array.from({length:count},(_,i)=>start.clone().add(i*minutes,"minutes").format(hourly?"HH:mm":"ddd DD/MM"));
      const rooms=[...this.data.rooms,{name:"",room_number:"Por asignar"}];
      const html=this.table(["Habitación",...heads],rooms.map(room=>[e(room.room_number),...heads.map((_,i)=>{
        const a=start.clone().add(i*minutes,"minutes"),b=a.clone().add(minutes,"minutes");
        return rows.filter(r=>(r.room||"")===room.name&&moment(r.starts_at).isBefore(b)&&moment(r.ends_at).isAfter(a)).map(r=>{
          const action=r.stay?"detail":r.booking?"booking":"";
          const text=r.kind==="Stay"?"Estancia":r.kind==="Maintenance"?"Mantenimiento":"Reserva";
          return action?this.button(action,text,r.stay||r.booking):`<span class="hs-badge">${text}</span>`;
        }).join("")||"<span class='hs-calendar-free'>Libre</span>";
      })]));el.find(".hs-calendar").html(html);
    }catch(error){el.find(".hs-calendar").text("No se pudo cargar el calendario. Actualice la página.");}
  };
  Desk.prototype.action_booking=async function(id){
    const info=await this.call("booking_detail",{name:id}),b=info.booking,key=frappe.utils.get_random(24);
    if(!this.allowed("reserve")){frappe.msgprint({title:__("Reserva"),message:`${e(b.name)} · ${e(this.date(b.starts_at))} → ${e(this.date(b.ends_at))}`});return;}
    const options=b.status==="Hold"?[{value:"Confirmed",label:"Confirmar reserva"},{value:"Modify",label:"Modificar reserva"},{value:"Cancelled",label:"Cancelar"}]:b.status==="Checked In"?(info.allocations.length?[{value:"Check In",label:"Registrar entrada"}]:[]):b.status==="Confirmed"?[{value:"Check In",label:"Registrar entrada"},{value:"Modify",label:"Modificar reserva"},{value:"Cancelled",label:"Cancelar reserva"},{value:"No Show",label:"No presentada"}]:[];
    if(!options.length){frappe.msgprint({title:__("Reserva"),message:e(id)+" · "+e(b.status)});return;}
    const allocations=info.allocations.map(a=>{const line=b.rooms.find(r=>r.name===a.booking_room);return{...a,label:`Solicitud ${line?.idx||""} · ${this.data.categories.find(c=>c.name===a.category)?.category_name||"Categoría"} · ${a.room?this.roomName(a.room):"Por asignar"} · ${line?.people||1} persona(s)`};});
    return this.dialog("Gestionar reserva",[f("status","Acción","Select",{reqd:1,options}),{...pick("allocation","Habitación solicitada",allocations,"label",false),default:allocations.length===1?allocations[0].name:""},{...pick("guest","Huésped principal",this.data.guests,"full_name",false),default:b.guest},pick("room","Asignar habitación",this.data.rooms,"room_number",false),f("reason","Motivo","Small Text")],async(v,d)=>{
      if(v.status==="Modify"){d.hide();await this.action_booking_edit(id);return;}
      const values={...v,booking:b.name,modified:b.modified};
      if(v.status==="Check In"){
        const fees=await this.call("preview",{property_name:this.property,action:"check_in",data:JSON.stringify(values)});
        if(+fees.early||+fees.late){await this.dialog("Revisar cargos por horario",[f("fees","Cargos","HTML",{options:`<p>${e(fees.explanation)}</p><p>Entrada anticipada: ${e(this.amount(fees.early))}</p><p>Salida tardía programada: ${e(this.amount(fees.late))}</p>`})],async(x,c)=>{await this.mutate("check_in",{...values,timing_acceptance:fees.acceptance},key);c.hide();d.hide();},"Confirmar entrada");return;}
      }else if(["Cancelled","No Show"].includes(v.status)){
        const fee=await this.call("preview",{property_name:this.property,action:"booking_status",data:JSON.stringify(values)});
        if(+fee.amount){await this.dialog("Revisar penalización",[f("fee","Cargo","HTML",{options:`<h3>${e(this.amount(fee.amount,fee.currency))}</h3><p>La política configurada generará una factura y aplicará anticipos disponibles.</p>`})],async(x,c)=>{await this.mutate("booking_status",{...values,fee_acceptance:fee.acceptance},key);c.hide();d.hide();},"Confirmar");return;}
      }
      await this.mutate(v.status==="Check In"?"check_in":"booking_status",values,key);d.hide();
    },"Confirmar");
  };
  Desk.prototype.action_booking_edit=async function(id){
    const info=await this.call("booking_detail",{name:id}),b=info.booking,key=frappe.utils.get_random(24);
    const wall=value=>moment.tz(value,this.data.system_timezone).tz(this.prop.time_zone).format("YYYY-MM-DD HH:mm:ss");
    return this.dialog("Modificar reserva",[f("starts_at","Entrada","Datetime",{reqd:1,default:wall(b.starts_at)}),f("ends_at","Salida","Datetime",{reqd:1,default:wall(b.ends_at)}),{...pick("customer","Pagador",this.data.customers,"customer_name"),default:b.customer},f("rooms","Habitaciones","Table",{in_place_edit:true,reqd:1,data:b.rooms.map(r=>({category:r.category,room:r.room,people:r.people,extra_beds:r.extra_beds})),fields:[f("category","Categoría","Link",{options:"HS Category",reqd:1,in_list_view:1,get_query:()=>({filters:{property:this.property}})}),f("room","Habitación","Link",{options:"HS Room",in_list_view:1,get_query:()=>({filters:{property:this.property}})}),f("people","Personas","Int",{reqd:1,in_list_view:1})]}),f("reason","Motivo","Small Text",{reqd:1})],async(v,d)=>{
      const values={...v,booking:id,modified:b.modified},q=await this.call("preview",{property_name:this.property,action:"modify_reservation",data:JSON.stringify(values)});
      await this.dialog("Revisar nueva cotización",[f("price","Importe","HTML",{options:`<h3>${e(this.amount(q.amount,q.currency))}</h3><ul>${q.lines.map(r=>`<li>${e(r.explanation.join("; "))}</li>`).join("")}</ul>`})],async(x,c)=>{await this.mutate("modify_reservation",{...values,acceptance:q.acceptance},key);c.hide();d.hide();},"Confirmar modificación");
    },"Cotizar");
  };
  Desk.prototype.action_checkout=async function(id){
    const info=await this.call("stay_detail",{name:id}),q=await this.call("preview",{property_name:this.property,action:"departure",data:JSON.stringify({stay:id})});
    const key=frappe.utils.get_random(24);
    if(q.inspection_required&&!q.inspected){frappe.msgprint(__("La salida requiere inspección de supervisión. Use Inspeccionar salida en la estancia."));return;}
    if(+q.amount){return this.dialog("Liquidar tiempo de estancia",[f("quote","Cargo adicional","HTML",{options:`<h3>${e(this.amount(q.amount,q.currency))}</h3><p>${e(q.explanation.join("; "))}</p><p>Prepare la cuenta y cobre el saldo antes de registrar salida.</p>`}),pick("folio","Cuenta",info.folios,"label")],async(v,d)=>{await this.mutate("prepare_departure",{stay:id,folio:v.folio,acceptance:q.acceptance},key);d.hide();await this.action_detail(id);},"Preparar liquidación");}
    return this.dialog("Registrar salida",[f("review","Revisión","HTML",{options:"<p>Revise consumos, saldo y garantías. La salida generará la tarea de limpieza.</p>"}),f("credit_reason","Motivo de salida a crédito autorizada","Small Text")],async(v,d)=>{await this.mutate("check_out",{...v,stay:id,modified:info.stay.modified},key);d.hide();},"Confirmar salida");
  };
  Desk.prototype.action_inspect_departure=async function(id){const key=frappe.utils.get_random(24);return this.dialog("Inspeccionar salida",[f("notes","Revisión, minibar y daños","Small Text",{reqd:1})],async(v,d)=>{await this.mutate("inspect_departure",{stay:id,...v},key);d.hide();});};
  Desk.prototype.action_portal_convert=async function(id){
    const key=frappe.utils.get_random(24);return this.dialog("Confirmar solicitud del portal",[pick("guest","Huésped registrado",this.data.guests,"full_name"),pick("customer","Cliente pagador",this.data.customers,"customer_name")],async(v,d)=>{
      const data={...v,portal_request:id},q=await this.call("preview",{property_name:this.property,action:"convert_portal",data:JSON.stringify(data)});
      await this.dialog("Revisar cotización",[f("summary","Alojamiento","HTML",{options:`<h2>${e(this.amount(q.amount,q.currency))}</h2>`})],async(x,c)=>{await this.mutate("convert_portal",{...data,acceptance:q.acceptance},key);c.hide();d.hide();},"Confirmar reserva");
    },"Cotizar");
  };
  const cleaning=Desk.prototype.render_housekeeping;
  Desk.prototype.render_housekeeping=function(el){cleaning.call(this,el);if(this.allowed("clean"))el.find(".hs-toolbar").append(this.button("incident","Registrar novedad")+this.button("linen","Ropa de cama"));};
  Desk.prototype.action_incident=async function(){const key=frappe.utils.get_random(24);return this.dialog("Daño u objeto encontrado",[pick("room","Habitación",this.data.rooms,"room_number"),f("kind","Tipo","Select",{reqd:1,options:[{value:"Damage",label:"Daño"},{value:"Lost Property",label:"Objeto encontrado"}]}),f("description","Descripción","Small Text",{reqd:1})],async(v,d)=>{await this.mutate("incident",v,key);d.hide();});};
  Desk.prototype.action_linen=async function(){const key=frappe.utils.get_random(24);return this.dialog("Movimiento de ropa de cama",[pick("room","Habitación de referencia",this.data.rooms,"room_number"),pick("item","Artículo de inventario",(this.data.items||[]).filter(i=>i.is_stock_item),"item_name"),f("quantity","Cantidad","Float",{reqd:1}),f("direction","Movimiento","Select",{reqd:1,options:[{value:"Send",label:"Enviar a lavandería"},{value:"Receive",label:"Recibir de lavandería"},{value:"Loss",label:"Registrar pérdida"}]}),f("reason","Observaciones / motivo","Small Text")],async(v,d)=>{await this.mutate("linen",v,key);d.hide();});};
  Desk.prototype.action_report=async function(report){
    const show=async(filters)=>{const rows=await this.call("report",{property_name:this.property,report_name:report,filters:JSON.stringify(filters)}),headers=rows.length?Object.keys(rows[0]):[];
      const value=(k,v)=>e(["status","kind","type","cleaning_status","settlement_direction","purpose","classification"].includes(k)?(this.data.report_values?.[v]||v):v);
      const d=await this.dialog(report,[f("rows","Resultado","HTML",{options:`<p>Hasta 1 000 filas por consulta.</p>${this.table(headers.map(k=>this.data.report_labels?.[k]||k),rows.map(r=>headers.map(k=>value(k,r[k]))))}<div class="hs-dialog-actions"><button class="btn btn-secondary" data-format="xlsx">Exportar XLSX</button><button class="btn btn-secondary" data-format="pdf">Exportar PDF</button></div>`})],async(v,x)=>x.hide(),"Cerrar","extra-large");
      d.$wrapper.on("click","[data-format]",event=>{const format=$(event.currentTarget).data("format"),params=new URLSearchParams({property_name:this.property,report_name:report,filters:JSON.stringify(filters),file_format:format});window.open("/api/method/hospitality_suite.api.export_report?"+params.toString(),"_blank","noopener");});
    };
    const extra=report==="Movimientos de inventario"?[pick("warehouse","Almacén",this.data.warehouses||[],"warehouse_name",false),f("item","Artículo","Link",{options:"Item"}),f("purpose","Uso operativo","Select",{options:[{value:"",label:"Todos"},...["Purchase","Transfer","Cleaning","Waste","Linen Replacement","Maintenance","Laundry","Sale","Adjustment","Stock"].map(v=>({value:v,label:this.data.report_values?.[v]||v}))]})]:[f("status","Estado (opcional)"),pick("room","Habitación",this.data.rooms,"room_number",false)];
    return this.dialog(`Filtros · ${report}`,[f("from_date","Desde","Date"),f("to_date","Hasta","Date"),...extra],async(values,d)=>{await show(values);d.hide();},"Consultar");
  };
  const services=Desk.prototype.render_services;
  Desk.prototype.render_services=function(el){services.call(this,el);const section=$('<section class="hs-section"></section>').appendTo(el);const names={Merchandise:"Mercancía",Cleaning:"Limpieza",Linen:"Ropa de cama",Parts:"Repuesto",Asset:"Activo fijo"};const paint=async warehouse_name=>{try{const data=await this.call("inventory_status",{property_name:this.property,warehouse_name});section.html(`<h2>Existencias por ubicación</h2><label>Almacén <select class="form-control hs-stock-warehouse" aria-label="Almacén de existencias">${(this.data.warehouses||[{name:data.warehouse,warehouse_name:data.warehouse}]).map(w=>`<option value="${e(w.name)}" ${w.name===data.warehouse?"selected":""}>${e(w.warehouse_name)}</option>`).join("")}</select></label>${this.table(["Artículo","Clasificación","Disponible","Mínimo","Cantidad a reponer","Alerta"],data.items.map(r=>[e(r.item_name),e(names[r.purpose]||r.purpose),e(r.actual_qty??"Registro de activos"),e(r.minimum??"Sin configurar"),e(r.reorder_quantity??"—"),r.needs_restock?"Reponer":"—"]))}`);section.find(".hs-stock-warehouse").on("change",event=>paint(event.target.value));}catch{section.text("No se pudieron consultar las existencias. Actualice la vista.");}};paint();};
  const cashier=Desk.prototype.render_cashier;
  Desk.prototype.render_cashier=function(el){cashier.call(this,el);el.find(".hs-toolbar").append(this.button("withdrawal","Retirar / entregar efectivo")+this.button("guarantee","Aplicar garantía")+this.button("credit","Nota de crédito"));};
  Desk.prototype.action_withdrawal=async function(){const key=frappe.utils.get_random(24);return this.dialog("Retiro o entrega de efectivo",[pick("shift","Turno abierto",this.data.shifts.filter(s=>s.status==="Open")),pick("method","Medio en efectivo",this.data.payment_methods.filter(m=>m.is_cash),"mode_of_payment"),f("amount","Importe","Currency",{reqd:1}),f("reason","Motivo y responsable de la entrega","Small Text",{reqd:1})],async(v,d)=>{await this.mutate("withdrawal",v,key);d.hide();});};
  Desk.prototype.action_guarantee=async function(){const key=frappe.utils.get_random(24);return this.dialog("Aplicar garantía autorizada",[pick("source_payment","Garantía recibida",this.data.payments.filter(p=>p.kind==="Guarantee"&&p.status==="Posted")),pick("folio","Cuenta destino",this.data.folios,"label"),f("amount","Importe a aplicar","Currency",{reqd:1}),f("reason","Autorización y motivo","Small Text",{reqd:1})],async(v,d)=>{await this.mutate("apply_guarantee",v,key);d.hide();});};
  Desk.prototype.action_credit=async function(){const key=frappe.utils.get_random(24);return this.dialog("Nota de crédito",[f("invoice","Factura de origen","Link",{options:"Sales Invoice",reqd:1,get_query:()=>({filters:{hs_property:this.property,docstatus:1,is_return:0}})}),f("reason","Motivo","Small Text",{reqd:1})],async(v,d)=>{await this.mutate("credit_note",v,key);d.hide();},"Crear nota de crédito");};
  Desk.prototype.action_change_room=async function(id){
    const info=await this.call("stay_detail",{name:id}),key=frappe.utils.get_random(24);
    return this.dialog("Cambiar habitación",[pick("room","Habitación de destino",this.data.rooms.filter(r=>r.name!==info.stay.room),"room_number"),pick("folio","Cuenta para el ajuste",info.folios,"label"),f("mode","Modalidad (solo establecimiento mixto)","Select",{options:this.prop.mode==="Mixed"?[{value:"",label:"Conservar modalidad"},"Hotel","Motel"]:[this.prop.mode],default:this.prop.mode}),f("reason","Motivo","Small Text",{reqd:1})],async(v,d)=>{
      const values={...v,stay:id,modified:info.stay.modified},q=await this.call("preview",{property_name:this.property,action:"change_room",data:JSON.stringify(values)});
      await this.dialog("Revisar cambio de habitación",[f("calculation","Efecto tarifario","HTML",{options:`<p>${e(q.explanation)}</p><h3>Ajuste: ${e(this.amount(q.difference))}</h3><p>Vigente hasta ${e(q.valid_until)}</p>`})],async(x,c)=>{await this.mutate("change_room",{...values,acceptance:q.acceptance},key);c.hide();d.hide();},"Confirmar cambio");
    },"Cotizar cambio");
  };
  const setup=Desk.prototype.render_setup;
  Desk.prototype.render_setup=function(el){setup.call(this,el);el.find(".hs-shortcuts").append(this.button("billing_party","6. Empresas, agencias y crédito")+this.button("policies","7. Horarios y penalizaciones")+this.button("denominations","8. Denominaciones de caja"));};
  Desk.prototype.action_billing_party=async function(){const key=frappe.utils.get_random(24);return this.dialog("Empresa, agencia o crédito",[f("customer","Cliente de ERPNext","Link",{options:"Customer",reqd:1}),f("kind","Tipo","Select",{options:["Company","Agency","Individual"],reqd:1}),f("credit_authorized","Autorizar crédito","Check"),f("credit_limit","Límite en moneda del establecimiento","Currency"),f("valid_until","Vigente hasta","Date"),f("reason","Motivo de la autorización","Small Text",{reqd:1})],async(v,d)=>{await this.call("save_setup",{property_name:this.property,section:"billing_party",data:JSON.stringify(v),request_key:key});d.hide();await this.load();});};
  Desk.prototype.action_policies=async function(){const config=await this.call("configuration",{property_name:this.property}),key=frappe.utils.get_random(24);const fields=[f("check_in_time","Hora habitual de entrada","Time"),f("check_out_time","Hora habitual de salida","Time"),f("early_hour_rate","Entrada anticipada por hora","Currency"),f("late_hour_rate","Salida tardía por hora","Currency"),f("schedule_grace_minutes","Tolerancia de horario (minutos)","Int"),f("schedule_rounding_minutes","Fracción de horario (minutos)","Int"),f("timing_item","Artículo para cargos de horario","Link",{options:"Item"}),f("checkout_inspection_required","Exigir inspección antes de salir","Check"),f("checkout_quote_minutes","Minutos para completar salida liquidada","Int"),f("cancellation_fee_mode","Penalización de cancelación","Select",{options:["None","Fixed","First Night","Percent"]}),f("cancellation_fee_value","Importe fijo o porcentaje de cancelación","Currency"),f("no_show_fee_mode","Penalización por no presentación","Select",{options:["None","Fixed","First Night","Percent"]}),f("no_show_fee_value","Importe fijo o porcentaje de no presentación","Currency"),f("penalty_item","Artículo para penalizaciones","Link",{options:"Item"})].map(df=>({...df,default:config[df.fieldname]}));return this.dialog("Horarios y penalizaciones",fields,async(v,d)=>{await this.call("save_setup",{property_name:this.property,section:"property",data:JSON.stringify(v),request_key:key,expected_modified:config.modified});d.hide();await this.load();});};
  Desk.prototype.action_denominations=async function(){const config=await this.call("configuration",{property_name:this.property}),key=frappe.utils.get_random(24),values=JSON.parse(config.cash_denominations||"{}");const rows=Object.entries(values).flatMap(([currency,items])=>items.map(value=>({currency,value})));return this.dialog("Denominaciones de caja",[f("rows","Billetes y monedas que utiliza","Table",{data:rows,in_place_edit:true,fields:[f("currency","Moneda","Link",{options:"Currency",in_list_view:1,reqd:1}),f("value","Denominación","Currency",{in_list_view:1,reqd:1})]})],async(v,d)=>{const data={};for(const row of v.rows||[])(data[row.currency]||=[]).push(row.value);await this.call("save_setup",{property_name:this.property,section:"property",data:JSON.stringify({cash_denominations:JSON.stringify(data)}),request_key:key,expected_modified:config.modified});d.hide();await this.load();});};
  Desk.prototype.action_close_shift=async function(id){
    const shift=this.data.shifts.find(s=>s.name===id),key=frappe.utils.get_random(24),saved=JSON.parse(shift.denominations||"{}").counts||{};
    const currencies=[...new Set([...Object.keys(shift.expected_by_currency),...Object.keys(saved)])];
    const fields=currencies.map((currency,index)=>f("currency_"+index,`Arqueo ${currency} · esperado ${shift.expected_by_currency[currency]||0}`,"Table",{in_place_edit:true,data:saved[currency]||(this.data.denominations[currency]||[1]).map(value=>({value,count:0})),fields:[f("value","Denominación","Currency",{in_list_view:1,reqd:1}),f("count","Cantidad","Int",{in_list_view:1,reqd:1,default:0})]}));
    return this.dialog("Arqueo por denominaciones",[...fields,f("reason","Motivo de diferencias","Small Text"),f("approve","Aprobar diferencias (gerencia)","Check")],async(v,d)=>{const denominations={};currencies.forEach((currency,index)=>{denominations[currency]=v["currency_"+index]||[];});await this.mutate("close_shift",{shift:id,modified:shift.modified,denominations,reason:v.reason,approve:v.approve},key);d.hide();},"Cerrar turno");
  };
  Desk.prototype.action_adjustment=async function(id){const info=this.current?.stay.name===id?this.current:await this.call("stay_detail",{name:id}),key=frappe.utils.get_random(24);return this.dialog("Descuento, cortesía o recargo",[pick("charge","Cargo de origen",info.charges.filter(r=>r.status==="Pending"&&+r.amount>0),"description"),f("adjustment_type","Tipo","Select",{reqd:1,options:[{value:"Discount",label:"Descuento"},{value:"Courtesy",label:"Cortesía del saldo del cargo"},{value:"Surcharge",label:"Recargo"}]}),f("amount","Importe (cortesía usa el saldo completo)","Currency"),f("reason","Motivo y autorización","Small Text",{reqd:1})],async(v,d)=>{await this.mutate("adjustment",v,key);d.hide();});};
})();
