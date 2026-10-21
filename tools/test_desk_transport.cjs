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
    moment:{tz:()=>({valueOf:()=>0})},performance:{now:()=>0},localStorage:{setItem(){}},navigator:{onLine:true},$:()=>({is:()=>true}),
    setTimeout:fn=>{timers.set(++timer,fn);return timer;},clearTimeout:id=>timers.delete(id)};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality.js'),'utf8'),context);
  const desk=Object.create(hospitality_suite.Desk.prototype);
  desk.property='hotel';desk.root={attr(k,v){desk.aria=v;return this;},html(v){desk.html=v;return this;}};
  desk.data={tag:'initial'};desk.render=()=>{desk.rendered=desk.data.tag;};desk.bind=()=>{};desk.connection=()=>{};
  return {desk,timers,context};
}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}
const snapshot=(tag,property='hotel')=>({tag,server_time:'2026-10-19 10:00:00',system_timezone:'America/Managua',properties:[{name:property}]});

function activityFixture(){
  const f=fixture(),state={disabled:false,message:'',attributes:{}},banner={length:1,text(value){state.message=value;return this;},attr(key,value){state.attributes[key]=value;return this;}};
  f.context.frappe.realtime={socket:{connected:true}};
  f.desk.root.find=selector=>selector==='.hs-connection-banner'?banner:selector==='#hs-connection'?{text(){}}:{prop(key,value){if(key==='disabled')state.disabled=value;}};
  f.desk.connection=Object.getPrototypeOf(f.desk).connection;
  return{...f,state};
}

test('page activity covers a committed operation through its refresh, including actions appended after render',async()=>{
  const {desk,state}=activityFixture(),execute=deferred(),refresh=deferred(),refreshStarted=deferred();let calls=0,opened=0;
  desk.call=method=>{calls++;if(method==='execute')return execute.promise;refreshStarted.resolve();return refresh.promise;};desk.action_reserve=async()=>opened++;
  const pending=desk.mutate('reserve',{},'stable-request');
  assert.equal(state.disabled,true);assert.match(state.message,/Guardando operación/);assert.equal(desk.aria,'true');
  execute.resolve({booking:'confirmed'});await refreshStarted.promise;
  assert.equal(desk.loading,true);assert.match(desk.button('logout','Cerrar sesión'),/ disabled>/);
  await desk.run_action('reserve');assert.equal(opened,0,'an action during the confirmed-operation refresh cannot silently create a second booking');
  refresh.resolve(snapshot('updated'));assert.deepEqual(await pending,{booking:'confirmed'});
  assert.equal(calls,2);assert.equal(state.disabled,false);assert.equal(state.attributes['data-state'],'ready');assert.equal(desk.aria,'false');
  assert.doesNotMatch(desk.button('logout','Cerrar sesión'),/ disabled>/);await desk.run_action('reserve');assert.equal(opened,1);
});

test('double activation of an asynchronous detail opens once and a pending invalidation runs after the action ends',async()=>{
  const {desk,state,timers}=activityFixture(),request=deferred();let opened=0,reads=0,refreshes=0;
  desk.action_detail=async id=>{reads++;assert.equal(id,'opaque-stay');await request.promise;opened++;};
  const first=desk.run_action('detail','opaque-stay');
  assert.match(state.message,/Preparando acción/);assert.equal(state.disabled,true);
  await desk.run_action('detail','opaque-stay');await desk.run_action('detail','other-stay');assert.equal(reads,1);
  desk.scheduleRefresh();[...timers.values()].at(-1)();assert.equal(desk.refreshPending,true);
  request.resolve();await first;assert.equal(opened,1);assert.equal(state.disabled,false);
  desk.load=()=>refreshes++;[...timers.values()].at(-1)();assert.equal(refreshes,1);
});

