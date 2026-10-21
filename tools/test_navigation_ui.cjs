const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
function fixture(shared=new Map()){
  const nodes=new Map(),rooms=[{name:'a',room_number:'H101',floor:'1',category:'standard',cleaning_status:'Clean',active:1},
    {name:'b',room_number:'H102',floor:'2',category:'suite',cleaning_status:'Clean',active:1,zone:'Jardín'},
    {name:'c',room_number:'H103',floor:'2',category:'suite',cleaning_status:'Dirty',active:1},
    {name:'d',room_number:'H104',floor:'2',category:'suite',cleaning_status:'Clean',active:1},
    {name:'e',room_number:'H105',floor:'2',category:'suite',cleaning_status:'Clean',active:0}];
  const cards=rooms.map(room=>({dataset:{room:room.name},visible:true,notes:[]}));
  function collection(key){if(!nodes.has(key))nodes.set(key,{value:'',attrs:{},htmlValue:'',length:1,html(value){this.htmlValue=value;return this;},attr(key,value){this.attrs[key]=value;return this;},text(value){this.textValue=value;return this;},prop(key,value){this[key]=value;return this;},val(value){if(value===undefined)return this.value;this.value=value;return this;},trigger(value){this.triggered=value;return this;},each(){return this;}});return nodes.get(key);}
  const root={htmlValue:'',html(value){this.htmlValue=value;return this;},find(key){return key==='.hs-room'?{each(callback){cards.forEach((card,index)=>callback(index,card));}}:collection(key);}};
  const context={window:{hospitality_suite:{}},frappe:{utils:{escape_html:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;')},session:{user:'manager'},set_route(route){context.destination=route;}},
    localStorage:{getItem:key=>shared.get(key)??null,setItem:(key,value)=>shared.set(key,value)},__:(text,args)=>args?text.replace(/\{(\d+)\}/g,(_,i)=>args[i]):text,
    $:node=>({toggle(value){node.visible=value;},find(){return {append(value){node.notes.push(value);}};}})};
  context.hospitality_suite=context.window.hospitality_suite;
  for(const name of ['hospitality.js','hospitality_board.js','hospitality_navigation.js'])vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js',name),'utf8'),context);
  const ns=context.window.hospitality_suite,desk=Object.create(ns.Desk.prototype);
  Object.assign(desk,{property:'hotel',route:'hospitality-home',prop:{currency:'NIO',time_zone:'America/Managua'},root,serverNow:()=>NaN,
    data:{rooms,categories:[{name:'standard',category_name:'Estándar'},{name:'suite',category_name:'Suite'}],occupied:[{room:'a',name:'stay'}],blocks:[{room:'d',starts_at:'2026-10-19 10:00:00',ends_at:null}],
      server_time:'2026-10-20 12:00:00',property_now:'2026-10-20T06:00:00-06:00',actions:['stay','report','reserve'],pages:[{route:'hospitality-home',title:'Inicio'},{route:'hospitality-stays',title:'Estancias'},{route:'hospitality-reception',title:'Recepción'}],cleaning:[],maintenance:[]}});
  return {desk,ns,context,root,nodes,cards,shared};
}
const reply=(overrides={})=>({property:'hotel',date:'2026-10-20',view:'arrivals',counts:{arrivals:3,departures:1},...overrides});

test('combined filters retain only the matching room and accent-insensitive search includes its zone',()=>{
  const f=fixture();f.desk.roomFilters={query:'jardin',clean:'Clean',floor:'2',category:'suite',state:'vacant'};f.desk.filterRooms();
  assert.deepEqual(f.cards.filter(c=>c.visible).map(c=>c.dataset.room),['b']);
  assert.equal(f.nodes.get('.hs-filter-count').textValue,'Mostrando 1 de 5 habitaciones');assert.equal(f.nodes.get('.hs-filter-empty').hidden,true);
  f.desk.update_room_filter('query','H999');assert(f.cards.every(c=>!c.visible));assert.equal(f.nodes.get('.hs-filter-empty').hidden,false);
  f.desk.action_clear_room_filters();assert.equal(f.cards.filter(c=>c.visible).length,5);assert.equal(f.nodes.get('#hs-search').triggered,'focus');
});
test('filters survive a new Desk and remain separate for each user and property',()=>{
  const f=fixture();f.desk.roomFilters=f.ns.navigation.filters(null,f.desk.data);f.desk.update_room_filter('floor','2');f.desk.update_room_filter('query','H102');
  const reload=fixture(f.shared);assert.equal(reload.desk.read_preference('room-filters').query,'H102');assert.equal(reload.desk.read_preference('room-filters').floor,'2');
  reload.desk.property='hourly';assert.equal(reload.desk.read_preference('room-filters'),null);reload.desk.save_preference('room-filters',{floor:'3'});
  reload.desk.property='hotel';assert.equal(reload.desk.read_preference('room-filters').floor,'2');
  reload.context.frappe.session.user='cleaner';assert.equal(reload.desk.read_preference('room-filters'),null);
});
test('removed metadata, corrupt JSON and denied/full storage cannot block operational Pages',()=>{
  const f=fixture(),raw={query:'  ESTANDAR  ',floor:'99',category:'removed',clean:'Unknown',state:'available'};
  const cleaned=f.ns.navigation.filters(raw,f.desk.data);assert.equal(cleaned.query,raw.query);for(const key of ['floor','category','clean','state'])assert.equal(cleaned[key],'');
  f.shared.set(f.desk.preference_key('room-filters'),'{bad');assert.equal(f.desk.read_preference('room-filters'),null);
  f.context.localStorage={getItem(){throw Error('denied');},setItem(){throw Error('full');}};
  f.desk.save_preference('room-filters',{floor:'2'});assert.equal(f.desk.read_preference('room-filters').floor,'2');
});
test('operational filters separate occupancy, current/end-exclusive blocks, dirty and inactive rooms',()=>{
  const f=fixture(),state=f.ns.navigation.state;assert.equal(state(f.desk.data.rooms[0],f.desk.data),'occupied');assert.equal(state(f.desk.data.rooms[3],f.desk.data),'blocked');assert.equal(state(f.desk.data.rooms[4],f.desk.data),'inactive');
  f.desk.data.blocks[0].ends_at=f.desk.data.server_time;assert.equal(state(f.desk.data.rooms[3],f.desk.data),'vacant');
  const clean={query:'estandar',floor:'',category:'',state:'occupied',clean:'Clean'};assert(f.ns.navigation.matches(f.desk.data.rooms[0],f.desk.data,clean));
});
test('a quota failure uses the latest session value even when an older disk value remains readable',()=>{
  const f=fixture(),key=f.desk.preference_key('room-filters');f.shared.set(key,JSON.stringify({floor:'1'}));
  f.context.localStorage.setItem=()=>{throw Error('QuotaExceededError');};f.desk.save_preference('room-filters',{floor:'2'});
  assert.equal(f.desk.read_preference('room-filters').floor,'2');
});
test('Home excludes blocked/inactive/occupied/dirty rooms and exposes only authorized links',async()=>{
  const f=fixture();f.desk.call=async()=>reply();f.desk.render_home(f.root);await new Promise(setImmediate);
  assert.match(f.root.htmlValue,/Su jornada de un vistazo/);assert.match(f.root.htmlValue,/Limpias sin ocupación ni bloqueo<\/span><strong>1<\/strong>/);
  assert.doesNotMatch(f.root.htmlValue,/Todo listo/);assert.doesNotMatch(f.root.htmlValue,/href="\/app\/hospitality-housekeeping"/);
  const pending=f.nodes.get('.hs-home-pending');assert.match(pending.htmlValue,/Llegadas pendientes<\/h3><strong>3/);assert.match(pending.htmlValue,/Ver salidas/);assert.match(pending.htmlValue,/20\/10\/2026/);assert.match(pending.htmlValue,/America\/Managua/);
});
test('Home zero is a confirmed count; an error or mismatched response never masquerades as zero',async()=>{
  const f=fixture();f.desk.homeContext={el:f.root,property:'hotel'};f.desk.call=async()=>reply({counts:{arrivals:0,departures:0}});await f.desk.load_home_pending();
  assert.match(f.nodes.get('.hs-home-pending').htmlValue,/Llegadas pendientes<\/h3><strong>0/);
  f.desk.call=async()=>reply({property:'other'});await f.desk.load_home_pending();assert.match(f.nodes.get('.hs-home-pending').htmlValue,/Reintentar pendientes/);assert.doesNotMatch(f.nodes.get('.hs-home-pending').htmlValue,/<strong>0/);
  f.desk.call=async()=>{throw Error('offline');};await f.desk.load_home_pending();assert.equal(f.nodes.get('.hs-home-pending').attrs['aria-busy'],'false');assert.match(f.nodes.get('.hs-home-pending').htmlValue,/No se pudieron consultar/);
});
test('an old Home success or failure cannot replace the current property view',async()=>{
  const f=fixture(),old=deferred(),fresh=deferred();f.desk.homeContext={el:f.root,property:'hotel'};f.desk.call=()=>old.promise;const one=f.desk.load_home_pending();
  f.desk.homeContext={el:f.root,property:'hotel'};f.desk.call=()=>fresh.promise;const two=f.desk.load_home_pending();old.resolve(reply({counts:{arrivals:99,departures:99}}));await one;
  assert.equal(f.nodes.get('.hs-home-pending').attrs['aria-busy'],'true');fresh.resolve(reply());await two;assert.doesNotMatch(f.nodes.get('.hs-home-pending').htmlValue,/99/);
  const late=deferred();f.desk.call=()=>late.promise;const three=f.desk.load_home_pending(),before=f.nodes.get('.hs-home-pending').htmlValue;f.desk.property='hourly';late.reject(Error('late'));await three;assert.equal(f.nodes.get('.hs-home-pending').htmlValue,before);
});
test('Home cannot query arrival data or navigate to stays for a cleaning-only role',async()=>{
  const f=fixture();f.desk.data.actions=['clean'];f.desk.data.pages=[{route:'hospitality-home',title:'Inicio'},{route:'hospitality-housekeeping',title:'Limpieza'}];let calls=0;f.desk.call=async()=>{calls++;};
  f.desk.render_home(f.root);await f.desk.load_home_pending();f.desk.action_home_queue('arrivals');assert.equal(calls,0);assert.equal(f.context.destination,undefined);assert.doesNotMatch(f.root.htmlValue,/hs-home-pending/);assert.match(f.root.htmlValue,/href="\/app\/hospitality-housekeeping"/);
});
test('Home queue navigation persists the exact property/date/view for the Stays Page and a reload',()=>{
  const f=fixture();f.desk.action_home_queue('departures');assert.equal(f.context.destination,'hospitality-stays');
  const next=fixture(f.shared);const selected=next.desk.restore_board_selection();assert.equal(selected.view,'departures');assert.equal(selected.date,'2026-10-20');assert.equal(selected.offset,0);
  next.desk.property='hourly';assert.equal(next.desk.restore_board_selection().view,'hosted');
  for(const date of ['2026-99-99','2026-02-31','<script>',''])assert.equal(f.ns.navigation.selection({date,view:'hack',offset:-2},'2026-10-20').date,'2026-10-20');
});
test('late room balance replies are ignored after rerender or property change; network errors do not display zero',async()=>{
  const f=fixture(),old=deferred(),fresh=deferred();f.desk.amount=(amount,currency)=>`${amount} ${currency}`;f.desk.call=()=>old.promise;const first=f.desk.load_room_balances(f.root);
  f.desk.call=()=>fresh.promise;const second=f.desk.load_room_balances(f.root);old.resolve({stay:{amount:999}});await first;assert.equal(f.cards[0].notes.length,0);
  fresh.resolve({stay:{amount:125,shared:true}});await second;assert.match(f.cards[0].notes[0],/125 NIO/);assert.match(f.cards[0].notes[0],/Saldo compartido/);
  const late=deferred();f.desk.call=()=>late.promise;const third=f.desk.load_room_balances(f.root);f.desk.property='hourly';late.reject(Error('late'));await third;assert.equal(f.cards[0].notes.length,1);
  f.desk.property='hotel';f.desk.call=async()=>{throw Error('offline');};await f.desk.load_room_balances(f.root);assert.match(f.cards[0].notes[1],/Consulte el saldo actualizado/);assert.doesNotMatch(f.cards[0].notes[1],/0 NIO/);
});
