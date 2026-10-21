const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
function fixture(){
  const dialogs=[],commands=[],accounts=[],reports=[];
  const groups=[{type:'Llegadas pendientes',documents:['opaque-hash'],hint:'Revise <la reserva>',page:'hospitality-reservations',items:Array.from({length:26},(_,n)=>({name:`opaque-${n}`,label:`Habitación H${n+1}`,detail:'Fecha <aceptada>',stay:`stay-${n}`}))}];
  const period={currency:'NIO',close_review:{date_label:'19/10/2026',starts_at:'19/10/2026 06:00',ends_at:'20/10/2026 06:00',close_time:'06:00:00',time_zone:'America/Managua'},time_zone:'America/Managua'};
  class Desk{
    constructor(){this.property='hotel';this.prop={time_zone:'Europe/Madrid'};this.permissions=new Set(['finance','stay','report','approve']);this.data={close_financial_groups:[],pages:[{route:'hospitality-reservations'}],closes:[{name:'saved',summary:JSON.stringify(period),blockers:JSON.stringify(groups)}]};}
    allowed(name){return this.permissions.has(name)}
    table(headers,rows){return `<table>${rows.map(row=>row.join('|')).join('\n')}</table>`}empty(s){return s}
    async mutate(action,data,key){commands.push({action,data,key});return {period,blockers:groups,review_acceptance:'digest'}}
    async action_detail(id){accounts.push(id)}async action_report(name){reports.push(name)}
    async dialog(title,fields,submit){const handlers={},button={prop(key,value){this[key]=value;return this}},d={title,fields,submit,hidden:false,handlers,$wrapper:{on(event,selector,handler){handlers[selector]=handler}},get_primary_btn(){return button},hide(){this.hidden=true},fields_dict:Object.fromEntries(fields.map(df=>[df.fieldname,{$wrapper:{html(value){df.options=value}}}]))};dialogs.push(d);return d}
  }
  const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_close.js'),'utf8'),{window:{hospitality_suite:{Desk}},frappe:{utils:{escape_html:escape,get_random:()=> 'key'},msgprint(){}},__:s=>s});
  return {desk:new Desk(),dialogs,commands,accounts,reports,groups,period};
}
test('close puts readable operational dates and pending work before indicators without rendering technical references',()=>{
  const f=fixture(),html=f.desk.close_summary_html(f.period,f.groups,{live:true});assert.match(html,/19\/10\/2026/);assert.match(html,/06:00:00/);assert.match(html,/America\/Managua/);assert.doesNotMatch(html,/Europe\/Madrid|opaque-hash/);assert.match(html,/Revise &lt;la reserva&gt;/);assert.ok(html.indexOf('Pendientes conservados')<html.indexOf('Habitaciones-noche'));assert.match(html,/Actualizar revisión/);
});
test('saved pending rows paginate in groups of 25 and open the captured account only in the original property',async()=>{
  const f=fixture(),d=await f.desk.show_close_pending(f.groups,0);assert.match(d.fields[0].options,/Habitación H25/);assert.doesNotMatch(d.fields[0].options,/Habitación H26/);assert.match(d.fields[0].options,/Fecha &lt;aceptada&gt;/);assert.doesNotMatch(d.fields[0].options,/opaque-/);assert.match(d.fields[0].options,/href="\/app\/hospitality-reservations"/);
  d.handlers['[data-hs-pending-page]']({currentTarget:{dataset:{hsPendingPage:'next'}}});assert.match(d.fields[0].options,/Habitación H26/);assert.doesNotMatch(d.fields[0].options,/Habitación H25/);
  await d.handlers['[data-hs-pending-account]']({currentTarget:{dataset:{hsPendingAccount:'25'}}});assert.deepEqual(f.accounts,['stay-25']);f.desk.property='other';await d.handlers['[data-hs-pending-account]']({currentTarget:{dataset:{hsPendingAccount:'0'}}});assert.equal(f.accounts.length,1);
});
test('legacy snapshots explain missing descriptions and do not echo hashes or fetch current documents',async()=>{
  const f=fixture();f.desk.call=()=>{throw Error('Historical values must not be fetched')};const d=await f.desk.show_close_pending([{type:'Registro anterior',documents:['raw-secret-reference']}],0);assert.match(d.fields[0].options,/registro anterior conserva las referencias/);assert.doesNotMatch(d.fields[0].options,/raw-secret-reference|Abrir cuenta/);assert.equal(f.commands.length,0);
});
test('read-only history hides account actions and unapproved routes while keeping reconciliation a read action',async()=>{
  const f=fixture();f.desk.permissions=new Set(['report']);f.groups[0].page='javascript:alert(1)';const d=await f.desk.show_close_pending(f.groups,0);assert.doesNotMatch(d.fields[0].options,/Abrir cuenta|javascript:/);
  const reconciliation=await f.desk.show_close_pending([{type:'Diferencias entre PMS y ERPNext',documents:['ref'],items:[{label:'Turno cerrado',detail:'Diferencia -100 NIO'}]}],0);await reconciliation.handlers['[data-hs-pending-reconcile]']();assert.deepEqual(f.reports,['Conciliación']);assert.equal(f.commands.length,0);
});
test('only the live review refreshes and each refresh remains bound to its property; saved summaries do not mutate',async()=>{
  const f=fixture(),live=await f.desk.action_daily_close();assert.equal(live.get_primary_btn().disabled,true);assert.equal(f.commands.length,1);f.desk.action_daily_close=async()=>{f.commands.push({refresh:true})};await live.handlers['[data-hs-close-refresh]']();assert.equal(live.hidden,true);assert.equal(f.commands.length,2);f.desk.property='other';await live.handlers['[data-hs-close-refresh]']();assert.equal(f.commands.length,2);
  const saved=await f.desk.action_view_close('saved');assert.equal(saved.handlers['[data-hs-close-refresh]'],undefined);assert.doesNotMatch(saved.fields[0].options,/data-hs-close-refresh/);
});
