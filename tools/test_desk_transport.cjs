// Exercise the shipped Desk methods with reordered/failed server responses.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function fixture(){
  const timers=new Map();let timer=0;
  const hospitality_suite={};
  const context={window:{hospitality_suite},hospitality_suite,__:(value,args)=>typeof value==="string"&&args?value.replace(/\{(\d+)\}/g,(m,n)=>args[n]??m):value,frappe:{utils:{escape_html:String,get_random:()=>"fallback"},show_alert(){}},
    moment:{tz:()=>({valueOf:()=>0})},localStorage:{setItem(){}},$:()=>({is:()=>true}),
    setTimeout:fn=>{timers.set(++timer,fn);return timer;},clearTimeout:id=>timers.delete(id)};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality.js'),'utf8'),context);
  const desk=Object.create(hospitality_suite.Desk.prototype);
  desk.property='hotel';desk.root={attr(k,v){desk.aria=v;return this;},html(v){desk.html=v;return this;}};
  desk.data={tag:'initial'};desk.render=()=>{desk.rendered=desk.data.tag;};desk.bind=()=>{};desk.connection=()=>{};
  return {desk,timers,context};
}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}
const snapshot=(tag,property='hotel')=>({tag,server_time:'2026-10-19 10:00:00',system_timezone:'America/Managua',properties:[{name:property}]});

test('booking descriptions use people and dates while respecting discreet mode and preserving keys',()=>{
  const {desk}=fixture();
  desk.date=()=>"23/10/2026 14:00";
  desk.data={properties:[{name:'hotel',discreet_mode:0}],bookings:[{name:'opaque-booking-key',guest:'guest-key',starts_at:'2026-10-23 14:00:00'}],guests:[{name:'guest-key',full_name:'Visitante de prueba'}],items:[{name:'STOCK-CODE',item_name:'Agua embotellada'}]};
  desk.prop=desk.data.properties[0];
  assert.equal(desk.bookingLabel('opaque-booking-key'),'Visitante de prueba · 23/10/2026 14:00');
  assert.equal(desk.itemName('STOCK-CODE'),'Agua embotellada');
  desk.data.properties[0].discreet_mode=1;
  assert.equal(desk.bookingLabel('opaque-booking-key'),'Huésped registrado · 23/10/2026 14:00');
  assert.equal(desk.data.bookings[0].name,'opaque-booking-key');
  assert.equal(desk.data.items[0].name,'STOCK-CODE');
});

