/* Operational instructions and explicit inspection actions, without guest data. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const e=value=>frappe.utils.escape_html(String(value??""));
  const field=(fieldname,label,fieldtype="Small Text",extra={})=>({fieldname,label:__(label),fieldtype,...extra});
  const kinds={Departure:__("De salida"),Stay:__("Durante estancia"),Deep:__("Profunda")};
  const render=Desk.prototype.render_housekeeping;
  Desk.prototype.render_housekeeping=function(el){
    render.call(this,el);
    const priority={Urgent:0,High:1,Normal:2};
    const tasks=this.data.cleaning.filter(row=>row.status!=="Completed").sort((a,b)=>(priority[a.priority]??2)-(priority[b.priority]??2));
    el.find('.hs-task-grid').html(tasks.map(task=>{
      const owned=!task.assigned_to||task.assigned_to===frappe.session?.user||this.allowed('inspect');
      const label=task.status==='Pending'?__('Iniciar limpieza'):task.status==='Inspection'?__('Inspeccionar y liberar'):this.prop.inspection_required?__('Solicitar inspección'):__('Finalizar limpieza');
      const action=owned?this.button('cleaning',label,task.name,'primary'):`<p class="hs-note">${e(__('Asignada a otra persona'))}</p>`;
      const rework=task.status==='Inspection'&&this.allowed('inspect')?this.button('rework_cleaning',__('Solicitar corrección'),task.name):'';
      return `<article class="hs-task"><div class="hs-task-top"><strong>${e(__('Habitación'))} ${e(this.roomName(task.room))}</strong>${this.badge(task.priority)}</div><p>${e(__(kinds[task.kind]||task.kind))} · ${this.badge(task.status)}</p><p>${e(task.assigned_label||task.assigned_to||__('Sin responsable'))}</p>${task.started_at?`<p class="hs-note">${e(__('Inicio'))}: ${e(this.date(task.started_at))}</p>`:''}<p>${e(task.notes||__('Limpieza y revisión de habitación'))}</p><div class="hs-dialog-actions">${action}${rework}</div></article>`;
    }).join('')||this.empty(__('Las habitaciones están al día')));
  };
  Desk.prototype.action_cleaning=async function(id){
    const task=this.data.cleaning.find(row=>row.name===id),key=frappe.utils.get_random(24);
    const target=task.status==='Pending'?'In Progress':task.status==='Inspection'?'Completed':this.prop.inspection_required?'Inspection':'Completed';
    const action=target==='In Progress'?__('Iniciar limpieza'):target==='Inspection'?__('Solicitar inspección'):task.status==='Inspection'?__('Inspeccionar y liberar'):__('Finalizar limpieza');
    const checklist=target==='In Progress'?[]:[field('bath',__('Baño revisado'),'Check',{reqd:1}),field('bed',__('Cama y ropa revisadas'),'Check',{reqd:1}),field('minibar',__('Minibar revisado'),'Check',{reqd:1}),field('surfaces',__('Superficies y equipo revisados'),'Check',{reqd:1})];
    return this.dialog(`${action} · ${__('Habitación')} ${this.roomName(task.room)}`,[...checklist,field('notes',__('Observaciones'),'Small Text',{default:task.notes||''})],async(values,dialog)=>{
      await this.mutate('cleaning',{task:id,modified:task.modified,status:target,notes:values.notes,checklist:{baño:!!values.bath,cama:!!values.bed,minibar:!!values.minibar,superficies:!!values.surfaces}},key);dialog.hide();
    },action);
  };
  Desk.prototype.action_rework_cleaning=function(id){
    const task=this.data.cleaning.find(row=>row.name===id),key=frappe.utils.get_random(24);
    return this.dialog(`${__('Solicitar corrección')} · ${__('Habitación')} ${this.roomName(task.room)}`,[field('notes',__('Qué debe corregirse'),'Small Text',{reqd:1})],async(values,dialog)=>{
      await this.mutate('cleaning',{task:id,modified:task.modified,status:'In Progress',notes:values.notes},key);dialog.hide();
    },__('Devolver a limpieza'));
  };
})();
