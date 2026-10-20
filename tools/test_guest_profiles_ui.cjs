const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const plain=value=>JSON.parse(JSON.stringify(value));
function fixture(){
  let key=0;
  const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const context={window:{hospitality_suite:{}},frappe:{utils:{escape_html:esc,get_random:()=>`key-${++key}`},ui:{open_dialogs:[]}},__:(text,args)=>args?text.replace(/\{(\d+)\}/g,(_,i)=>args[i]):text};context.hospitality_suite=context.window.hospitality_suite;
  for(const file of ['hospitality.js','hospitality_guests.js','hospitality_forms.js'])vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js',file),'utf8'),context);
  const suite=context.window.hospitality_suite,desk=Object.create(suite.Desk.prototype);
  Object.assign(desk,{property:'hotel',prop:{guest_id_required:0},data:{rooms:[],categories:[],guests:[],customers:[]},allowed:()=>true});
  return{suite,desk};
}
test('a lost registration response settles its original request and applies edits to the same guest without another registration',async()=>{
  const {suite}=fixture(),sent=[];let lost=true;
  const session=new suite.GuestSession('hotel',async(method,args)=>{sent.push({method,args:plain(args)});if(lost){lost=false;throw {status:0};}return {guest:'HUE-00001',modified:`version-${sent.length}`,related_versions:{contact:'c2',address:null}};});
  await assert.rejects(session.save({full_name:'Antes',identity_file:'drop',customer:'drop'}));
  await session.save({full_name:'Después'});
  assert.equal(sent.length,3);assert.deepEqual(sent[0],sent[1]);assert.equal(sent[2].method,'update_guest');
  assert.equal(sent[2].args.name,'HUE-00001');assert.equal(sent[2].args.modified,'version-2');assert.notEqual(sent[2].args.request_key,sent[1].args.request_key);
  assert.equal(JSON.parse(sent[2].args.data).full_name,'Después');assert.equal(JSON.parse(sent[2].args.related_versions).contact,'c2');
  assert(!('customer' in JSON.parse(sent[0].args.data)));assert(!('identity_file' in JSON.parse(sent[0].args.data)));
  assert.match(sent[2].args.reason,/Corrección durante el registro/);
});
test('unchanged network retry does not issue another correction and business rejection allows corrected input with original versions',async()=>{
  const {suite}=fixture(),sent=[];let failures=1;
  const info={guest:'existing',modified:'g1',related_versions:{contact:'c1',address:'a1'}};
  const session=new suite.GuestSession('hotel',async(method,args)=>{sent.push(plain(args));if(failures-- >0)throw {status:0};return {guest:'existing',modified:'g2',related_versions:{contact:'c2'}};},info);
  await assert.rejects(session.save({full_name:'Persona'},'Motivo'));await session.save({full_name:'Persona'},'Motivo');assert.equal(sent.length,2);assert.deepEqual(sent[0],sent[1]);
  const invalid=new suite.GuestSession('hotel',async(method,args)=>{sent.push(plain(args));if(args.reason==='')throw {_server_messages:'reason required'};return {guest:'existing',modified:'g2'};},info);
  await assert.rejects(invalid.save({full_name:'Persona'}));assert.equal(invalid.pending,null);
  await invalid.save({full_name:'Persona'},'Corregido');assert.equal(sent.at(-1).modified,'g1');assert.equal(JSON.parse(sent.at(-1).related_versions).address,'a1');
});
test('guest editor prioritizes the server policy, preserves existing data and leaves optional address fields blank',async()=>{
  const {desk}=fixture();let captured;
  desk.dialog=async(title,fields,submit,label)=>{captured={title,fields,submit,label,layout:desk.form_layout(fields)};return {hide(){}};};
  await desk.action_guest();
  assert.equal(captured.fields.find(f=>f.fieldname==='identity_number').reqd,0);assert.equal(captured.fields.find(f=>f.fieldname==='country').default,'');
  assert.match(captured.fields[0].options,/no exige identificación/);
  const tabFor=name=>{let tab;for(const df of captured.layout.fields){if(df.fieldtype==='Tab Break')tab=df.label;if(df.fieldname===name)return tab;}};
  assert.equal(tabFor('identity_number'),'Datos adicionales');assert.equal(captured.layout.action,'Registrar huésped');
  const info={guest:'existing',modified:'g1',property:'hotel',guest_id_required:true,values:{full_name:'Persona',identity_number:'FICTICIA',phone:'00000000'},customer_label:'<b>Pagador</b>',shared_contact:true,related_versions:{contact:'c1'}};
  desk.call=async()=>info;await desk.action_guest_edit('existing');
  assert.equal(captured.fields.find(f=>f.fieldname==='identity_number').reqd,1);assert.equal(tabFor('identity_number'),'Datos principales');
  assert.equal(captured.fields.find(f=>f.fieldname==='phone').default,'00000000');assert.equal(captured.fields.find(f=>f.fieldname==='reason').reqd,1);
  assert.match(captured.fields.find(f=>f.fieldname==='payer_summary').options,/&lt;b&gt;Pagador/);assert.equal(captured.layout.action,'Guardar cambios');
  assert.equal(captured.fields.filter(f=>f.fieldname==='address_line1').length,1);
});
test('guest cards display payer names and editing is restricted to the guest action',()=>{
  const {desk}=fixture();desk.data.guests=[{name:'OPAQUE-ID',full_name:'<Persona>',customer:'CUSTOMER-ID'}];desk.data.customers=[{name:'CUSTOMER-ID',customer_name:'Cliente visible'}];
  let html;desk.render_guests({html:value=>{html=value;}});assert.match(html,/Actualizar datos/);assert.match(html,/Cliente visible/);assert.match(html,/&lt;Persona&gt;/);
  assert.doesNotMatch(html.replace(/<[^>]*>/g,''),/OPAQUE-ID|CUSTOMER-ID/);
  desk.allowed=action=>action!=='guest';assert.equal(desk.button('guest_edit','Actualizar datos','OPAQUE-ID'),'');
});
test('old property replies and older edit requests do not open a guest modal or send a correction',async()=>{
  const {desk}=fixture();let opened=0,resolveOld;
  desk.dialog=async()=>{opened++;};
  const info={property:'hotel',guest:'existing',modified:'g1',values:{}};
  desk.call=async()=>{desk.property='other';return info;};await desk.action_guest_edit('existing');assert.equal(opened,0);
  desk.property='hotel';let count=0;desk.call=()=>++count===1?new Promise(resolve=>{resolveOld=resolve;}):Promise.resolve(info);
  const old=desk.action_guest_edit('old');await desk.action_guest_edit('new');resolveOld(info);await old;assert.equal(opened,1);
  desk.allowed=()=>false;desk.call=async()=>assert.fail('Unauthorized read');await desk.action_guest_edit('existing');assert.equal(opened,1);
});