test('report scope changes ignore old options and keep a failed scope unqueryable',async()=>{
  const {desk,context}=fixture();
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_reporting.js'),'utf8'),context);
  const metadata=user=>({base:'Auditoría',filters:['user'],companies:['Company'],properties:[{name:'hotel',property_name:'Hotel',company:'Company'},{name:'motel',property_name:'Motel',company:'Company'}],
    date_fields:[{value:'occurred_at',label:'Momento'}],date_field:'occurred_at',note:'Source dates',users:[{name:user,full_name:user}]});
  desk.data={property_now:'2026-10-19T10:00:00-06:00'};
  let controls,values,submit,disabled=false,queries=0,notices=0;
  context.frappe.msgprint=()=>{notices++;};
  desk.dialog=async(title,fields,callback)=>{
    submit=callback;controls=Object.fromEntries(fields.map(df=>[df.fieldname,{df}]));values=Object.fromEntries(fields.map(df=>[df.fieldname,df.default||'']));
    return {fields_dict:controls,get_value:key=>values[key],async set_value(key,value){const old=values[key];values[key]=value;if(old!==value)await controls[key].df.onchange?.();},
      set_df_property(key,property,value){controls[key].df[property]=value;},get_primary_btn:()=>({prop(key,value){disabled=value;}})};
  };
  desk.call=async()=>metadata('initial');
  const dialog=await desk.action_report('Auditoría');
  desk.show_paged=async()=>{queries++;};
  const older=deferred(),newer=deferred();let count=0;
  desk.call=()=>++count===1?older.promise:newer.promise;
  values.property_name='motel';const first=controls.property_name.df.onchange();
  values.property_name='hotel';const second=controls.property_name.df.onchange();
  newer.resolve(metadata('authorized current owner'));await second;
  older.resolve(metadata('obsolete owner'));await first;
  assert.equal(controls.user.df.options[1].value,'authorized current owner');assert.equal(disabled,false);
  desk.call=async()=>{throw Error('scope disconnected');};
  values.property_name='motel';await assert.rejects(controls.property_name.df.onchange(),/scope disconnected/);
  assert.equal(disabled,true);await submit(values,{hide(){}});assert.equal(queries,0);assert.equal(notices,1);
  desk.call=async()=>metadata('recovered owner');values.property_name='hotel';await controls.property_name.df.onchange();
  await submit(values,{hide(){}});assert.equal(queries,1);
});
test('an older success cannot overwrite a newer property response',async()=>{
  const {desk}=fixture(),old=deferred(),fresh=deferred();let count=0;
  desk.call=()=>++count===1?old.promise:fresh.promise;
  const first=desk.load();desk.property='motel';const second=desk.load();
  fresh.resolve(snapshot('new','motel'));await second;old.resolve(snapshot('old'));await first;
  assert.equal(desk.rendered,'new');assert.equal(desk.property,'motel');
});
test('an old failure cannot clear busy or replace a newer result with an error',async()=>{
  const {desk}=fixture(),old=deferred(),fresh=deferred();let count=0;
  desk.call=()=>++count===1?old.promise:fresh.promise;
  const first=desk.load(),second=desk.load();old.reject(Error('old connection failed'));await first;
  assert.equal(desk.aria,'true');assert.equal(desk.html,undefined);
  fresh.resolve(snapshot('new'));await second;assert.equal(desk.rendered,'new');assert.equal(desk.aria,'false');
});
test('an invalidation during a failed mutation is refreshed once the request ends',async()=>{
  const {desk,timers}=fixture(),pending=deferred();desk.call=()=>pending.promise;
  const mutation=desk.mutate('payment',{amount:30},'stable-key');
  desk.scheduleRefresh();[...timers.values()].at(-1)();assert.equal(desk.refreshPending,true);
  pending.reject(Error('response lost'));await assert.rejects(mutation,/response lost/);
  assert.equal(desk.busy,false);
  let refreshed=0;desk.load=()=>{refreshed++;};[...timers.values()].at(-1)();assert.equal(refreshed,1);
});
test('dialog keeps numeric edits across row refreshes and leaves untouched hidden rows alone',async()=>{
  const {desk,context}=fixture(),row1={name:'first',people:1},row2={name:'second',people:7};
  let typed='1',submit,capture;
  const input={};
  const edited={df:{fieldname:'people',fieldtype:'Int'},$input:{0:input,is:()=>true},get_input_value:()=>typed,get_parsed_value:Number,
    async parse_validate_and_set_in_model(raw){row1.people=Number(raw);}};
  const hidden={df:{fieldname:'people',fieldtype:'Int'},$input:{0:{},is:()=>false},get_input_value:()=>1,get_parsed_value:Number,
    async parse_validate_and_set_in_model(raw){row2.people=Number(raw);}};
  const primary={off(){return this;},on(event,callback){submit=callback;return this;},prop(){return this;}};
  context.__=value=>value;
  context.frappe.ui={Dialog:class{
    constructor(){this.fields_dict={rows:{df:{fieldname:'rows',fieldtype:'Table'},grid:{grid_rows:[{doc:row1,on_grid_fields_dict:{people:edited}},{doc:row2,on_grid_fields_dict:{people:hidden}}]}}};this.$wrapper={on(events,selector,callback){capture=callback;}};}
    get_primary_btn(){return primary;}show(){}get_values(){return{rows:[row1,row2]};}
  }};
  let accepted;
  await desk.dialog('Counts',[{fieldname:'rows',fieldtype:'Table'}],async values=>{accepted=values;});
  typed='2';capture({target:input});assert.equal(row1.people,2,'row change must keep what was typed');
  typed='1';row1.people=1; // a later native editor refresh must not replace the edit
  await submit();assert.equal(accepted.rows[0].people,2);assert.equal(accepted.rows[1].people,7);
});
test('a partly arrived group exposes its remaining numbered request and valid actions',async()=>{
  const {desk,context}=fixture();
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_extras.js'),'utf8'),context);
  const info={booking:{name:'group',status:'Checked In',guest:'principal',rooms:[{name:'request',idx:1,people:2}]},allocations:[{name:'allocation',booking_room:'request',category:'standard'}]};
  desk.allowed=()=>true;desk.call=async()=>info;desk.data={categories:[{name:'standard',category_name:'Estándar'}],guests:[],rooms:[]};
  let fields;desk.dialog=async(title,value)=>{fields=value;};
  await desk.action_booking('group');
  assert.deepEqual(Array.from(fields.find(f=>f.fieldname==='status').options,o=>o.value),['Check In']);
  const allocation=fields.find(f=>f.fieldname==='allocation');assert.equal(allocation.default,'allocation');
  assert.match(allocation.options[1].label,/Solicitud 1.*2 persona/);
  assert.equal(fields.find(f=>f.fieldname==='guest').default,'principal');
  info.allocations=[];let message;context.__=value=>value;context.frappe.msgprint=value=>{message=value;};fields=undefined;
  await desk.action_booking('group');assert.equal(fields,undefined);assert(message);
});
test('a native business rejection keeps its server message; a lost response gets recovery guidance',async()=>{
  const {desk,context}=fixture();let submit;const messages=[];
  context.frappe.msgprint=message=>messages.push(message);
  const primary={off(){return this;},on(event,callback){submit=callback;return this;},prop(){return this;}};
  context.frappe.ui={Dialog:class{constructor(){this.fields_dict={};this.$wrapper={on(){}};}get_primary_btn(){return primary;}show(){}get_values(){return{};}}};
  let error={status:417,responseJSON:{_server_messages:'["Cupo agotado"]'}};
  await desk.dialog('Request',[],async()=>{throw error;});await submit();assert.equal(messages.length,0);
  error={status:0};await submit();assert.equal(messages.length,1);assert.equal(messages[0].title,'Sin confirmación del servidor');
});

test('property wall-clock controls preserve native single-digit hours',async()=>{
  const {desk,context}=fixture();let received,attributes,value;
  desk.prop={time_zone:'America/Managua'};
  const primary={off(){return this;},on(){return this;},prop(){return this;}};
  context.frappe.ui={Dialog:class{
    constructor(options){received=options.fields[0];this.fields_dict={cutoff:{$input:{attr(v){attributes=v;}},set_value(v){value=v;}}};this.$wrapper={on(){}};}
    get_primary_btn(){return primary;}show(){}get_values(){return{};}
  }};
  await desk.dialog('Cutoff',[{fieldname:'cutoff',fieldtype:'Time',default:'6:45:00'}],async()=>{});
  assert.equal(received.fieldtype,'Data');assert.match(received.description,/America\/Managua/);
  assert.equal(attributes.type,'time');assert.equal(value,'06:45:00');
});