test('action preparation is announced next to the clicked control and its local status is removed on completion or failure',async()=>{
  const {desk,context}=activityFixture();let status;
  context.document={createElement:()=>({setAttribute(key,value){this[key]=value;},remove(){this.removed=true;}})};
  const trigger={isConnected:true,insertAdjacentElement(position,node){assert.equal(position,'afterend');status=node;}};
  const request=deferred();desk.action_booking=()=>request.promise;
  const pending=desk.run_action('booking','booking-key',trigger);
  assert.equal(status.role,'status');assert.equal(status.className,'hs-action-status');assert.match(status.textContent,/Preparando acción/);assert.equal(status.removed,undefined);
  request.resolve();await pending;assert.equal(status.removed,true);
  context.frappe.msgprint=()=>{};desk.action_booking=async()=>{throw Error('read failed');};await desk.run_action('booking','booking-key',trigger);assert.equal(status.removed,true);
});

test('an action failure restores enabled controls, keeps one native error and permits a deliberate retry',async()=>{
  const {desk,state,context}=activityFixture();let notices=0,attempts=0;
  context.frappe.msgprint=()=>notices++;
  desk.action_detail=async()=>{attempts++;if(attempts===1)throw Error('unhandled transport failure');};
  await desk.run_action('detail');assert.equal(notices,1);assert.equal(state.disabled,false);assert.equal(desk.page_busy(),false);
  await desk.run_action('detail');assert.equal(attempts,2);assert.equal(notices,1);
  desk.action_detail=async()=>{throw {_server_messages:'already presented'};};await desk.run_action('detail');assert.equal(notices,1);
  context.navigator.onLine=false;await desk.run_action('detail');desk.connection();assert.equal(notices,1);assert.equal(state.disabled,true);assert.match(state.message,/Sin conexión/);
});

test('only the latest load releases the page and invalidations arriving during a load are not lost',async()=>{
  const {desk,state,timers}=activityFixture(),old=deferred(),current=deferred();let calls=0,refreshes=0;
  desk.call=()=>++calls===1?old.promise:current.promise;
  const first=desk.load(),second=desk.load();assert.match(state.message,/Actualizando información/);assert.equal(state.disabled,true);
  old.reject(Error('obsolete failure'));await first;assert.equal(desk.loading,true);assert.equal(state.disabled,true);
  desk.scheduleRefresh();[...timers.values()].at(-1)();assert.equal(desk.refreshPending,true);
  current.resolve(snapshot('current'));await second;assert.equal(desk.loading,false);assert.equal(state.disabled,false);assert.equal(desk.rendered,'current');
  desk.load=()=>refreshes++;[...timers.values()].at(-1)();assert.equal(refreshes,1);
});

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

test('reconciliation submits opaque visit keys with readable labels and clears them on scope changes',async()=>{
  const {desk,context}=fixture();
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_reporting.js'),'utf8'),context);
  const metadata=key=>({base:'Conciliación',filters:['stay','shift','status','detail_level'],companies:['Company'],properties:[{name:'hotel',property_name:'Hotel',company:'Company'}],
    date_fields:[{value:'source_date',label:'Fecha de origen'}],date_field:'source_date',note:'Cuentas completas',statuses:['OK'],shifts:[],
    stays:[{name:key,label:'Habitación H101 · Visitante · 20/10/2026 14:00 · Alojado'}]});
  desk.data={};let controls,values,submit,captured;
  desk.dialog=async(title,fields,callback)=>{
    submit=callback;controls=Object.fromEntries(fields.map(df=>[df.fieldname,{df}]));values=Object.fromEntries(fields.map(df=>[df.fieldname,df.default||'']));
    return {fields_dict:controls,get_value:key=>values[key],async set_value(key,value){values[key]=value;},
      set_df_property(key,property,value){controls[key].df[property]=value;},get_primary_btn:()=>({prop(){}})};
  };
  desk.call=async()=>metadata('opaque-visit');
  await desk.action_report('Conciliación');
  assert.equal(controls.stay.df.label,'Estancia');
  assert.equal(controls.stay.df.options[1].value,'opaque-visit');
  assert.match(controls.stay.df.options[1].label,/Habitación H101/);
  assert.doesNotMatch(controls.stay.df.options[1].label,/opaque-visit/);
  values.stay='opaque-visit';desk.show_paged=async(title,method,args)=>{captured=JSON.parse(args.filters);};
  await submit(values,{hide(){}});assert.equal(captured.stay,'opaque-visit');
  desk.call=async()=>metadata('another-visit');await controls.property_name.df.onchange();
  assert.equal(values.stay,'');assert.equal(controls.stay.df.options[1].value,'another-visit');
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
    constructor(){this.fields_dict={rows:{df:{fieldname:'rows',fieldtype:'Table'},grid:{grid_rows:[{doc:row1,on_grid_fields_dict:{people:edited}},{doc:row2,on_grid_fields_dict:{people:hidden}}]}}};this.$wrapper={addClass(){},on(events,selector,callback){capture=callback;}};}
    get_close_btn(){return{attr(){}};}get_primary_btn(){return primary;}show(){}get_values(){return{rows:[row1,row2]};}
  }};
  let accepted;
  await desk.dialog('Counts',[{fieldname:'rows',fieldtype:'Table'}],async values=>{accepted=values;});
  typed='2';capture({target:input});assert.equal(row1.people,2,'row change must keep what was typed');
  typed='1';row1.people=1; // a later native editor refresh must not replace the edit
  await submit();assert.equal(accepted.rows[0].people,2);assert.equal(accepted.rows[1].people,7);
});

