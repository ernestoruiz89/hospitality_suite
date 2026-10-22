const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function fixture(actions=['clean','inspect','maintain']){
  const suite={},escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const context={window:{hospitality_suite:suite},hospitality_suite:suite,__:(v,args)=>args?v.replace(/\{(\d+)\}/g,(m,n)=>args[n]):v,
    frappe:{utils:{escape_html:escape,get_random:()=> 'stable-key'},session:{user:'cleaner'},msgprint(){}},localStorage:{getItem:()=>null},setTimeout,clearTimeout};
  for(const name of ['hospitality.js','hospitality_extras.js','hospitality_workflows.js','hospitality_housekeeping.js','hospitality_forms.js'])
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js',name),'utf8'),context);
  const desk=Object.create(suite.Desk.prototype);desk.allowed=permission=>actions.includes(permission);desk.roomName=()=> 'H101';desk.date=value=>value;
  desk.prop={inspection_required:1};desk.data={cleaning:[],rooms:[],equipment:[],incidents:[]};
  let form,mutation;
  desk.dialog=async(title,fields,submit,label)=>{form={title,fields,submit,label};return{fields_dict:{equipment:{df:{}}},get_value(){},set_value(){}};};
  desk.mutate=async(action,values,key)=>{mutation={action,values,key};};
  return {desk,form:()=>form,mutation:()=>mutation};
}
test('cleaning keeps instructions and uses explicit inspection versus release actions',async()=>{
  const f=fixture(),task={name:'task',room:'room',status:'In Progress',modified:'version',notes:'Conservar indicaciones'};f.desk.data.cleaning=[task];
  await f.desk.action_cleaning('task');assert.equal(f.form().label,'Solicitar inspección');assert.equal(f.form().fields.find(row=>row.fieldname==='notes').default,task.notes);
  await f.form().submit({bath:1,bed:1,minibar:1,surfaces:1,notes:task.notes},{hide(){}});
  assert.equal(f.mutation().values.status,'Inspection');assert.equal(f.mutation().values.modified,'version');
  task.status='Inspection';await f.desk.action_cleaning('task');assert.equal(f.form().label,'Inspeccionar y liberar');
  task.status='In Progress';f.desk.prop.inspection_required=0;await f.desk.action_cleaning('task');assert.equal(f.form().label,'Finalizar limpieza');
});
test('requesting correction has a required reason and submits the current task version',async()=>{
  const f=fixture();f.desk.data.cleaning=[{name:'task',room:'room',status:'Inspection',modified:'current'}];
  await f.desk.action_rework_cleaning('task');assert.equal(f.form().fields[0].reqd,1);assert.equal(f.form().label,'Devolver a limpieza');
  await f.form().submit({notes:'Revisar baño'},{hide(){}});assert.equal(f.mutation().values.status,'In Progress');assert.equal(f.mutation().values.modified,'current');
});
test('cards prioritize urgent work, escape notes, show type and hide another cleaner actions',()=>{
  const f=fixture(['clean']);f.desk.data.cleaning=[{name:'normal',kind:'Stay',priority:'Normal',status:'Pending',notes:'<script>bad</script>',room:'room'},
    {name:'urgent',kind:'Deep',priority:'Urgent',status:'In Progress',room:'room',assigned_to:'someone-else',assigned_label:'Otra persona'}];
  let cards='';const target={html(){return this;},append(){return this;},find(selector){return{append(){},html(value){if(selector==='.hs-task-grid')cards=value;}};}};
  f.desk.render_housekeeping(target);assert.ok(cards.indexOf('Profunda')<cards.indexOf('Durante estancia'));assert.match(cards,/Asignada a otra persona/);
  assert.match(cards,/&lt;script&gt;/);assert.doesNotMatch(cards,/<script>/);
  assert.doesNotMatch(cards,/data-act="cleaning" data-id="urgent"/);
  assert.match(cards,/data-act="print_cleaning" data-id="urgent"/,'the visible task can be printed without granting its update action');
});
test('open ended maintenance hides deadline, clears a stale date and fits two task tabs',async()=>{
  const f=fixture();f.desk.data.maintenance=[];await f.desk.action_maintenance('');
  const form=f.form(),end=form.fields.find(row=>row.fieldname==='ends_at');
  assert.equal(end.depends_on({until_reopened:1}),false);assert.equal(end.mandatory_depends_on({until_reopened:0}),true);
  const layout=f.desk.form_layout(form.fields);assert.equal(layout.kind,'maintenance');assert.equal(layout.fields.filter(row=>row.fieldtype==='Tab Break').length,2);
  await form.submit({room:'room',starts_at:'2026-10-20 14:00:00',until_reopened:1,ends_at:'old deadline'},{hide(){}});
  assert.equal(f.mutation().values.ends_at,null);assert.equal(f.mutation().values.until_reopened,1);
});

