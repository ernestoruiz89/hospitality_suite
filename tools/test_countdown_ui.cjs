const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const epoch=Date.parse('2026-10-20T12:00:00Z');
function fixture(){
  let monotonic=0,wall=epoch+86400000,refreshes=0,visible=true;
  const nodes=[{dataset:{countdown:'2026-10-20 15:00:00'},textContent:''}],zones=[];
  const context={window:{hospitality_suite:{}},frappe:{utils:{escape_html:String}},Date:{now:()=>wall},performance:{now:()=>monotonic},
    navigator:{onLine:true},document:{hidden:false},$:()=>({is:()=>visible}),
    __:(text,args)=>args?text.replace(/\{(\d+)\}/g,(_,i)=>args[i]):text,
    moment:{tz(value,zone){zones.push(zone);return {valueOf:()=>Date.parse(value.replace(' ','T')+'Z')};}}};
  context.hospitality_suite=context.window.hospitality_suite;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality.js'),'utf8'),context);
  const desk=Object.create(context.window.hospitality_suite.Desk.prototype);
  desk.property='hotel';desk.data={system_timezone:'Etc/UTC',property_now:'2026-10-20T06:00:00-06:00',occupied:[{name:'stay',ends_at:nodes[0].dataset.countdown}],charges:[{amount:1500,status:'Pending'}]};
  desk.root={find(selector){assert.equal(selector,'[data-countdown]');return {each(callback){nodes.forEach((node,index)=>callback(index,node));}};}};
  desk.scheduleRefresh=()=>{refreshes++;};
  desk.connection=()=>{}; // This fixture isolates the monotonic clock, not page controls.
  return{desk,context,nodes,zones,advance(ms){monotonic+=ms;},wall(value){wall=value;},visible(value){visible=value;},refreshes:()=>refreshes};
}

