// Exercise the app's rendering boundary with real labels and opaque wire keys.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

function fixture(){
  const translations={Estado:'État',Pendiente:'En attente',Importe:'Montant','Huésped registrado':'Client enregistré','Artículo del catálogo':'Article du catalogue','Con precio':'Prix défini','Sin precio':'Sans prix','Fuera de servicio':'Hors service'};
  const __=(value,args)=>String(translations[value]??value).replace(/\{(\d+)\}/g,(m,n)=>args?.[n]??m);
  const escape_html=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const hospitality_suite={};
  const $=tag=>{
    assert.equal(tag,'<option>');
    return {attributes:{},properties:{},text(v){this.textContent=v;return this;},attr(k,v){this.attributes[k]=v;return this;},
      prop(k,v){this.properties[k]=v;return this;},html(){throw new Error('Master names must never be inserted as HTML');}};
  };
  const context={window:{hospitality_suite},hospitality_suite,frappe:{utils:{escape_html}},__,$};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality.js'),'utf8'),context);
  const input={options:[],selected:'opaque-selected',val(v){if(arguments.length)this.selected=v;return this.selected;},
    empty(){this.options=[];},append(option){this.options.push(option);},trigger(event){this.event=event;}};
  const control={df:{options:[]},$input:input};
  const desk=Object.create(hospitality_suite.Desk.prototype);
  desk.prop={discreet_mode:false};desk.data={guests:[{name:'guest-key',full_name:'Estado'}],items:[{name:'item-key',item_name:'Estado'}]};
  return {control,input,desk,context,render:hospitality_suite.safe_select_options};
}

test('translated reconciliation and audit captions retain their original routing identifiers',async()=>{
  const {desk,context}=fixture(),dialogs=[],reports=[];
  context.__=text=>({'Diferencias entre PMS y ERPNext':'Écarts PMS et ERPNext',Conciliación:'Rapprochement',Auditoría:'Audit'}[text]??text);
  context.frappe.session={user:'Administrator'};desk.property='hotel';desk.allowed=()=>true;
  desk.table=(headers,rows)=>headers.join('|')+rows.flat().join('|');desk.empty=text=>text;
  desk.dialog=async(title,fields)=>{const handlers={};const d={title,fields,handlers,$wrapper:{on(event,selector,fn){handlers[selector]=fn;}}};dialogs.push(d);return d;};
  desk.action_report=async name=>reports.push(name);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_close.js'),'utf8'),context);
  const pending=await desk.show_close_pending([{type:'Diferencias entre PMS y ERPNext',documents:['ref'],items:[{label:'Cuenta',detail:'Diferencia'}]}],0);
  assert.equal(pending.title,'Écarts PMS et ERPNext');assert.match(pending.fields[0].options,/data-hs-pending-reconcile/);
  await pending.handlers['[data-hs-pending-reconcile]']();assert.deepEqual(reports,['Conciliación']);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_reporting.js'),'utf8'),context);
  desk.call=async()=>({total:1,offset:0,page_length:50,has_more:false,columns:['name'],rows:[{name:'event-ref'}]});
  const audit=await desk.show_paged('Audit','report_page',{},'Auditoría');assert.match(audit.fields[0].options,/data-hs-audit="event-ref"/);
});

test('translated availability caption still selects local datetime filters and sends the original report name',async()=>{
  const {desk,context}=fixture(),calls=[];
  context.__=(text,args)=>String(({Disponibilidad:'Disponibilité'}[text]??text)).replace('{0}',args?.[0]??'{0}');
  desk.property='hotel';desk.data.property_now='2026-10-21T10:00:00';
  desk.call=async(method,args)=>{calls.push({method,args});return {base:'Disponibilidad',companies:[],properties:[],filters:[],date_fields:[]};};
  desk.dialog=async(title,fields)=>({title,fields,fields_dict:{},async set_value(){}});
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_reporting.js'),'utf8'),context);
  const dialog=await desk.action_report('Disponibilidad');assert.match(dialog.title,/Disponibilité/);
  assert.deepEqual(Array.from(dialog.fields.filter(df=>df._hsDateTime),df=>df.fieldname),['starts_at','ends_at']);
  assert.equal(calls[0].args.report_name,'Disponibilidad');assert.equal(dialog.fields.some(df=>df.fieldname==='date_field'),false);
});