test('reception identifies an indefinite block and does not offer its room reservation',()=>{
  const f=fixture(['reserve']);let html='';
  f.desk.query='';f.desk.root={find:()=>({val:()=>''})};f.desk.filterRooms=()=>{};f.desk.roomTiming=()=>'';
  Object.assign(f.desk.data,{rooms:[{name:'blocked-room',room_number:'H104',cleaning_status:'Clean'}],occupied:[],categories:[],
    blocks:[{room:'blocked-room',starts_at:'2026-10-20 10:00:00',ends_at:null}],server_time:'2026-10-20 15:00:00'});
  const chain={prepend(){return this;},each(){return this;},val(){return this;},on(){return this;}};
  f.desk.render_reception({html(value){html=value;},find(){return chain;}});
  assert.match(html,/Hasta reapertura autorizada/);assert.match(html,/Reapertura pendiente/);
  assert.doesNotMatch(html,/data-act="reserve" data-id="blocked-room"/);
});

test('maintenance shows the catalogue part name safely while retaining its original stock reference',()=>{
  const f=fixture(['maintain']);let html='';
  const part={item:'INTERNAL-PART-KEY',quantity:2,status:'Issued',stock_entry:'original-entry'};
  Object.assign(f.desk.data,{inventory_currency:'NIO',items:[{name:part.item,item_name:'Válvula anterior',display_name:'Válvula <principal>'}],
    maintenance:[{name:'order',room:'room',title:'Revisar grifería',status:'In Progress',parts:[part],cost:40}]});
  f.desk.amount=()=> 'C$ 40.00';
  const chain={first(){return this;},find(){return this;},each(){return this;}};
  f.desk.render_maintenance({html(value){html=value;},find(){return chain;}});
  assert.match(html,/Válvula &lt;principal&gt; × 2/);assert.doesNotMatch(html,/INTERNAL-PART-KEY|<principal>/);
  assert.equal(part.item,'INTERNAL-PART-KEY');assert.equal(part.stock_entry,'original-entry');
});

test('incident evidence remains accessible by its private link before and after resolution',()=>{
  const f=fixture(['maintain','incident']);let html='';
  Object.assign(f.desk.data,{maintenance:[],incidents:[
    {name:'incident-open',room:'room',kind:'Damage',description:'Novedad abierta',status:'Open',evidence:'/private/files/abierta.txt'},
    {name:'incident-resolved',room:'room',kind:'Damage',description:'Novedad revisada',status:'Resolved',resolution:'Revisado <correctamente>',evidence:'/private/files/evidencia"final.txt'}]});
  const chain={first(){return this;},find(){return this;},each(){return this;}};
  f.desk.render_maintenance({html(value){html=value;},find(){return chain;}});
  assert.equal((html.match(/>Ver evidencia<\/a>/g)||[]).length,2);
  assert.match(html,/href="\/private\/files\/abierta.txt"/);
  assert.match(html,/href="\/private\/files\/evidencia&quot;final.txt"/);
  assert.match(html,/target="_blank" rel="noopener"/);
  assert.match(html,/Revisado &lt;correctamente&gt;/);
  assert.match(html,/data-act="incident_evidence" data-id="incident-open"/);
  assert.doesNotMatch(html,/data-act="incident_evidence" data-id="incident-resolved"/);
});