test('a required checklist blocks submission and requests error focus while zero amounts and draft saves remain valid',async()=>{
  const {desk,context}=fixture();let checked=0,accepted=0,revealed=0;const messages=[];
  context.frappe.msgprint=message=>messages.push(message);desk.reveal_form_error=()=>revealed++;
  const primary={off(){return this;},on(){return this;},prop(){return this;}};
  context.frappe.ui={Dialog:class{
    constructor(){this.fields_dict={bath:{df:{fieldname:'bath',fieldtype:'Check',label:'Baño revisado',reqd:1},get_value:()=>checked},amount:{df:{fieldname:'amount',fieldtype:'Currency',reqd:1},get_value:()=>0}};this.$wrapper={addClass(){},on(){}};}
    get_close_btn(){return{attr(){}};}get_primary_btn(){return primary;}show(){}get_values(){return{bath:checked,amount:0};}
  }};
  const d=await desk.dialog('Checklist',[],async values=>{accepted++;assert.equal(values.amount,0);});
  await d._hsSubmit();assert.equal(accepted,0);assert.equal(revealed,1);assert.match(messages[0].message,/Baño revisado/);assert.equal(d._hsBusy,false);
  checked=1;await d._hsSubmit();assert.equal(accepted,1);
  checked=0;for(const key of ['hidden','hidden_due_to_dependency','read_only']){d.fields_dict.bath.df[key]=1;await d._hsSubmit();delete d.fields_dict.bath.df[key];}
  assert.equal(accepted,4);assert.equal(messages.length,1);
  await d._hsSubmit({validate:false});assert.equal(accepted,5,'partial drafts do not require the checklist');assert.equal(revealed,1);
});

test('the common dialog validates before native submission and retains one in-flight request for a safe retry',async()=>{
  const {desk,context}=fixture();vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_forms.js'),'utf8'),context);
  let name='',requests=0,reads=0,payload;const messages=[],pending=deferred();context.frappe.msgprint=value=>messages.push(value);
  context.frappe.ui={Dialog:class{
    constructor(){this.fields_dict={name:{df:{fieldname:'name',fieldtype:'Data',label:'Nombre',reqd:1},get_value:()=>name}};this.$wrapper={addClass(){},on(){}};}
    get_close_btn(){return{attr(){}};}get_primary_btn(){return{off(){return this;},on(){return this;},prop(){return this;}};}show(){}
    get_values(){reads++;return{name};}
  }};
  const dialog=await desk.dialog('Nombre',[],async values=>{payload=values;requests++;if(requests===1)await pending.promise;});
  await dialog._hsSubmit();assert.equal(reads,0);assert.equal(requests,0);assert.equal(dialog._hsFormErrors[0].field.df.fieldname,'name');assert.equal(messages.length,0,'required mistakes stay beside the field');
  name='Visitante';const first=dialog._hsSubmit();await dialog._hsSubmit();assert.equal(requests,1);assert.equal(dialog._hsBusy,true);
  pending.reject({responseJSON:{_server_messages:'Rejected by native validation'}});await first;assert.equal(dialog._hsBusy,false);assert.equal(name,'Visitante');
  await dialog._hsSubmit();assert.equal(requests,2);assert.equal(payload.name,'Visitante');assert.equal(messages.length,0,'native server rejection is not duplicated');
  name='';await dialog._hsSubmit({validate:false});assert.equal(requests,3,'partial draft saves can still omit required fields');
});

