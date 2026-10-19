// Exercise the app's rendering boundary with real labels and opaque wire keys.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

function fixture(){
  const translations={Estado:'État',Pendiente:'En attente',Importe:'Montant','Huésped registrado':'Client enregistré','Artículo del catálogo':'Article du catalogue'};
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

test('native operational selects translate labels and preserve values, defaults and disabled state',()=>{
  const {control,input,render}=fixture();
  control.df.options=[{value:'Pending',label:'Pendiente'},{value:'opaque-selected',label:'Estado',disabled:true}];
  render.call(control);
  assert.deepEqual(input.options.map(o=>[o.attributes.value,o.textContent,o.properties.disabled]),[['Pending','En attente',false],['opaque-selected','État',true]]);
  assert.equal(input.val(),'opaque-selected');
  assert.equal(input.event,'select-change');
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