test('native operational selects translate labels and preserve values, defaults and disabled state',()=>{
  const {control,input,render}=fixture();
  control.df.options=[{value:'Pending',label:'Pendiente'},{value:'opaque-selected',label:'Estado',disabled:true}];
  render.call(control);
  assert.deepEqual(input.options.map(o=>[o.attributes.value,o.textContent,o.properties.disabled]),[['Pending','En attente',false],['opaque-selected','État',true]]);
  assert.equal(input.val(),'opaque-selected');
  assert.equal(input.event,'select-change');
});

test('Hotel and timed labels preserve persisted codes and conditional mixed-mode choices',()=>{
  const {context,control,input,render}=fixture();
  const options=context.window.hospitality_suite.mode_options(['Hotel','Motel','Mixed',{value:'',label:'Conservar modalidad'}]);
  assert.deepEqual(Array.from(options,o=>o.value),['Hotel','Motel','Mixed','']);
  assert.deepEqual(Array.from(options,o=>o.label),['Hotel','Por tiempo','Hotel y por tiempo','Conservar modalidad']);
  control.df.options=options;render.call(control);
  assert.equal(input.options[1].attributes.value,'Motel');assert.equal(input.options[1].textContent,'Por tiempo');
});

test('master-data names are literal text even when matching a translation key or containing markup',async()=>{
  const {control,input,render,desk,context}=fixture();
  control.df._hsDataOptions=true;
  control.df.options=[{value:'item-key',label:'Estado'},{value:'other-key',label:'<img src=x onerror=alert(1)>'}];
  render.call(control);
  assert.equal(input.options[0].textContent,'Estado');
  assert.equal(input.options[1].textContent,'<img src=x onerror=alert(1)>');
  assert.equal(input.options[1].attributes.value,'other-key');
  assert.equal(desk.guestName('guest-key'),'Estado');
  assert.equal(desk.itemName('item-key'),'Estado');
  assert.equal(desk.itemName('missing'),'Article du catalogue');
  assert.match(desk.badge('Pending'),/En attente/);
  assert.match(desk.badge('Pending'),/hs-pending/);
  let title;
  context.frappe.ui={Dialog:class{constructor(options){title=options.title;this.$wrapper={on(){}};}show(){}}};
  desk.call=async()=>({stay:{name:'stay-key',room:'room-key',guest:'guest-key',status:'Checked Out'},folios:[],charges:[]});
  desk.roomName=()=>'<b>H101</b>';
  desk.guestName=()=>'<img src=x onerror=alert(1)>';
  desk.date=()=>'';
  await desk.action_detail('stay-key');
  assert.match(title,/&lt;b&gt;H101&lt;\/b&gt;/);
  assert.ok(!title.includes('<img'));
});

test('secondary status captions translate without changing their CSS or protocol keys',()=>{
  const {desk}=fixture();
  for(const [key,label] of [['Priced','Prix défini'],['Missing','Sans prix'],['Fuera de servicio','Hors service']]){
    const rendered=desk.badge(key);assert.ok(rendered.includes(label));assert.ok(rendered.includes('hs-'+key.toLowerCase().replaceAll(' ','-')));
  }
});

test('display aliases remain literal data and raw catalogue names are retained',()=>{
  const {desk}=fixture();const row={name:'generated-item',item_name:'Historical name',display_name:'Estado'};desk.data.items.push(row);
  assert.equal(desk.itemName(row.name),'Estado');assert.equal(row.item_name,'Historical name');
});