test('numeric bounds stop an original decimal draft before native parsing can silently turn it into a valid integer',async()=>{
  const {desk,context}=fixture();vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_forms.js'),'utf8'),context);
  let capture,raw='1.5',model=1,parsed=0,sent=0,reads=0;
  const input={value:'1.5'},control={df:{fieldname:'quantity',fieldtype:'Int',label:'Habitaciones',reqd:1,_hsBounds:{min:1,integer:true}},$input:{0:input,is:()=>true},get_value:()=>model,get_input_value:()=>raw,async parse_validate_and_set_in_model(value){parsed++;model=Math.trunc(Number(value));raw=String(model);}};
  context.frappe.ui={Dialog:class{
    constructor(){this.fields_dict={quantity:control};this.$wrapper={addClass(){},on(events,selector,callback){if(events.includes('hsNumeric'))capture=callback;}};}
    get_close_btn(){return{attr(){}};}get_primary_btn(){return{off(){return this;},on(){return this;},prop(){return this;}};}show(){}
    get_values(){reads++;return{quantity:model};}
  }};
  const dialog=await desk.dialog('Consulta',[],async()=>{sent++;});capture({target:input});raw='1';input.value='1'; // native blur already truncated its display
  await dialog._hsSubmit();assert.equal(parsed,0);assert.equal(reads,0);assert.equal(sent,0);assert.equal(input.value,'1.5');assert.equal(model,1);
  raw='2';capture({target:input});await dialog._hsSubmit();assert.equal(parsed,1);assert.equal(sent,1);assert.equal(model,2);
  raw='0';capture({target:input});await dialog._hsSubmit({validate:false});assert.equal(sent,2,'explicit partial drafts keep their bypass');
});

test('dependency reads keep a just-typed required price and its caret before native blur, including zero',async()=>{
  const {desk,context}=fixture();
  const input={value:'900',type:'text',isConnected:true,selectionStart:1,selectionEnd:2,getClientRects:()=>[{}],setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}};
  context.document={activeElement:input};let calls=0,original;
  context.frappe.ui={Dialog:class{
    constructor(){this.fields_dict={amount:{df:{fieldname:'amount',fieldtype:'Currency',reqd:1},$input:[input]}};this.$wrapper={addClass(){},on(){}};}
    get_close_btn(){return{attr(){}};}get_primary_btn(){return{off(){return this;},on(){return this;}};}show(){}
    get_values(ignoreErrors){assert.equal(ignoreErrors,true);assert.equal(this.fields_dict.amount.value,undefined,'read must not commit another value');calls++;const values={amount:Number(input.value)};input.value='';input.selectionStart=0;input.selectionEnd=0;return values;}
  }};
  original=context.frappe.ui.Dialog.prototype.get_values;
  const dialog=await desk.dialog('Precio',[{fieldname:'amount',fieldtype:'Currency',reqd:1}],()=>{});
  assert.equal(dialog.get_values(true).amount,900);assert.equal(input.value,'900');assert.deepEqual([input.selectionStart,input.selectionEnd],[1,2]);
  input.value='0';assert.equal(dialog.get_values(true).amount,0);assert.equal(input.value,'0');
  assert.equal(calls,2);assert.equal(context.frappe.ui.Dialog.prototype.get_values,original);
});

test('a required checkbox keeps its just-selected state while a native message retains focus',()=>{
  const {context}=fixture(),input={type:'checkbox',checked:true,isConnected:true,getClientRects:()=>[{}]},message={tagName:'H4'};
  context.document={activeElement:input};const dialog={fields_dict:{check:{df:{reqd:1},$input:[input]}}};
  const read=context.window.hospitality_suite.preserve_editing_value(dialog,function(){const values={check:input.checked?1:0};input.checked=false;context.document.activeElement=message;return values;});
  assert.equal(read.call(dialog).check,1);assert.equal(input.checked,true);assert.equal(context.document.activeElement,message);
});

