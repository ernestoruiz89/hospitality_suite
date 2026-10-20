const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const file=name=>fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/',name),'utf8');
function fixture(){
  let key=0;
  const context={window:{hospitality_suite:{}},__:(value,args)=>args?value.replace(/\{(\d+)\}/g,(_,i)=>args[i]):value,frappe:{utils:{escape_html:String,get_random:()=>`key-${++key}`},show_alert(){}},moment:()=>({add(){return this;},format(){return '2026-10-24 14:00:00';}})};
  context.hospitality_suite=context.window.hospitality_suite;
  context.$=()=>({text(){return this;},on(){return this;}});
  vm.runInNewContext(file('hospitality.js'),context);vm.runInNewContext(file('hospitality_drafts.js'),context);
  const suite=context.window.hospitality_suite,desk=Object.create(suite.Desk.prototype);
  Object.assign(desk,{property:'hotel',prop:{mode:'Hotel',time_zone:'America/Managua'},data:{server_time:'2026-10-23 14:00:00',rooms:[],guests:[],customers:[],bookings:[]}});
  return {context,suite,desk};
}
const plain=value=>JSON.parse(JSON.stringify(value));
test('a lost draft response retries exactly once with its original payload before saving later edits',async()=>{
  const {suite}=fixture(),sent=[];let lost=true;
  const session=new suite.DraftSession('hotel',async(data,key,property)=>{
    sent.push({data:plain(data),key,property});if(lost){lost=false;throw {status:0};}
    return {booking:'same-draft',modified:`version-${sent.length}`};
  });
  await assert.rejects(session.save({instructions:'Antes',rooms:[{people:0,__temp:'drop'}],amount:999}));
  await session.save({instructions:'Después',rooms:[]});
  assert.equal(sent.length,3);assert.deepEqual(sent[0],sent[1]);
  assert.equal(sent[2].data.booking,'same-draft');assert.equal(sent[2].data.modified,'version-2');
  assert.equal(sent[2].data.values.instructions,'Después');assert.notEqual(sent[2].key,sent[1].key);
  assert.equal(sent[0].data.values.amount,undefined);assert.equal(sent[0].data.values.rooms[0].__temp,undefined);
  assert.equal(sent[0].data.values.rooms[0].people,0);assert(sent.every(row=>row.property==='hotel'));
});
test('retrying unchanged partial values does not issue a second save and preview settles only the old intent',async()=>{
  const {suite}=fixture();let calls=0;
  const session=new suite.DraftSession('hotel',async()=>{if(++calls===1)throw {status:0};return {booking:'draft',modified:'v2'};});
  await assert.rejects(session.save({rooms:[]}));await session.save({rooms:[]});assert.equal(calls,2);
  const request=session.review({instructions:'Edición aún sin guardar',rooms:[]});
  assert.equal(calls,2);assert.equal(request.modified,'v2');assert.equal(request.values.instructions,'Edición aún sin guardar');
});
test('a business rejection allows corrected values while preserving the existing version',async()=>{
  const {suite}=fixture(),requests=[];let invalid=true;
  const session=new suite.DraftSession('hotel',async(data)=>{requests.push(plain(data));if(invalid){invalid=false;throw {responseJSON:{_server_messages:'invalid'}};}return {booking:'draft',modified:'new'};},'draft','old');
  await assert.rejects(session.save({instructions:'Inválido'}));assert.equal(session.pending,null);
  await session.save({instructions:'Corregido'});assert.equal(requests[1].modified,'old');assert.equal(session.modified,'new');
});
test('unchanged DST wall times preserve both explicit folds and edited/cleared dates use the new value',()=>{
  const {suite}=fixture(),saved={starts_at:'2026-11-01T01:00:00-04:00',ends_at:'2026-11-01T01:00:00-05:00'};
  const unchanged=suite.draft_dates({starts_at:'2026-11-01T01:00',ends_at:'2026-11-01 01:00:00'},saved);
  assert.equal(unchanged.starts_at,saved.starts_at);assert.equal(unchanged.ends_at,saved.ends_at);
  const edited=suite.draft_dates({starts_at:'2026-11-01T02:00',ends_at:''},saved);
  assert.equal(edited.starts_at,'2026-11-01T02:00');assert.equal(edited.ends_at,null);
});
test('resume keeps missing dates empty, scopes links and offers save separately from price review',async()=>{
  const {desk}=fixture();let fields,secondary;
  desk.allowed=()=>true;
  const dialog={set_secondary_action_label(value){secondary=value;},set_secondary_action(){},$body:{append(){}}};
  // New editor does not require a pre-existing guest to save a partial request.
  desk.dialog=async(title,input)=>{fields=input;return dialog;};
  await desk.booking_draft_editor(null);
  assert.equal(secondary,'Guardar borrador');assert.equal(fields.find(f=>f.fieldname==='guest').reqd,false);
  assert.equal(fields.find(f=>f.fieldname==='customer').reqd,true);
  const category=fields.find(f=>f.fieldname==='rooms').fields.find(f=>f.fieldname==='category');
  await desk.booking_draft_editor({booking:{name:'draft',modified:'v1'},draft:{mode:'Hotel',rooms:[]}});
  assert.equal(fields.find(f=>f.fieldname==='starts_at').default,'');assert.equal(fields.find(f=>f.fieldname==='ends_at').default,'');
  desk.property='other';assert.equal(category.get_query().filters.property,'hotel');
  desk.allowed=()=>false;fields=null;await desk.booking_draft_editor(null);assert.equal(fields,null);
});
test('draft cards show missing data and unquoted price without leaking identifiers or mixing current bookings',()=>{
  const {desk}=fixture();desk.allowed=()=>true;desk.date=()=>'';desk.table=(headers,rows)=>JSON.stringify({headers,rows});
  desk.data.bookings=[{name:'opaque-draft',status:'Draft',amount:0,channel:'Recepción'},{name:'real-booking',status:'Confirmed',amount:1500}];
  desk.bookingLabel=()=> 'Cliente';desk.badge=status=>status;desk.amount=()=> 'C$ 1,500';desk.button=(action,label)=>label;
  let html;desk.render_reservations({html(value){html=value;}});
  assert.match(html,/Borradores por completar/);assert.match(html,/Sin cotizar/);assert.match(html,/Por definir/);assert.match(html,/Retomar borrador/);
  assert.doesNotMatch(html,/opaque-draft/);
  assert.equal((html.match(/Ver reserva/g)||[]).length,1);
  desk.allowed=()=>false;desk.render_reservations({html(value){html=value;}});assert.doesNotMatch(html,/Retomar borrador/);
});
