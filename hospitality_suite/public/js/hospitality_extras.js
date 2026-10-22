/* Additional views and operational dialogs share the same authenticated commands. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const e=x=>frappe.utils.escape_html(String(x??""));
  const f=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),fieldtype:fieldtype==="Datetime"?"Data":fieldtype,_hsDateTime:fieldtype==="Datetime",...extra});
  const pick=(name,label,rows,labelKey="name",required=true)=>f(name,label,"Select",{reqd:required,_hsDataOptions:true,options:[{value:"",label:__("Seleccione…")},...rows.map(r=>({value:r.name,label:r[labelKey]||r.name}))]});
  const originalDialog=Desk.prototype.dialog;
  const button=Desk.prototype.button;
  const actions={reserve:"reserve",availability:"reserve",walk_in:"stay",extend:"stay",change_room:"stay",folio:"stay",move_charge:"stay",checkout:"stay",guest:"guest",open_shift:"finance",close_shift:"finance",payment:"finance",service:"service",service_status:"service",cleaning:"clean",incident:"incident",linen:"clean",setup:"setup",new_property:"setup",daily_close:"report",portal_convert:"reserve",portal_reject:"reserve",withdrawal:"finance",guarantee:"approve",credit:"approve",billing_party:"setup",inspect_departure:"inspect",policies:"setup",denominations:"setup",adjustment:"approve",maintenance_parts:"maintain",maintenance_evidence:"maintain",incident_evidence:"incident",resolve_incident:"inspect",return_parts:"approve",rework_cleaning:"inspect",room_block:"block",room_unblock:"block"};
  Desk.prototype.button=function(action,...args){if(actions[action]&&!this.allowed(actions[action]))return "";return button.call(this,action,...args);};
  Desk.prototype.dialog=async function(title,fields,submit,label,size){
    const dialog=await originalDialog.call(this,title,fields,submit,label,size);
    for(const df of fields){const control=dialog.fields_dict[df.fieldname];if(control?.$input)control.$input.attr("aria-label",__(df.label));}
    return dialog;
  };
  const reservations=Desk.prototype.render_reservations;
  Desk.prototype.render_reservations=function(el){
    reservations.call(this,el);
    const start=(this.data.property_now||this.data.server_time).slice(0,10);
    el.append(`<section class="hs-section hs-calendar-section"><div class="hs-toolbar"><h2>${frappe.utils.escape_html(__("Calendario por habitación"))}</h2><label for="hs-calendar-date" class="sr-only">${frappe.utils.escape_html(__("Fecha del calendario"))}</label><input id="hs-calendar-date" type="date" class="form-control" value="${e(start)}" style="max-width:170px"></div><div class="hs-calendar" role="status">${frappe.utils.escape_html(__("Cargando calendario…"))}</div></section>`);
    el.find("#hs-calendar-date").on("change",event=>this.drawCalendar(el,event.target.value));
    this.drawCalendar(el,start);
    if(this.allowed("reserve")&&this.data.categories?.length){
      const modes=this.prop.mode==="Mixed"?["Hotel","Por tiempo","Day Pass"]:this.prop.mode==="Por tiempo"?["Por tiempo","Day Pass"]:[this.prop.mode];
      el.append(`<section class="hs-section hs-rate-section"><h2>${e(__("Calendario de tarifas"))}</h2><p class="hs-note">${e(__("Cotización orientativa por categoría. El precio y el cupo se vuelven a comprobar al reservar."))}</p><div class="hs-rate-filters"><label>${e(__("Categoría"))}<select id="hs-rate-category" class="form-control">${this.data.categories.map(row=>`<option value="${e(row.name)}">${e(row.category_name)}</option>`).join("")}</select></label><label>${e(__("Desde"))}<input id="hs-rate-date" type="date" class="form-control" value="${e(start)}"></label><label>${e(__("Días"))}<select id="hs-rate-days" class="form-control"><option value="7">7</option><option value="14" selected>14</option><option value="31">31</option></select></label><label>${e(__("Personas por habitación"))}<input id="hs-rate-people" type="number" min="1" value="1" class="form-control"></label><label>${e(__("Modalidad"))}<select id="hs-rate-mode" class="form-control">${modes.map(mode=>`<option value="${e(mode)}">${e(mode==="Por tiempo"?__("Por tiempo"):mode==="Day Pass"?__("Day Pass"):__("Hotel"))}</option>`).join("")}</select></label><label class="hs-rate-hours" ${modes[0]==="Por tiempo"?"":"hidden"}>${e(__("Horas del bloque"))}<input id="hs-rate-hours" type="number" min="1" max="24" value="3" class="form-control"></label></div><div class="hs-rate-results" role="status"></div></section>`);
      const selected=()=>({category:el.find("#hs-rate-category").val(),from_date:el.find("#hs-rate-date").val(),days:Number(el.find("#hs-rate-days").val()),
        people:Number(el.find("#hs-rate-people").val()),mode:el.find("#hs-rate-mode").val(),hours:Number(el.find("#hs-rate-hours").val())});
      el.find(".hs-rate-filters").on("change",event=>{if(event.target?.id==="hs-rate-mode"){
        const dayPass=event.target.value==="Day Pass";
        el.find(".hs-rate-hours").prop("hidden",event.target.value==="Hotel");
        el.find("#hs-rate-hours").attr("max",dayPass?15:24).val(dayPass?8:3);
      }this.drawRateCalendar(el,selected());});
      this.drawRateCalendar(el,{category:this.data.categories[0].name,from_date:start,days:14,people:1,mode:modes[0],hours:3});
    }
    const portal=this.data.portal_requests||[];
    if(portal.length)el.append(`<section class="hs-section"><h2>${frappe.utils.escape_html(__("Solicitudes del portal"))}</h2>${this.table([__("Solicitante"),__("Fechas"),__("Estado"),__("Importe consultado"),__("Acción")],portal.map(r=>[e(r.full_name),`${e(this.date(r.starts_at))}<br>${e(this.date(r.ends_at))}`,e(r.status==="Requested"?__("Sin retención"):__("Cupo retenido")),this.amount(r.amount,r.currency),this.button("portal_convert",__("Revisar solicitud"),r.name)+this.button("portal_reject",__("Rechazar"),r.name)]))}</section>`);
  };
  Desk.prototype.drawCalendar=async function(el,date){
    const sequence=this.calendarSequence=(this.calendarSequence||0)+1,property=this.property,zone=this.prop.time_zone;
    const target=el.find(".hs-calendar"),hourly=this.prop.mode==="Por tiempo",start=moment.tz(date,"YYYY-MM-DD",zone),end=start.clone().add(hourly?1:7,"days");
    const rooms=[...this.data.rooms,{name:"",room_number:__("Por asignar")}],current=()=>this.calendarSequence===sequence&&this.property===property;
    if(!start.isValid()||start.format("YYYY-MM-DD")!==date){el.find("#hs-calendar-date").attr("aria-invalid","true");target.attr("aria-busy","false").html(`<p role="alert">${e(__("Seleccione una fecha válida para el calendario."))}</p>`);return;}
    el.find("#hs-calendar-date").attr("aria-invalid","false");target.attr("aria-busy","true").html(`<p role="status">${e(__("Cargando calendario…"))}</p>`);
    try{
      const rows=await this.call("calendar",{property_name:property,starts_at:start.format("YYYY-MM-DDTHH:mm:ssZ"),ends_at:end.format("YYYY-MM-DDTHH:mm:ssZ")});
      if(!current())return;
      if(!Array.isArray(rows))throw Error("Unexpected calendar data");
      const count=hourly?12:7,minutes=hourly?120:1440;
      let weekday;
      try{weekday=new Intl.DateTimeFormat((frappe.boot?.lang||"es").replaceAll("_","-"),{weekday:"short",timeZone:zone});}
      catch{weekday=new Intl.DateTimeFormat("es",{weekday:"short",timeZone:zone});}
      const heads=Array.from({length:count},(_,i)=>{const column=start.clone().add(i*minutes,"minutes");return hourly?column.format("HH:mm"):`${weekday.format(column.valueOf())} ${column.format("DD/MM")}`;});
      const rangeStart=Date.parse(start.format("YYYY-MM-DDTHH:mm:ssZ")),rangeEnd=Date.parse(end.format("YYYY-MM-DDTHH:mm:ssZ"));
      if(!Number.isFinite(rangeStart)||!Number.isFinite(rangeEnd)||rangeEnd<=rangeStart||rows.some(row=>!Number.isFinite(Date.parse(row.starts_at))||!Number.isFinite(Date.parse(row.ends_at))))throw Error("Invalid calendar interval");
      const compact=[];
      const timeline=rooms.map(room=>{
        const bookings=rows.filter(row=>(row.room||"")===room.name&&Date.parse(row.starts_at)<rangeEnd&&Date.parse(row.ends_at)>rangeStart)
          .sort((a,b)=>Date.parse(a.starts_at)-Date.parse(b.starts_at));
        const bars=bookings.map((row,lane)=>{
          const left=Math.max(0,(Date.parse(row.starts_at)-rangeStart)/(rangeEnd-rangeStart)*100);
          const right=Math.min(100,(Date.parse(row.ends_at)-rangeStart)/(rangeEnd-rangeStart)*100);
          const action=row.stay?"detail":row.booking?"booking":null;
          const label=row.kind==="Stay"?__("Estancia"):row.kind==="Maintenance"?__("Mantenimiento"):row.kind==="Room Block"?`${__("Bloqueo")} · ${window.hospitality_suite.room_block_reason(row.block_reason)}`:__("Reserva");
          const period=`${this.date(row.starts_at)} → ${this.date(row.ends_at)}`;
          const short=right-left<7.5;
          if(short)compact.push({room:room.room_number,label,period,action,id:row.stay||row.booking});
          const content=!short&&action?this.button(action,`${label} · ${period}`,row.stay||row.booking):`<span>${e(label)} · ${e(period)}</span>`;
          const tone=row.kind==="Stay"?"is-stay":row.kind==="Maintenance"?"is-maintenance":row.kind==="Room Block"?"is-block":"is-reservation";
          return `<div class="hs-timeline-bar ${tone}${short?" is-short":""}" title="${e(label)} · ${e(period)}" style="left:${left.toFixed(4)}%;width:${Math.max(0,right-left).toFixed(4)}%;top:${lane*38+4}px">${content}</div>`;
        }).join("");
        const clean=room.cleaning_status?`<small>${e(__(room.cleaning_status))}</small>`:"";
        return `<div class="hs-timeline-row"><div class="hs-timeline-room"><strong>${e(room.room_number)}</strong>${clean}</div><div class="hs-timeline-track" style="--hs-slots:${count};min-height:${Math.max(44,bookings.length*38+8)}px">${bars||`<span class="hs-timeline-empty">${e(__("Sin asignación"))}</span>`}</div></div>`;
      }).join("");
      const ticks=`<div class="hs-timeline-header"><span>${e(__("Habitación"))}</span><div class="hs-timeline-ticks" style="--hs-slots:${count}">${heads.map(head=>`<span>${e(head)}</span>`).join("")}</div></div>`;
      const legend=`<p class="hs-timeline-legend"><span class="is-reservation">${e(__("Reserva"))}</span><span class="is-stay">${e(__("Estancia"))}</span><span class="is-maintenance">${e(__("Mantenimiento"))}</span><span class="is-block">${e(__("Bloqueo"))}</span><small>${e(__("Una celda sin asignación no confirma disponibilidad. Consulte el período antes de reservar."))}</small></p>`;
      const compactList=compact.length?`<details class="hs-timeline-short" ${compact.length<=5?"open":""}><summary>${e(__("Intervalos breves"))} (${compact.length})</summary><p>${e(__("Las marcas estrechas conservan su duración a escala; abra aquí el detalle de cada intervalo."))}</p>${this.table([__("Habitación"),__("Tipo"),__("Intervalo"),__("Acción")],compact.map(row=>[e(row.room),e(row.label),e(row.period),row.action?this.button(row.action,__("Ver detalle"),row.id):"—"]))}</details>`:"";
      el.find(".hs-calendar").html(`<div class="hs-timeline-scroll"><div class="hs-timeline-chart" role="region" aria-label="${e(__("Calendario por habitación"))}">${ticks}${timeline}</div></div>${legend}${compactList}`);
    }catch(error){if(current())target.html(`<p role="alert">${e(__("No se pudo cargar el calendario. Cambie la fecha o pulse Actualizar para reintentar."))}</p>`);}
    finally{if(current())target.attr("aria-busy","false");}
  };
  Desk.prototype.drawRateCalendar=async function(el,selection){
    const sequence=this.rateCalendarSequence=(this.rateCalendarSequence||0)+1,property=this.property,target=el.find(".hs-rate-results");
    const current=()=>this.rateCalendarSequence===sequence&&this.property===property;
    const date=String(selection.from_date||""),parsed=new Date(`${date}T12:00:00Z`);
    const validDate=/^\d{4}-\d{2}-\d{2}$/.test(date)&&Number.isFinite(parsed.valueOf())&&parsed.toISOString().slice(0,10)===date;
    const category=this.data.categories?.find(row=>row.name===selection.category);
    const valid=validDate&&category&&[7,14,31].includes(selection.days)&&Number.isInteger(selection.people)&&selection.people>=1&&selection.people<=Number(category.capacity||9999)&&
      ["Hotel","Por tiempo","Day Pass"].includes(selection.mode)&&(this.prop.mode==="Mixed"||this.prop.mode===(selection.mode==="Day Pass"?"Por tiempo":selection.mode))&&Number.isInteger(selection.hours)&&selection.hours>=1&&selection.hours<=(selection.mode==="Day Pass"?15:24);
    if(!valid){target.attr("aria-busy","false").html(`<p role="alert">${e(__("Revise fecha, categoría, modalidad y cantidad de personas."))}</p>`);return;}
    target.attr("aria-busy","true").html(`<p role="status">${e(__("Consultando tarifas y cupo…"))}</p>`);
    try{
      const data=await this.call("rate_calendar",{property_name:property,...selection});if(!current())return;
      if(data?.property!==property||data?.category!==selection.category||data?.from_date!==date||data?.days!==selection.days||data?.read_only!==true||!Array.isArray(data.rows)||data.rows.length!==selection.days)throw Error("Unexpected rate calendar");
      const cells=data.rows.map(row=>{
        const issues={no_rate:__("Sin tarifa"),collision:__("Tarifas con la misma prioridad"),wrong_currency:__("Tarifa en otra moneda"),review_rate:__("Tarifa por revisar")};
        const rate=row.rate_status==="ok"?e(row.rate_title||row.rate||__("Tarifa aplicable")):e(issues[row.rate_status]||__("Tarifa por revisar"));
        const amount=row.rate_status==="ok"&&row.amount!==null?e(this.amount(row.amount,row.currency)):"—";
        const stock=Number.isInteger(row.available)&&row.available>=0?(row.available?__("{0} con cupo",[row.available]):__("Sin cupo")):__("Cupo por revisar");
        return `<tr><th scope="row">${e(row.date?.split("-").reverse().join("/")||"")}</th><td>${rate}</td><td>${amount}</td><td>${e(stock)}</td></tr>`;
      }).join("");
      const interval=selection.mode==="Hotel"?__("Muestra por día: entrada 14:00, salida 11:00 del día siguiente."):selection.mode==="Day Pass"?__("Muestra Day Pass: inicio 08:00, duración {0} horas; salida el mismo día.",[selection.hours]):__("Muestra por bloque: inicio 14:00, duración {0} horas.",[selection.hours]);
      target.html(`<p class="hs-note">${e(interval)} ${e(__("La tarifa muestra la regla aplicable y no garantiza el cupo futuro."))}</p><div class="hs-table-wrap" tabindex="0"><table class="hs-table"><thead><tr><th>${e(__("Fecha"))}</th><th>${e(__("Tarifa"))}</th><th>${e(__("Precio"))}</th><th>${e(__("Cupo"))}</th></tr></thead><tbody>${cells}</tbody></table></div>`);
    }catch{if(current())target.html(`<p role="alert">${e(__("No se pudo consultar el calendario de tarifas. Revise los datos y vuelva a intentar."))}</p>`);}
    finally{if(current())target.attr("aria-busy","false");}
  };
  Desk.prototype.action_booking=async function(id){
    const property=this.property,info=await this.call("booking_detail",{name:id}),b=info.booking,key=frappe.utils.get_random(24);
    if(this.property!==property||b.property!==property)return;
    const summary=f("booking_summary",__("Resumen de la reserva"),"HTML",{options:this.booking_summary(info)});
    const options=b.status==="Hold"?[{value:"Confirmed",label:__("Confirmar reserva")},{value:"Modify",label:__("Modificar reserva")},{value:"Cancelled",label:__("Cancelar")}]:b.status==="Checked In"?(info.allocations.length?[{value:"Check In",label:__("Registrar entrada")}]:[]):b.status==="Confirmed"?[{value:"Check In",label:__("Registrar entrada")},{value:"Modify",label:__("Modificar reserva")},{value:"Cancelled",label:__("Cancelar reserva")},{value:"No Show",label:__("No presentada")}]:[];
    if(!this.allowed("reserve")||!options.length){
      const dialog=await this.dialog(__("Ver reserva"),[summary],async(v,d)=>d.hide(),__("Cerrar"));
      return this.bind_booking_summary(dialog,property);
    }
    const allocations=info.allocations.map(a=>{const line=b.rooms.find(r=>r.name===a.booking_room);return{...a,label:__("Solicitud {0} · {1} · {2} · {3} persona(s)",[line?.idx||"",this.data.categories.find(c=>c.name===a.category)?.category_name||__("Categoría"),a.room?this.roomName(a.room):__("Por asignar"),line?.people||1])};});
    const dialog=await this.dialog(__("Gestionar reserva"),[summary,f("_booking_actions",__("Acciones disponibles"),"Section Break"),f("status",__("Acción"),"Select",{reqd:1,options}),{...pick("allocation",__("Habitación solicitada"),allocations,"label",false),default:allocations.length===1?allocations[0].name:"",depends_on:doc=>doc.status==="Check In",mandatory_depends_on:doc=>doc.status==="Check In"},{...pick("guest",__("Huésped principal"),this.data.guests,"full_name",false),default:b.guest,depends_on:doc=>doc.status==="Check In",mandatory_depends_on:doc=>doc.status==="Check In"},{...pick("room",__("Asignar habitación"),this.data.rooms,"room_number",false),depends_on:doc=>doc.status==="Check In"},f("reason",__("Motivo"),"Data",{depends_on:doc=>["Cancelled","No Show"].includes(doc.status),mandatory_depends_on:doc=>["Cancelled","No Show"].includes(doc.status)})],async(v,d)=>{
      if(this.property!==property)throw Error("Property changed");
      if(v.status==="Modify"){d.hide();await this.action_booking_edit(id);return;}
      const values={...v,booking:b.name,modified:b.modified};
      if(v.status==="Check In"){
        const fees=await this.call("preview",{property_name:this.property,action:"check_in",data:JSON.stringify(values)});
        if(+fees.early||+fees.late){await this.dialog(__("Revisar cargos por horario"),[f("fees",__("Cargos"),"HTML",{options:`<p>${e(fees.explanation)}</p><p>${frappe.utils.escape_html(__("Entrada anticipada:"))} ${e(this.amount(fees.early))}</p><p>${frappe.utils.escape_html(__("Salida tardía programada:"))} ${e(this.amount(fees.late))}</p>`})],async(x,c)=>{await this.mutate("check_in",{...values,timing_acceptance:fees.acceptance},key);c.hide();d.hide();},__("Confirmar entrada"));return;}
      }else if(["Cancelled","No Show"].includes(v.status)){
        const fee=await this.call("preview",{property_name:this.property,action:"booking_status",data:JSON.stringify(values)});
        if(+fee.amount){await this.dialog(__("Revisar penalización"),[f("fee",__("Cargo"),"HTML",{options:`<h3>${e(this.amount(fee.amount,fee.currency))}</h3><p>${frappe.utils.escape_html(__("La política configurada generará una factura y aplicará anticipos disponibles."))}</p>`})],async(x,c)=>{await this.mutate("booking_status",{...values,fee_acceptance:fee.acceptance},key);c.hide();d.hide();},__("Confirmar"));return;}
      }
      await this.mutate(v.status==="Check In"?"check_in":"booking_status",values,key);d.hide();
    },__("Confirmar"));
    return this.bind_booking_summary(dialog,property);
  };
  Desk.prototype.action_booking_edit=async function(id){
    const info=await this.call("booking_detail",{name:id}),b=info.booking,key=frappe.utils.get_random(24);
    const wall=value=>moment.tz(value,this.data.system_timezone).tz(this.prop.time_zone).format("YYYY-MM-DD HH:mm:ss");
    return this.dialog(__("Modificar reserva"),[f("starts_at",__("Entrada"),"Datetime",{reqd:1,default:wall(b.starts_at)}),f("ends_at",__("Salida"),"Datetime",{reqd:1,default:wall(b.ends_at)}),{...pick("customer",__("Pagador"),this.data.customers,"customer_name"),default:b.customer},f("rooms",__("Habitaciones"),"Table",{in_place_edit:true,reqd:1,data:b.rooms.map(r=>({category:r.category,room:r.room,people:r.people,extra_beds:r.extra_beds})),fields:[f("category",__("Categoría"),"Link",{options:"HS Category",reqd:1,in_list_view:1,get_query:()=>({filters:{property:this.property}})}),f("room",__("Habitación"),"Link",{options:"HS Room",in_list_view:1,get_query:()=>({filters:{property:this.property}})}),f("people",__("Personas"),"Int",{reqd:1,in_list_view:1})]}),f("reason",__("Motivo"),"Small Text",{reqd:1})],async(v,d)=>{
      const values={...v,booking:id,modified:b.modified},q=await this.call("preview",{property_name:this.property,action:"modify_reservation",data:JSON.stringify(values)});
      await this.dialog(__("Revisar nueva cotización"),[f("price",__("Importe"),"HTML",{options:`<h3>${e(this.amount(q.amount,q.currency))}</h3><ul>${q.lines.map(r=>`<li>${e(r.explanation.join("; "))}</li>`).join("")}</ul>`})],async(x,c)=>{await this.mutate("modify_reservation",{...values,acceptance:q.acceptance},key);c.hide();d.hide();},__("Confirmar modificación"));
    },__("Cotizar"));
  };
  Desk.prototype.action_checkout=async function(id){
    const info=await this.call("stay_detail",{name:id}),q=await this.call("preview",{property_name:this.property,action:"departure",data:JSON.stringify({stay:id})});
    const key=frappe.utils.get_random(24);
    if(q.inspection_required&&!q.inspected){frappe.msgprint(__("La salida requiere inspección de supervisión. Use Inspeccionar salida en la estancia."));return;}
    if(+q.amount){return this.dialog(__("Liquidar tiempo de estancia"),[f("quote",__("Cargo adicional"),"HTML",{options:`<h3>${e(this.amount(q.amount,q.currency))}</h3><p>${e(q.explanation.join("; "))}</p><p>${frappe.utils.escape_html(__("Prepare la cuenta y cobre el saldo antes de registrar salida."))}</p>`}),pick("folio",__("Cuenta"),info.folios,"label")],async(v,d)=>{await this.mutate("prepare_departure",{stay:id,folio:v.folio,acceptance:q.acceptance},key);d.hide();await this.action_detail(id);},__("Preparar liquidación"));}
    return this.dialog(__("Registrar salida"),[f("review",__("Revisión"),"HTML",{options:`<p>${frappe.utils.escape_html(__("Revise consumos, saldo y garantías. La salida generará la tarea de limpieza."))}</p>`}),f("credit_reason",__("Motivo de salida a crédito autorizada"),"Small Text")],async(v,d)=>{await this.mutate("check_out",{...v,stay:id,modified:info.stay.modified},key);d.hide();},__("Confirmar salida"));
  };
  Desk.prototype.action_inspect_departure=async function(id){const key=frappe.utils.get_random(24);return this.dialog(__("Inspeccionar salida"),[f("notes",__("Revisión, minibar y daños"),"Small Text",{reqd:1})],async(v,d)=>{await this.mutate("inspect_departure",{stay:id,...v},key);d.hide();});};
  Desk.prototype.action_portal_convert=async function(id){
    const property=this.property,request=(this.data.portal_requests||[]).find(row=>row.name===id);
    if(!request||request.property!==property){frappe.msgprint(__("Actualice las solicitudes del portal antes de revisar."));return;}
    const key=frappe.utils.get_random(24),category=(this.data.categories||[]).find(row=>row.name===request.category)?.category_name||__("Categoría registrada");
    const rooms=+request.rooms===1?__("1 habitación"):__("{0} habitaciones",[request.rooms]);
    const people=+request.people===1?__("1 persona por habitación"):__("{0} personas por habitación",[request.people]);
    const context=`<h3>${e(request.full_name)}</h3><p>${e(category)} · ${e(rooms)} · ${e(people)}</p><p>${e(__("Entrada"))}: ${e(this.date(request.starts_at))}<br>${e(__("Salida"))}: ${e(this.date(request.ends_at))}<br>${e(this.prop.time_zone)}</p>`;
    const same=()=>{if(this.property!==property)throw Error("Property changed");};
    const deadline=request.status==="Requested"?`${e(__("Sin cupo reservado. Confirmar antes de"))}: ${e(this.date(request.request_until))}`:
      `${e(__("Cupo conservado hasta"))}: ${e(this.date(request.hold_until))}`;
    return this.dialog(__("Revisar solicitud del portal"),[f("portal_summary",__("Solicitud recibida"),"HTML",{options:`${context}<p>${deadline}</p><p>${e(__("Alojamiento consultado"))}: <strong>${e(this.amount(request.amount,request.currency))}</strong></p>`}),pick("guest",__("Huésped registrado"),this.data.guests,"full_name"),pick("customer",__("Cliente pagador"),this.data.customers,"customer_name")],async(v,d)=>{
      same();const data={...v,portal_request:id},q=await this.call("preview",{property_name:property,action:"convert_portal",data:JSON.stringify(data)});same();
      const customer=this.data.customers.find(row=>row.name===v.customer)?.customer_name||__("Cliente registrado");
      await this.dialog(__("Confirmar reserva del portal"),[f("summary",__("Reserva a confirmar"),"HTML",{options:`${context}<p>${e(__("Huésped"))}: ${e(this.guestName(v.guest))}<br>${e(__("Pagador"))}: ${e(customer)}</p><h2>${e(__("Total de alojamiento"))}: ${e(this.amount(q.amount,q.currency))}</h2><p>${e(__("Se confirmará la reserva con habitaciones por asignar. No se registra un cobro ni una entrada."))}</p>`})],async(x,c)=>{same();await this.mutate("convert_portal",{...data,acceptance:q.acceptance},key);c.hide();d.hide();},__("Confirmar reserva"));
    },__("Revisar reserva"));
  };
  Desk.prototype.action_portal_reject=async function(id){
    const property=this.property,request=(this.data.portal_requests||[]).find(row=>row.name===id);
    if(!this.allowed("reserve")||!request||request.property!==property)return;
    const key=frappe.utils.get_random(24);
    return this.dialog(__("Rechazar solicitud del portal"),[f("reason",__("Motivo del rechazo"),"Small Text",{reqd:1}),
      f("notice",__("Efecto"),"HTML",{options:`<p>${e(__("La solicitud dejará de estar pendiente. Si conservaba cupo temporal, se liberará."))}</p>`})],
    async(v,d)=>{if(this.property!==property)throw Error("Property changed");await this.mutate("reject_portal",{portal_request:id,reason:v.reason},key);d.hide();},__("Rechazar solicitud"));
  };
  const cleaning=Desk.prototype.render_housekeeping;
  Desk.prototype.render_housekeeping=function(el){cleaning.call(this,el);if(this.allowed("clean"))el.find(".hs-toolbar").append(this.button("incident",__("Registrar novedad"))+this.button("linen",__("Ropa de cama")));};
  Desk.prototype.action_incident=async function(){const key=frappe.utils.get_random(24);return this.dialog(__("Daño u objeto encontrado"),[pick("room",__("Habitación"),this.data.rooms,"room_number"),f("kind",__("Tipo"),"Select",{reqd:1,options:[{value:"Damage",label:__("Daño")},{value:"Lost Property",label:__("Objeto encontrado")}]}),f("description",__("Descripción"),"Small Text",{reqd:1})],async(v,d)=>{await this.mutate("incident",v,key);d.hide();});};
  Desk.prototype.action_linen=async function(){const key=frappe.utils.get_random(24);return this.dialog(__("Movimiento de ropa de cama"),[pick("room",__("Habitación de referencia"),this.data.rooms,"room_number"),this.item_field(__("Artículo de inventario"),"stock"),f("quantity",__("Cantidad"),"Float",{reqd:1}),f("direction",__("Movimiento"),"Select",{reqd:1,options:[{value:"Send",label:__("Enviar a lavandería")},{value:"Receive",label:__("Recibir de lavandería")},{value:"Loss",label:__("Registrar pérdida")}]}),f("reason",__("Observaciones / motivo"),"Small Text")],async(v,d)=>{await this.mutate("linen",v,key);d.hide();});};
  Desk.prototype.action_report=async function(report){
    const show=async(filters)=>{const rows=await this.call("report",{property_name:this.property,report_name:report,filters:JSON.stringify(filters)}),headers=rows.length?Object.keys(rows[0]):[];
      const value=(k,v)=>e(["status","kind","type","cleaning_status","settlement_direction","purpose","classification","mode"].includes(k)?(this.data.report_values?.[v]||v):v);
      const d=await this.dialog(report,[f("rows",__("Resultado"),"HTML",{options:`<p>${frappe.utils.escape_html(__("Hasta 1 000 filas por consulta."))}</p>${this.table(headers.map(k=>this.data.report_labels?.[k]||k),rows.map(r=>headers.map(k=>value(k,r[k]))))}<div class="hs-dialog-actions"><button class="btn btn-secondary" data-format="xlsx">${frappe.utils.escape_html(__("Exportar XLSX"))}</button><button class="btn btn-secondary" data-format="pdf">${frappe.utils.escape_html(__("Exportar PDF"))}</button></div>`})],async(v,x)=>x.hide(),__("Cerrar"),"extra-large");
      d.$wrapper.on("click","[data-format]",event=>{const format=$(event.currentTarget).data("format"),params=new URLSearchParams({property_name:this.property,report_name:report,filters:JSON.stringify(filters),file_format:format});window.open("/api/method/hospitality_suite.api.export_report?"+params.toString(),"_blank","noopener");});
    };
    const extra=report==="Movimientos de inventario"?[pick("warehouse",__("Almacén"),this.data.warehouses||[],"warehouse_name",false),f("item",__("Artículo"),"Link",{options:"Item"}),f("purpose",__("Uso operativo"),"Select",{options:[{value:"",label:__("Todos")},...["Purchase","Transfer","Cleaning","Waste","Linen Replacement","Maintenance","Laundry","Sale","Adjustment","Stock"].map(v=>({value:v,label:this.data.report_values?.[v]||v}))]})]:[f("status",__("Estado (opcional)")),pick("room",__("Habitación"),this.data.rooms,"room_number",false)];
    return this.dialog(__("Filtros · {0}",[report]),[f("from_date",__("Desde"),"Date"),f("to_date",__("Hasta"),"Date"),...extra],async(values,d)=>{await show(values);d.hide();},__("Consultar"));
  };
  const cashier=Desk.prototype.render_cashier;
  Desk.prototype.render_cashier=function(el){cashier.call(this,el);el.find(".hs-toolbar").append(this.button("withdrawal",__("Retirar / entregar efectivo"))+this.button("guarantee",__("Aplicar garantía"))+this.button("credit",__("Nota de crédito")));};
  Desk.prototype.action_withdrawal=async function(){const key=frappe.utils.get_random(24);return this.dialog(__("Retiro o entrega de efectivo"),[pick("shift",__("Turno abierto"),this.data.shifts.filter(s=>s.status==="Open")),pick("method",__("Medio en efectivo"),this.data.payment_methods.filter(m=>m.is_cash),"mode_of_payment"),f("amount",__("Importe"),"Currency",{reqd:1}),f("reason",__("Motivo y responsable de la entrega"),"Small Text",{reqd:1})],async(v,d)=>{await this.mutate("withdrawal",v,key);d.hide();});};
  Desk.prototype.action_guarantee=async function(){const key=frappe.utils.get_random(24);return this.dialog(__("Aplicar garantía autorizada"),[pick("source_payment",__("Garantía recibida"),this.data.payments.filter(p=>p.kind==="Guarantee"&&p.status==="Posted").map(p=>({...p,label:this.paymentSourceLabel(p)})),"label"),pick("folio",__("Cuenta destino"),this.data.folios,"label"),pick("shift",__("Turno abierto"),this.data.shifts.filter(s=>s.status==="Open")),f("amount",__("Importe a aplicar"),"Currency",{reqd:1}),f("reason",__("Autorización y motivo"),"Small Text",{reqd:1})],async(v,d)=>{await this.mutate("apply_guarantee",v,key);d.hide();});};
  Desk.prototype.action_change_room=async function(id){
    const info=await this.call("stay_detail",{name:id}),key=frappe.utils.get_random(24);
    return this.dialog(__("Cambiar habitación"),[pick("room",__("Habitación de destino"),this.data.rooms.filter(r=>r.name!==info.stay.room),"room_number"),pick("folio",__("Cuenta para el ajuste"),info.folios,"label"),f("mode",__("Modalidad (solo establecimiento mixto)"),"Select",{options:this.prop.mode==="Mixed"?[{value:"",label:__("Conservar modalidad")},"Hotel","Por tiempo"]:[this.prop.mode],default:this.prop.mode}),f("reason",__("Motivo"),"Small Text",{reqd:1})],async(v,d)=>{
      const values={...v,stay:id,modified:info.stay.modified},q=await this.call("preview",{property_name:this.property,action:"change_room",data:JSON.stringify(values)});
      await this.dialog(__("Revisar cambio de habitación"),[f("calculation",__("Efecto tarifario"),"HTML",{options:`<p>${e(q.explanation)}</p><h3>${frappe.utils.escape_html(__("Ajuste:"))} ${e(this.amount(q.difference))}</h3><p>${frappe.utils.escape_html(__("Vigente hasta"))} ${e(q.valid_until)}</p>`})],async(x,c)=>{await this.mutate("change_room",{...values,acceptance:q.acceptance},key);c.hide();d.hide();},"Confirmar cambio");
    },"Cotizar cambio");
  };
  const setup=Desk.prototype.render_setup;
  Desk.prototype.render_setup=function(el){setup.call(this,el);el.find(".hs-shortcuts").append(this.button("billing_party",__("6. Empresas, agencias y crédito"))+this.button("policies",__("7. Horarios y penalizaciones"))+this.button("denominations",__("8. Denominaciones de caja")));};
  Desk.prototype.action_billing_party=async function(){const key=frappe.utils.get_random(24);return this.dialog(__("Empresa, agencia o crédito"),[f("customer",__("Cliente de ERPNext"),"Link",{options:"Customer",reqd:1}),f("kind",__("Tipo"),"Select",{options:["Company","Agency","Individual"],reqd:1}),f("credit_authorized",__("Autorizar crédito"),"Check"),f("credit_limit",__("Límite en moneda del establecimiento"),"Currency"),f("credit_days",__("Plazo de pago (días)"),"Int",{default:30}),f("valid_until",__("Vigente hasta"),"Date"),f("reason",__("Motivo de la autorización"),"Small Text",{reqd:1})],async(v,d)=>{await this.call("save_setup",{property_name:this.property,section:"billing_party",data:JSON.stringify(v),request_key:key});d.hide();await this.load();});};
  Desk.prototype.action_policies=async function(){const config=await this.call("configuration",{property_name:this.property}),key=frappe.utils.get_random(24);const fields=[f("close_time",__("Hora de corte del día operativo"),"Time"),f("check_in_time",__("Hora habitual de entrada"),"Time"),f("check_out_time",__("Hora habitual de salida"),"Time"),f("early_hour_rate",__("Entrada anticipada por hora"),"Currency"),f("late_hour_rate",__("Salida tardía por hora"),"Currency"),f("schedule_grace_minutes",__("Tolerancia de horario (minutos)"),"Int"),f("schedule_rounding_minutes",__("Fracción de horario (minutos)"),"Int"),f("timing_item",__("Artículo para cargos de horario"),"Link",{options:"Item"}),f("checkout_inspection_required",__("Exigir inspección antes de salir"),"Check"),f("checkout_quote_minutes",__("Minutos para completar salida liquidada"),"Int"),f("cancellation_fee_mode",__("Penalización de cancelación"),"Select",{options:["None","Fixed","First Night","Percent"]}),f("cancellation_fee_value",__("Importe fijo o porcentaje de cancelación"),"Currency"),f("no_show_fee_mode",__("Penalización por no presentación"),"Select",{options:["None","Fixed","First Night","Percent"]}),f("no_show_fee_value",__("Importe fijo o porcentaje de no presentación"),"Currency"),f("penalty_item",__("Artículo para penalizaciones"),"Link",{options:"Item"})].map(df=>({...df,default:config[df.fieldname]}));return this.dialog(__("Horarios y penalizaciones"),fields,async(v,d)=>{await this.call("save_setup",{property_name:this.property,section:"property",data:JSON.stringify(v),request_key:key,expected_modified:config.modified});d.hide();await this.load();});};
  Desk.prototype.action_denominations=async function(){const config=await this.call("configuration",{property_name:this.property}),key=frappe.utils.get_random(24),values=JSON.parse(config.cash_denominations||"{}");const rows=Object.entries(values).flatMap(([currency,items])=>items.map(value=>({currency,value})));return this.dialog(__("Denominaciones de caja"),[f("rows",__("Billetes y monedas que utiliza"),"Table",{data:rows,in_place_edit:true,fields:[f("currency",__("Moneda"),"Link",{options:"Currency",in_list_view:1,reqd:1}),f("value",__("Denominación"),"Currency",{in_list_view:1,reqd:1})]})],async(v,d)=>{const data={};for(const row of v.rows||[])(data[row.currency]||=[]).push(row.value);await this.call("save_setup",{property_name:this.property,section:"property",data:JSON.stringify({cash_denominations:JSON.stringify(data)}),request_key:key,expected_modified:config.modified});d.hide();await this.load();});};
  Desk.prototype.action_close_shift=async function(id){
    const shift=this.data.shifts.find(s=>s.name===id),key=frappe.utils.get_random(24),saved=JSON.parse(shift.denominations||"{}").counts||{};
    const currencies=[...new Set([...Object.keys(shift.expected_by_currency),...Object.keys(saved)])];
    const fields=currencies.map((currency,index)=>f("currency_"+index,__("Arqueo {0} · esperado {1}",[currency,shift.expected_by_currency[currency]||0]),"Table",{in_place_edit:true,data:saved[currency]||(this.data.denominations[currency]||[1]).map(value=>({value,count:0})),fields:[f("value",__("Denominación"),"Currency",{in_list_view:1,reqd:1}),f("count",__("Cantidad"),"Int",{in_list_view:1,reqd:1,default:0})]}));
    return this.dialog(__("Arqueo por denominaciones"),[...fields,f("reason",__("Motivo de diferencias"),"Small Text"),f("approve",__("Aprobar diferencias (supervisión)"),"Check")],async(v,d)=>{const denominations={};currencies.forEach((currency,index)=>{denominations[currency]=v["currency_"+index]||[];});await this.mutate("close_shift",{shift:id,modified:shift.modified,denominations,reason:v.reason,approve:v.approve},key);d.hide();},__("Cerrar turno"));
  };
  Desk.prototype.action_adjustment=async function(id){const info=this.current?.stay.name===id?this.current:await this.call("stay_detail",{name:id}),key=frappe.utils.get_random(24);return this.dialog(__("Descuento, cortesía o recargo"),[pick("charge",__("Cargo de origen"),info.charges.filter(r=>["Pending","Scheduled"].includes(r.status)&&+r.amount>0),"description"),f("adjustment_type",__("Tipo"),"Select",{reqd:1,options:[{value:"Discount",label:__("Descuento")},{value:"Courtesy",label:__("Cortesía del saldo del cargo")},{value:"Surcharge",label:__("Recargo")}]}),f("amount",__("Importe (cortesía usa el saldo completo)"),"Currency"),f("reason",__("Motivo y autorización"),"Small Text",{reqd:1})],async(v,d)=>{await this.mutate("adjustment",v,key);d.hide();});};
})();