test('a fast field or tab change cannot erase a required name before native debounced commit',()=>{
  const {context}=fixture(),name={value:'Tarifa escrita',isConnected:true,getClientRects:()=>[]},other={value:'NIO',isConnected:true,getClientRects:()=>[{}]};
  context.document={activeElement:other};const field={df:{reqd:1},$input:[name]},dialog={fields_dict:{name:field,other:{df:{},$input:[other]}}};
  const read=context.window.hospitality_suite.preserve_editing_value(dialog,()=>{name.value='';return{name:'Tarifa escrita'};});
  assert.equal(read().name,'Tarifa escrita');assert.equal(name.value,'Tarifa escrita','inactive tab keeps the pending name');assert.equal(field.value,undefined,'the wrapper does not write the model');
  field.df.hidden_due_to_dependency=1;read();assert.equal(name.value,'','dependency hiding is preserved');
  delete field.df.hidden_due_to_dependency;name.value='Old input';
  const commit=context.window.hospitality_suite.preserve_editing_value(dialog,()=>{field.value='New native value';name.value=field.value;return{};});
  commit();assert.equal(name.value,'New native value','a new native model value wins');
});

test('native dependency changes to hidden, disabled or replaced controls are preserved',()=>{
  const {context}=fixture();
  for(const change of ['hidden','disabled','readonly','replaced']){
    let visible=true;const input={value:'old',isConnected:true,getClientRects:()=>visible?[{}]:[]},field={df:{},$input:[input]},dialog={fields_dict:{value:field}};
    context.document={activeElement:input};
    const read=context.window.hospitality_suite.preserve_editing_value(dialog,()=>{input.value='native change';if(change==='hidden')visible=false;if(change==='disabled')input.disabled=true;if(change==='readonly')field.df.read_only=1;if(change==='replaced')field.$input=[{}];return{};});
    read();assert.equal(input.value,'native change',change);
  }
});

test('native read errors remain errors and leave the active draft intact',()=>{
  const {context}=fixture(),input={value:'unfinished',isConnected:true,getClientRects:()=>[{}]};context.document={activeElement:input};
  const dialog={fields_dict:{value:{df:{},$input:[input]}}},error=Error('native validation');
  const read=context.window.hospitality_suite.preserve_editing_value(dialog,()=>{input.value='';throw error;});
  assert.throws(read,e=>e===error);assert.equal(input.value,'unfinished');
});
test('a partly arrived group exposes its remaining numbered request and valid actions',async()=>{
  const {desk,context}=fixture();
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_booking_summary.js'),'utf8'),context);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_extras.js'),'utf8'),context);
  const info={booking:{name:'group',property:'hotel',status:'Checked In',guest:'principal',rooms:[{name:'request',idx:1,people:2}]},allocations:[{name:'allocation',booking_room:'request',category:'standard'}]};
  desk.allowed=()=>true;desk.call=async()=>info;desk.data={categories:[{name:'standard',category_name:'Estándar'}],guests:[],rooms:[]};
  desk.date=()=>'';desk.amount=()=>'';
  let fields;desk.dialog=async(title,value)=>{fields=value;return {$wrapper:{on(){}}};};
  await desk.action_booking('group');
  assert.deepEqual(Array.from(fields.find(f=>f.fieldname==='status').options,o=>o.value),['Check In']);
  const allocation=fields.find(f=>f.fieldname==='allocation');assert.equal(allocation.default,'allocation');
  assert.match(allocation.options[1].label,/Solicitud 1.*2 persona/);
  assert.equal(fields.find(f=>f.fieldname==='guest').default,'principal');
  assert.equal(allocation.depends_on({status:'Modify'}),false);
  assert.equal(fields.find(f=>f.fieldname==='guest').mandatory_depends_on({status:'Check In'}),true);
  assert.equal(fields.find(f=>f.fieldname==='reason').depends_on({status:'Check In'}),false);
  assert.equal(fields.find(f=>f.fieldname==='reason').mandatory_depends_on({status:'Cancelled'}),true);
  info.allocations=[];fields=undefined;
  await desk.action_booking('group');assert.equal(fields.length,1);assert.equal(fields[0].fieldname,'booking_summary');
});