test('an incorrect device clock and forward/backward clock changes never alter elapsed server time or money',()=>{
  const f=fixture(),before=JSON.stringify(f.desk.data);
  f.desk.syncClock('2026-10-20 12:00:00','Etc/UTC');f.desk.updateTimers();
  assert.equal(f.nodes[0].textContent,'Tiempo restante: 3 h 0 min');
  f.wall(epoch-7*86400000);f.advance(60000);f.desk.updateTimers();
  assert.equal(f.nodes[0].textContent,'Tiempo restante: 2 h 59 min');
  f.wall(epoch+30*86400000);f.advance(60000);f.desk.updateTimers();
  assert.equal(f.nodes[0].textContent,'Tiempo restante: 2 h 58 min');
  assert.equal(f.desk.serverNow(),epoch+120000);assert.equal(JSON.stringify(f.desk.data),before);
});
test('a fresh page reconstructs the same deadline from a new server reference rather than restarting its duration',()=>{
  const first=fixture();first.desk.syncClock('2026-10-20 12:00:00','Etc/UTC');first.advance(120000);first.desk.updateTimers();
  const reload=fixture();reload.wall(epoch-86400000);reload.desk.syncClock('2026-10-20 12:02:00','Etc/UTC');reload.desk.updateTimers();
  assert.equal(reload.nodes[0].dataset.countdown,first.nodes[0].dataset.countdown);
  assert.equal(reload.nodes[0].textContent,first.nodes[0].textContent);
});
test('countdown uses the system timezone of stored server timestamps and preserves precise deadline boundaries',()=>{
  const f=fixture();f.desk.syncClock('2026-10-20 14:59:59','Etc/UTC');f.desk.updateTimers();
  assert.equal(f.nodes[0].textContent,'Salida próxima · Tiempo restante: menos de 1 min');
  f.advance(1000);f.desk.updateTimers();assert.equal(f.nodes[0].textContent,'Hora prevista de salida alcanzada');
  f.advance(1000);f.desk.updateTimers();assert.equal(f.nodes[0].textContent,'Tiempo excedido: menos de 1 min');
  f.advance(59000);f.desk.updateTimers();assert.equal(f.nodes[0].textContent,'Tiempo excedido: 1 min');
  assert(f.zones.every(zone=>zone==='Etc/UTC'));
});
test('near departure is text, begins exactly one hour before the server deadline and becomes exceeded without changing money',()=>{
  const f=fixture(),before=JSON.stringify(f.desk.data);f.desk.syncClock('2026-10-20 13:59:59','Etc/UTC');f.desk.updateTimers();
  assert.equal(f.nodes[0].textContent,'Tiempo restante: 1 h 0 min');
  f.advance(1000);f.wall(epoch+86400000);f.desk.updateTimers();assert.equal(f.nodes[0].textContent,'Salida próxima · Tiempo restante: 1 h 0 min');
  f.advance(3601000);f.desk.updateTimers();assert.equal(f.nodes[0].textContent,'Tiempo excedido: menos de 1 min');assert.equal(JSON.stringify(f.desk.data),before);
});
test('arrival labels use the server clock, distinguish imminent and overdue reservations, and update without a mutation',()=>{
  const f=fixture();f.desk.syncClock('2026-10-20 12:00:00','Etc/UTC');
  assert.equal(f.desk.arrivalState('2026-10-20 13:00:01'),'Próxima llegada pendiente');
  assert.equal(f.desk.arrivalState('2026-10-20 13:00:00'),'Llegada próxima · sin entrada registrada');
  assert.equal(f.desk.arrivalState('2026-10-20 12:00:00'),'Llegada pendiente · hora prevista superada');
  assert.equal(f.desk.arrivalState('invalid'),'Llegada por actualizar');
  const node={dataset:{roomArrival:'2026-10-20 12:00:01'}};f.desk.route='hospitality-reception';
  f.desk.root={find(selector){return {each(callback){if(selector==='[data-room-arrival]')callback(0,node);}};}};
  f.desk.updateTimers();assert.equal(node.textContent,'Llegada próxima · sin entrada registrada');f.advance(2000);f.wall(epoch-86400000);f.desk.updateTimers();assert.equal(node.textContent,'Llegada pendiente · hora prevista superada');
});
test('missing or invalid references display an update state rather than a false amount of time',()=>{
  const f=fixture();f.desk.updateTimers();assert.equal(f.nodes[0].textContent,'Tiempo por actualizar');
  f.desk.syncClock('invalid','Etc/UTC');f.desk.updateTimers();assert.equal(f.nodes[0].textContent,'Tiempo por actualizar');
  f.desk.syncClock('2026-10-20 12:00:00','Etc/UTC');f.nodes[0].dataset.countdown='invalid';f.desk.updateTimers();
  assert.equal(f.nodes[0].textContent,'Tiempo por actualizar');
});
test('resuming a stale visible page requests a fresh server reference and skips hidden or offline surfaces',()=>{
  const f=fixture();f.desk.syncClock('2026-10-20 12:00:00','Etc/UTC');f.desk.resumeClock();assert.equal(f.refreshes(),0);
  f.advance(61000);f.context.document.hidden=true;f.desk.resumeClock();assert.equal(f.refreshes(),0);
  f.context.document.hidden=false;f.visible(false);f.desk.resumeClock();assert.equal(f.refreshes(),0);
  f.visible(true);f.context.navigator.onLine=false;f.desk.resumeClock();assert.equal(f.refreshes(),0);
  f.context.navigator.onLine=true;f.desk.resumeClock();assert.equal(f.refreshes(),1);
});
test('returning from a hidden page refreshes even when the device suspended its monotonic timer',()=>{
  const f=fixture();f.desk.syncClock('2026-10-20 12:00:00','Etc/UTC');f.advance(1000);
  f.context.document.hidden=true;f.desk.resumeClock(true);assert.equal(f.refreshes(),0);
  f.context.document.hidden=false;f.desk.resumeClock(true);assert.equal(f.refreshes(),1);
});
test('an obsolete bootstrap response cannot replace the newer property clock',async()=>{
  const f=fixture(),pending=[];let rendered;
  f.desk.root={attr(){return this;},html(){return this;}};f.desk.render=()=>{rendered=f.desk.data.tag;};f.context.localStorage={setItem(){}};
  f.desk.call=()=>new Promise(resolve=>pending.push(resolve));
  const first=f.desk.load();f.desk.property='motel';const second=f.desk.load();
  pending[1]({tag:'new',server_time:'2026-10-20 13:00:00',system_timezone:'Etc/UTC',properties:[{name:'motel'}]});await second;
  pending[0]({tag:'old',server_time:'2026-10-20 11:00:00',system_timezone:'Etc/UTC',properties:[{name:'hotel'}]});await first;
  assert.equal(rendered,'new');assert.equal(f.desk.serverNow(),epoch+3600000);
});
test('a fresh page resolves an inaccessible saved property before requesting its operational snapshot',async()=>{
  const f=fixture(),requests=[],stored=[];f.desk.data=null;f.desk.property='obsolete-property';
  f.desk.root={attr(){return this;},html(){return this;}};f.desk.render=()=>{};f.context.localStorage={setItem:(key,value)=>stored.push([key,value])};
  f.desk.call=async(method,args)=>{requests.push(args.property_name);assert.notEqual(args.property_name,'obsolete-property');return {server_time:'2026-10-20 12:00:00',system_timezone:'Etc/UTC',properties:[{name:'hotel'}]};};
  await f.desk.load();assert.deepEqual(requests,[undefined,'hotel']);assert.equal(f.desk.property,'hotel');
  assert.deepEqual(stored,[['hs-property','hotel']]);assert.equal(f.desk.serverNow(),epoch);
});
