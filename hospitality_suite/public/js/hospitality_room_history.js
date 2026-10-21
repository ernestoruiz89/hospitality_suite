/* Room history stays inside Pages, with bounded results and immutable query context. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  const kinds={operation:__("Operación"),change:__("Cambio de datos"),period:__("Período")};
  Desk.prototype.room_history_allowed=function(){return this.allowed("stay")||this.allowed("finance")||this.allowed("report");};
  const reception=Desk.prototype.render_reception;
  Desk.prototype.render_reception=function(el){
    reception.call(this,el);if(!this.room_history_allowed())return;
    el.find('.hs-room').each((_,node)=>{
      const room=this.data.rooms.find(row=>row.name===node.dataset.room);if(!room)return;
      const button=this.button('room_history',__('Historial'),room.name).replace('<button ',`<button aria-label="${e(__("Ver historial de la habitación {0}",[room.room_number]))}" `);
      $(node).find('.hs-room-actions').append(`<div class="hs-room-history">${button}</div>`);
    });
  };
  Desk.prototype.room_history_rows=function(data){
    if(!data.rows.length)return `<div class="hs-empty"><h3>${e(__("No hay movimientos para esta habitación en estas fechas."))}</h3><p>${e(__("Puede ampliar el rango o elegir otra vista."))}</p></div>`;
    return `<div class="hs-history-list">${data.rows.map(row=>{
      const period=row.kind==='period',when=period?`${this.date(row.starts_at)} → ${row.ends_at?this.date(row.ends_at):__('Sin fecha final registrada')}`:this.date(row.occurred_at);
      const fields=row.fields?.length?`<details><summary>${e(__("Ver valores registrados ({0})",[row.fields.length]))}</summary>${this.table([__('Dato'),__('Antes'),__('Después')],row.fields.map(field=>[e(field.label),e(field.before),e(field.after)]))}</details>`:'';
      const related=row.relation==='related'?`<p class="hs-note">${e(__("Documento relacionado; la habitación de ese momento no pudo reconstruirse de forma única."))}</p>`:'';
      return `<article class="hs-history-row"><div><span class="hs-badge">${e(kinds[row.kind]||__('Registro'))}</span><time>${e(when)}</time></div><h4>${e(row.title)}</h4>${row.actor?`<small>${e(__('Registrado por'))}: ${e(row.actor)}</small>`:''}${row.note?`<p class="hs-history-note">${e(row.note)}</p>`:''}${related}${fields}</article>`;
    }).join('')}</div>`;
  };
  Desk.prototype.action_room_history=async function(room){
    if(!this.room_history_allowed())return;
    const property=this.property,zone=this.prop.time_zone,label=this.roomName(room),day=(this.data.property_now||this.data.server_time).slice(0,10);
    const state={property,room,zone,sequence:0,shown:true,loading:false,accepted:null};
    const field=(fieldname,label,extra={})=>({fieldname,label:__(label),fieldtype:'Data',...extra});
    const dialog=await this.dialog(__("Historial · habitación {0}",[label]),[
      field('starts_at',__('Desde ({0})',[zone]),{reqd:1,_hsDateTime:true,default:moment(day).subtract(7,'days').format('YYYY-MM-DDT00:00:00')}),
      {fieldname:'_history_column',fieldtype:'Column Break'},
      field('ends_at',__('Hasta (sin incluir)'),{reqd:1,_hsDateTime:true,default:moment(day).add(1,'days').format('YYYY-MM-DDT00:00:00')}),
      {fieldname:'_history_options',fieldtype:'Section Break'},
      field('view',__('Qué desea ver'),{fieldtype:'Select',reqd:1,_hsDataOptions:true,default:'activity',options:[
        {value:'activity',label:__('Actividad')},{value:'changes',label:__('Cambios de datos')},{value:'periods',label:__('Estancias y bloqueos')},{value:'all',label:__('Todo el historial')}]}),
      {fieldname:'_history_result',fieldtype:'HTML',options:`<p>${e(__("Consulte períodos que cruzan estas fechas y cambios registrados dentro del rango. Las reservas sin habitación asignada se consultan en Reservas."))}</p>`}
    ],async(values,d)=>this.load_room_history(d,state,values,0),__('Consultar historial'),'large');
    dialog.$wrapper.addClass('hs-room-history-dialog');
    dialog.$wrapper.on('input.hsRoomHistory change.hsRoomHistory','input,select',()=>{
      state.sequence++;state.accepted=null;
      dialog.fields_dict._history_result.$wrapper.html(`<p role="status">${e(__("Fechas o vista cambiadas. Pulse Consultar historial para actualizar."))}</p>`);
    });
    dialog.$wrapper.on('click.hsRoomHistory','[data-history-offset]',event=>{
      if(!state.accepted||state.loading)return;
      const offset=Number(event.currentTarget.dataset.historyOffset);if(!Number.isInteger(offset)||offset<0)return;
      return this.load_room_history(dialog,state,state.accepted,offset);
    });
    dialog.$wrapper.one('hide.bs.modal.hsRoomHistory',()=>{state.shown=false;state.sequence++;state.accepted=null;});
    return dialog;
  };
  Desk.prototype.load_room_history=async function(dialog,state,values,offset=0){
    if(!state.shown||state.loading)return;
    const target=dialog.fields_dict._history_result.$wrapper;
    if(this.property!==state.property){target.html(`<p role="alert">${e(__("El establecimiento cambió. Cierre esta ventana y vuelva a abrir el historial."))}</p>`);return;}
    const {starts_at,ends_at,view}=values,query={property_name:state.property,room:state.room,starts_at,ends_at,view,offset,page_length:25},sequence=++state.sequence;
    state.accepted=null;
    const start=Date.parse(starts_at),end=Date.parse(ends_at);
    if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start){
      target.html(`<p role="alert">${e(__("Indique fechas válidas. La fecha final debe ser posterior a la inicial."))}</p>`);return;
    }
    const current=()=>state.shown&&state.sequence===sequence&&this.property===state.property;
    state.loading=true;
    target.attr({'aria-busy':'true',role:'status','aria-live':'polite'}).html(`<p>${e(__("Consultando historial…"))}</p>`);
    try{
      const data=await this.call('room_history',query);if(!current())return;
      if(data?.property!==state.property||data?.room!==state.room||data?.view!==view||data?.time_zone!==state.zone||!Array.isArray(data.rows)||data.offset!==offset)throw Error('History context mismatch');
      state.accepted={starts_at,ends_at,view};
      const from=data.total?data.offset+1:0,to=Math.min(data.offset+data.rows.length,data.total);
      const pager=`<div class="hs-history-pagination">${data.offset?`<button type="button" class="btn btn-secondary" data-history-offset="${Math.max(0,data.offset-data.page_length)}">${e(__('Anterior'))}</button>`:''}<span>${e(__("Mostrando {0}–{1} de {2} registros",[from,to,data.total]))}</span>${data.has_more?`<button type="button" class="btn btn-secondary" data-history-offset="${data.offset+data.page_length}">${e(__('Siguiente'))}</button>`:''}</div>`;
      target.html(`<p>${e(this.date(data.starts_at))} → ${e(this.date(data.ends_at))} · ${e(data.time_zone)}</p>${this.room_history_rows(data)}${pager}`);
    }catch{if(current())target.html(`<p role="alert">${e(__("No se pudo consultar el historial. Revise las fechas y pulse Consultar historial para reintentar."))}</p>`);}
    finally{state.loading=false;target.attr('aria-busy','false');}
  };
})();