test('partial dialog submission bypasses required-field checks and still captures typed numeric values',async()=>{
  const {desk,context}=fixture();let checks=0,accepted;
  const primary={off(){return this;},on(){return this;},prop(){return this;}};
  context.frappe.ui={Dialog:class{
    constructor(){this.fields_dict={customer:{df:{fieldname:'customer',fieldtype:'Select'},get_value:()=>''},people:{df:{fieldname:'people',fieldtype:'Int'},$input:{is:()=>true},get_input_value:()=>0,async parse_validate_and_set_in_model(){},get_value:()=>0},help:{df:{fieldname:'help',fieldtype:'HTML'},get_value:()=>'<p>Help</p>'}};this.$wrapper={addClass(){},on(){}};}
    get_close_btn(){return{attr(){}};}get_primary_btn(){return primary;}show(){}get_values(){checks++;return null;}
  }};
  const dialog=await desk.dialog('Draft',[],async()=>{throw Error('must use secondary handler');});
  await dialog._hsSubmit({validate:false,handler:async values=>{accepted=values;}});
  assert.equal(checks,0);assert.equal(accepted.customer,'');assert.equal(accepted.people,0);assert.equal(accepted.help,undefined);
});
test('a native business rejection keeps its server message; a lost response gets recovery guidance',async()=>{
  const {desk,context}=fixture();let submit;const messages=[];
  context.frappe.msgprint=message=>messages.push(message);
  const primary={off(){return this;},on(event,callback){submit=callback;return this;},prop(){return this;}};
  context.frappe.ui={Dialog:class{constructor(){this.fields_dict={};this.$wrapper={addClass(){},on(){}};}get_close_btn(){return{attr(){}};}get_primary_btn(){return primary;}show(){}get_values(){return{};}}};
  let error={status:417,responseJSON:{_server_messages:'["Cupo agotado"]'}};
  await desk.dialog('Request',[],async()=>{throw error;});await submit();assert.equal(messages.length,0);
  error={status:0};await submit();assert.equal(messages.length,1);assert.equal(messages[0].title,'Sin confirmación del servidor');
});

test('property wall-clock controls preserve native single-digit hours',async()=>{
  const {desk,context}=fixture();let received,attributes,value;
  desk.prop={time_zone:'America/Managua'};
  const primary={off(){return this;},on(){return this;},prop(){return this;}};
  context.frappe.ui={Dialog:class{
    constructor(options){received=options.fields[0];this.fields_dict={[received.fieldname]:{$input:{attr(v){attributes=v;}},set_value(v){value=v;}}};this.$wrapper={addClass(){},on(){}};}
    get_close_btn(){return{attr(){}};}get_primary_btn(){return primary;}show(){}get_values(){return{};}
  }};
  await desk.dialog('Cutoff',[{fieldname:'cutoff',fieldtype:'Time',default:'6:45:00'}],async()=>{});
  assert.equal(received.fieldtype,'Data');assert.match(received.description,/America\/Managua/);
  assert.equal(attributes.type,'time');assert.equal(value,'06:45:00');
  desk.prop=undefined;
  await desk.dialog('Initial setup',[{fieldname:'cutoff',fieldtype:'Time',default:'06:00:00',description:'Zona elegida en este formulario'}],async()=>{});
  assert.equal(received.description,'Zona elegida en este formulario');
  assert.equal(value,'06:00:00');
  const original=desk.dialog;let setupFields;
  desk.dialog=(title,fields)=>{setupFields=fields;};
  desk.action_new_property();desk.dialog=original;
  const date=setupFields.find(df=>df.fieldname==='business_date');
  await desk.dialog('Initial date',[{...date,default:'2026-10-18'}],async()=>{});
  assert.equal(attributes.type,'date');assert.equal(value,'2026-10-18');
});
