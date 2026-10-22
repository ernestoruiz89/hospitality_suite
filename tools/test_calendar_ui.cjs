const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
function fixture(){
  const nodes=new Map(),zones=[];
  const find=key=>{if(!nodes.has(key))nodes.set(key,{attrs:{},htmlValue:'',attr(key,value){this.attrs[key]=value;return this;},html(value){this.htmlValue=value;return this;}});return nodes.get(key);};
  class Clock{
    constructor(value){this.ms=typeof value==='number'?value:Date.parse(String(value).slice(0,19)+(String(value).length===10?'T00:00:00':'')+'Z');}
    clone(){return new Clock(this.ms);}add(amount,unit){this.ms+=amount*({days:86400000,minutes:60000}[unit]||0);return this;}valueOf(){return this.ms+21600000;}
    isValid(){return Number.isFinite(this.ms);}isBefore(other){return this.ms<other.ms;}isAfter(other){return this.ms>other.ms;}
    format(pattern){const value=new Date(this.ms).toISOString();return pattern==='YYYY-MM-DD'?value.slice(0,10):pattern==='YYYY-MM-DDTHH:mm:ssZ'?value.slice(0,19)+'-06:00':value.slice(0,16);}
  }
  const moment=value=>new Clock(value);moment.tz=(date,format,zone)=>{zones.push([format,zone]);return new Clock(date);};
  const context={window:{hospitality_suite:{}},frappe:{utils:{escape_html:value=>String(value).replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}},moment,
    __:(text,args)=>args?text.replace(/\{(\d+)\}/g,(_,i)=>args[i]):text};context.hospitality_suite=context.window.hospitality_suite;
  for(const name of ['hospitality.js','hospitality_extras.js'])vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js',name),'utf8'),context);
  const desk=Object.create(context.window.hospitality_suite.Desk.prototype);
  Object.assign(desk,{property:'hotel',prop:{mode:'Hotel',time_zone:'America/Managua'},data:{rooms:[{name:'room',room_number:'H101'}],actions:['reserve']},
    table:(headers,rows)=>JSON.stringify({headers,rows}),date:value=>String(value),action_owner:()=> 'review',page_busy:()=>false});
  return {desk,el:{find},nodes,zones,context};
}
test('calendar clears the previous range, announces loading and queries an explicit property timezone',async()=>{
  const f=fixture(),request=deferred();let query;f.desk.call=(method,args)=>{assert.equal(method,'calendar');query=args;return request.promise;};
  const pending=f.desk.drawCalendar(f.el,'2026-10-20');assert.equal(f.nodes.get('.hs-calendar').attrs['aria-busy'],'true');assert.match(f.nodes.get('.hs-calendar').htmlValue,/Cargando calendario/);
  assert.equal(query.starts_at,'2026-10-20T00:00:00-06:00');assert.equal(query.ends_at,'2026-10-27T00:00:00-06:00');assert.deepEqual(f.zones,[['YYYY-MM-DD','America/Managua']]);
  request.resolve([]);await pending;assert.match(f.nodes.get('.hs-calendar').htmlValue,/Sin asignación/);assert.doesNotMatch(f.nodes.get('.hs-calendar').htmlValue,/Libre|Disponible/);assert.equal(f.nodes.get('.hs-calendar').attrs['aria-busy'],'false');
});
test('an older calendar response or error cannot replace a more recent date or clear its busy state',async()=>{
  const f=fixture(),old=deferred(),fresh=deferred();f.desk.call=()=>old.promise;const first=f.desk.drawCalendar(f.el,'2026-10-20');
  f.desk.call=()=>fresh.promise;const second=f.desk.drawCalendar(f.el,'2026-10-21');old.reject(Error('late failure'));await first;
  assert.equal(f.nodes.get('.hs-calendar').attrs['aria-busy'],'true');assert.doesNotMatch(f.nodes.get('.hs-calendar').htmlValue,/No se pudo/);
  fresh.resolve([]);await second;assert.match(f.nodes.get('.hs-calendar').htmlValue,/2026-10-21/);assert.doesNotMatch(f.nodes.get('.hs-calendar').htmlValue,/2026-10-20/);
});
test('changing the property invalidates success before it can combine rows with the new room list',async()=>{
  const f=fixture(),request=deferred();f.desk.call=()=>request.promise;const pending=f.desk.drawCalendar(f.el,'2026-10-20');
  f.desk.property='other';f.desk.data.rooms=[{name:'foreign',room_number:'M101'}];const before=f.nodes.get('.hs-calendar').htmlValue;
  request.resolve([{room:'room',kind:'Reservation',booking:'sensitive-id',starts_at:'2026-10-20T01:00:00-06:00',ends_at:'2026-10-21T01:00:00-06:00'}]);await pending;
  assert.equal(f.nodes.get('.hs-calendar').htmlValue,before);
});
test('invalid or empty dates invalidate in-flight work and identify the date field without querying',async()=>{
  const f=fixture(),request=deferred();let calls=0;f.desk.call=()=>{calls++;return request.promise;};const pending=f.desk.drawCalendar(f.el,'2026-10-20');
  await f.desk.drawCalendar(f.el,'');assert.equal(calls,1);assert.equal(f.nodes.get('#hs-calendar-date').attrs['aria-invalid'],'true');assert.match(f.nodes.get('.hs-calendar').htmlValue,/Seleccione una fecha válida/);
  request.resolve([]);await pending;assert.match(f.nodes.get('.hs-calendar').htmlValue,/Seleccione una fecha válida/);assert.equal(f.nodes.get('.hs-calendar').attrs['aria-busy'],'false');
});
test('network failure and malformed data display retry guidance instead of an empty available calendar',async()=>{
  const f=fixture();for(const response of [()=>Promise.reject(Error('offline')),async()=>({rows:[]})]){
    f.desk.call=response;await f.desk.drawCalendar(f.el,'2026-10-20');assert.match(f.nodes.get('.hs-calendar').htmlValue,/No se pudo cargar/);assert.match(f.nodes.get('.hs-calendar').htmlValue,/reintentar/);assert.doesNotMatch(f.nodes.get('.hs-calendar').htmlValue,/Sin asignación/);assert.equal(f.nodes.get('.hs-calendar').attrs['aria-busy'],'false');
  }
});
test('weekday headings follow the user language, default to Spanish, and safely recover from an invalid locale',async()=>{
  const f=fixture();f.desk.call=async()=>[];await f.desk.drawCalendar(f.el,'2026-10-20');assert.match(f.nodes.get('.hs-calendar').htmlValue,/mar /);
  f.context.frappe.boot={lang:'en_US'};await f.desk.drawCalendar(f.el,'2026-10-20');assert.match(f.nodes.get('.hs-calendar').htmlValue,/Tue /);
  f.context.frappe.boot.lang='invalid!';await f.desk.drawCalendar(f.el,'2026-10-20');assert.match(f.nodes.get('.hs-calendar').htmlValue,/mar /);assert.doesNotMatch(f.nodes.get('.hs-calendar').htmlValue,/No se pudo cargar/);
});
test('continuous bars keep the booking action and clipped interval without declaring empty slots available',async()=>{
  const f=fixture();
  f.desk.call=async()=>[{room:'room',kind:'Reservation',booking:'BOOK-1',starts_at:'2026-10-20T12:00:00-06:00',ends_at:'2026-10-22T12:00:00-06:00'}];
  await f.desk.drawCalendar(f.el,'2026-10-20');
  const html=f.nodes.get('.hs-calendar').htmlValue;
  assert.match(html,/hs-timeline-bar is-reservation/);
  assert.match(html,/data-act="booking" data-id="BOOK-1"/);
  assert.match(html,/left:7\.1429%;width:28\.5714%/);
  assert.match(html,/Una celda sin asignación no confirma disponibilidad/);
});
test('hourly motel chart clips a stay that crosses midnight to the selected local day',async()=>{
  const f=fixture();f.desk.prop.mode='Por tiempo';
  f.desk.call=async()=>[{room:'room',kind:'Stay',stay:'STAY-1',starts_at:'2026-10-19T23:00:00-06:00',ends_at:'2026-10-20T03:00:00-06:00'}];
  await f.desk.drawCalendar(f.el,'2026-10-20');
  const html=f.nodes.get('.hs-calendar').htmlValue;
  assert.match(html,/hs-timeline-bar is-stay/);
  assert.match(html,/data-act="detail" data-id="STAY-1"/);
  assert.match(html,/left:0\.0000%;width:12\.5000%/);
});
test('short hotel intervals keep their exact marker and a usable detail action in the list',async()=>{
  const f=fixture();f.desk.call=async()=>[{room:'room',kind:'Stay',stay:'STAY-SHORT',starts_at:'2026-10-20T09:00:00-06:00',ends_at:'2026-10-20T09:15:00-06:00'}];
  await f.desk.drawCalendar(f.el,'2026-10-20');
  const html=f.nodes.get('.hs-calendar').htmlValue;
  assert.match(html,/hs-timeline-bar is-stay is-short/);
  assert.match(html,/Intervalos breves/);
  assert.match(html,/STAY-SHORT/);
  assert.equal((html.match(/data-act=\\"detail\\"/g)||[]).length,1,'only the list exposes the action for a narrow marker');
});
