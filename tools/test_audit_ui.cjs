const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
function fixture(){
  const dialogs=[],calls=[];
  class Desk{
    constructor(){this.property='hotel';this.data={};this.prop={time_zone:'America/Managua'};this.record={action:'Tarifa modificada',actor:'Supervisión',document_type:'Tarifa',document:'Precio de temporada',reason:'<script>motivo</script>',occurred_at:'20/10/2026 12:00',business_date:'2026-10-19',historical_values_available:true,values_document:'Tarifa · TAR-00001',values:[{field:'amount',label:'Importe',before:'1,500.00 NIO',after:'1,900.00 NIO',changed:true},{field:'category',label:'Categoría',before:'Estándar',after:'Estándar',changed:false}]};}
    async call(method,args){calls.push({method,args});return this.record;}
    table(headers,rows){return `<table><thead>${headers.join('|')}</thead><tbody>${rows.map(row=>row.join('|')).join('\n')}</tbody></table>`;}
    empty(text){return text;}
    async dialog(title,fields,submit){const handlers={};const dialog={title,fields,submit,handlers,hide(){},$wrapper:{on(event,selector,handler){handlers[selector]=handler;}},set_df_property(name,key,value){fields.find(row=>row.fieldname===name)[key]=value;}};dialogs.push(dialog);return dialog;}
  }
  const context={window:{hospitality_suite:{Desk}},frappe:{session:{user:'auditor'},msgprint(){},user:{has_role:()=>false},utils:{escape_html:escape}},__:(text,args)=>args?text.replace('{0}',args[0]):text};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_audit.js'),'utf8'),context);
  return {desk:new Desk(),dialogs,calls,context};
}
test('audit detail separates operation and values, escapes text and expands unchanged fields',async()=>{
  const {desk,calls}=fixture(),dialog=await desk.action_view_audit('event');
  assert.equal(calls[0].method,'audit_detail');assert.equal(calls[0].args.property_name,'hotel');
  assert.equal(dialog.fields.filter(row=>row.fieldtype==='Tab Break').length,2);
  assert.match(dialog.fields.find(row=>row.fieldname==='operation').options,/&lt;script&gt;/);
  const values=dialog.fields.find(row=>row.fieldname==='values').options;
  assert.match(values,/Antes\|Después/);assert.match(values,/1,900.00 NIO/);assert.match(values,/<details><summary>Datos que se conservaron/);
  assert.doesNotMatch(values,/<script>/);
});
test('legacy audit has a clear missing-data explanation and never renders arbitrary payload',async()=>{
  const {desk}=fixture();desk.record.values=[];desk.record.historical_values_available=false;desk.record.details={secret:'NEVER-ECHO'};
  const dialog=await desk.action_view_audit('legacy'),html=dialog.fields.map(row=>row.options||'').join('');
  assert.match(html,/no conserva el desglose/);assert.doesNotMatch(html,/NEVER-ECHO|undefined|\[object Object\]/);
});
test('a response from a property that is no longer selected does not open a dialog',async()=>{
  const {desk,dialogs}=fixture();let resolve;desk.call=()=>new Promise(done=>resolve=done);
  const pending=desk.action_view_audit('event');desk.property='other';resolve(desk.record);await pending;assert.equal(dialogs.length,0);
});
test('review pages contain at most 25 saved records and detail buttons open the matching event',async()=>{
  const {desk}=fixture(),rows=Array.from({length:26},(_,index)=>({name:'event-'+index,action:'Tarifa modificada',actor:'Supervisión',document:'Temporada '+index,reason:'<img>',occurred_at:'20/10/2026'}));
  const dialog=await desk.show_audit_review({business_date:'2026-10-19',rows});
  assert.equal((dialog.fields[0].options.match(/data-hs-audit=/g)||[]).length,25);assert.match(dialog.fields[0].options,/&lt;img&gt;/);
  dialog.handlers['[data-audit-page]']({currentTarget:{dataset:{auditPage:'next'}}});
  assert.equal((dialog.fields[0].options.match(/data-hs-audit=/g)||[]).length,1);assert.match(dialog.fields[0].options,/event-25/);
  let selected;desk.action_view_audit=name=>selected=name;dialog.handlers['[data-hs-audit]']({currentTarget:{dataset:{hsAudit:'event-25'}}});assert.equal(selected,'event-25');
});
test('empty review remains readable without generating a mutation',async()=>{
  const {desk,calls}=fixture(),dialog=await desk.show_audit_review({business_date:'2026-10-19',rows:[]});
  assert.match(dialog.fields[0].options,/Sin registros excepcionales/);assert.equal(calls.length,0);
});
test('the audit report exposes a readable detail action for the exact event',async()=>{
  const {desk,context}=fixture();
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_reporting.js'),'utf8'),context);
  desk.call=async()=>({total:1,offset:0,page_length:50,has_more:false,columns:['action'],rows:[{name:'event-exact',action:'Rate changed',_display:{action:'Tarifa modificada'}}]});
  const dialog=await desk.show_paged('Auditoría','report_page',{},'Auditoría');
  assert.match(dialog.fields[0].options,/Tarifa modificada/);assert.match(dialog.fields[0].options,/data-hs-audit="event-exact"/);
  let selected;desk.action_view_audit=name=>selected=name;dialog.handlers['[data-hs-audit]']({currentTarget:{dataset:{hsAudit:'event-exact'}}});assert.equal(selected,'event-exact');
});
test('saved close review opens its frozen event list without reading current events',async()=>{
  const {desk,context}=fixture();
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_close.js'),'utf8'),context);
  const review={business_date:'2026-10-19',rows:[{name:'frozen',category:'Cambios manuales',action:'Tarifa modificada'}]};
  desk.data.closes=[{name:'close',business_date:'2026-10-19',summary:JSON.stringify({audit_review:review}),blockers:'[]'}];
  desk.call=async()=>{throw Error('Do not re-sum saved history');};desk.show_audit_review=async value=>assert.equal(value.rows[0].name,'frozen');
  const dialog=await desk.action_view_close('close');assert.match(dialog.fields[0].options,/Registros para revisar/);
  await dialog.handlers['[data-hs-audit-review]']();
});
test('each close execution opens its own captured summary instead of the current close document',async()=>{
  const {desk}=fixture();desk.record.close_snapshot={business_date:'2026-10-19',marker:'first-execution'};desk.record.close_blockers=[];
  let opened;desk.show_close_snapshot=async period=>opened=period.marker;
  const dialog=await desk.action_view_audit('old-close-event');
  assert.match(dialog.fields.find(row=>row.fieldname==='operation').options,/Ver resumen de esta ejecución/);
  await dialog.handlers['[data-hs-audit-close]']();assert.equal(opened,'first-execution');
});
test('a read-only report user does not start preparation or submit a close mutation',async()=>{
  const {desk,context,dialogs}=fixture();
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_close.js'),'utf8'),context);
  desk.allowed=()=>false;desk.mutate=async()=>{throw Error('Read-only user must not mutate a close');};
  await desk.action_daily_close();assert.equal(dialogs.length,0);
});
test('audit tabs supply the native Frappe parent context without duplicate ids between dialogs',async()=>{
  const {desk}=fixture(),first=await desk.action_view_audit('first'),second=await desk.action_view_audit('second');
  const a=first.fields.filter(row=>row.fieldtype==='Tab Break'),b=second.fields.filter(row=>row.fieldtype==='Tab Break');
  assert.equal(first.fields.find(row=>row.hidden==false),a[0]);assert.equal(second.fields.find(row=>row.hidden==false),b[0]);
  assert.ok(a[0].parent);assert.equal(a[0].parent,a[1].parent);assert.equal(b[0].parent,b[1].parent);assert.notEqual(a[0].parent,b[0].parent);
});
