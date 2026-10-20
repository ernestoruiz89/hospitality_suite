const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(open_dialogs=[]){
  class Desk{constructor(){this.prop={guest_id_required:0};this.data={payment_methods:[{name:'cash',is_cash:1},{name:'bank',is_cash:0,reference_required:1}]};}}
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_forms.js'),'utf8'),{window:{hospitality_suite:{Desk}},frappe:{ui:{open_dialogs}},__:text=>text});
  return new Desk();
}
const input=(fieldname,extra={})=>({fieldname,label:fieldname,fieldtype:'Data',...extra});
test('tabbed forms preserve every original control, callback, required flag and future extension once',()=>{
  const desk=fixture(),query=()=>({filters:{property:'authorized'}}),onchange=()=>{};
  const fields=[input('block_hours',{fieldtype:'Float',default:3}),input('amount',{fieldtype:'Currency',reqd:1}),input('title'),
    input('included_services',{fieldtype:'Table',fields:[input('item',{get_query:query})]}),input('future_extension',{default:'unchanged',onchange})];
  const previous=fields.map(df=>({...df})),layout=desk.form_layout(fields),second=desk.form_layout(fields);
  for(let i=0;i<fields.length;i++){
    assert.equal(layout.fields.filter(df=>df===fields[i]).length,1);
    for(const key of ['fieldname','fieldtype','reqd','default','get_query','onchange','fields'])assert.equal(fields[i][key],previous[i][key]);
  }
  assert.equal(layout.fields.find(df=>df.fieldname==='future_extension').onchange,onchange);
  assert.equal(layout.fields.find(df=>df.fieldname==='included_services').fields[0].get_query,query);
  const tabs=layout.fields.filter(df=>df.fieldtype==='Tab Break');
  assert.equal(tabs[0].hidden,0,'native Frappe must recognize the explicit opening tab');
  assert(tabs.some(df=>df.label==='Otros ajustes'));
  assert(!second.fields.some(df=>tabs.some(tab=>tab.fieldname===df.fieldname)));
  assert.notEqual(tabs[0].parent,second.fields[0].parent);
  assert.equal(desk.form_layout([input('amount')]),null);
  assert.equal(desk.form_layout([...fields,{fieldtype:'Tab Break',fieldname:'existing'}]),null);
  assert.equal(desk.form_layout([...fields,fields[0]]),null);
});
test('hotel rates keep people charges while block/hour options are reserved for motel mode',()=>{
  const desk=fixture(),fields=['block_hours','extra_hour_rate','grace_minutes','rounding_minutes','night_start','night_end','included_people','amount','included_services'].map(name=>input(name,{default:name==='block_hours'?3:undefined}));
  desk.form_layout(fields);
  for(const name of ['block_hours','extra_hour_rate','night_start','night_end']){
    const field=fields.find(df=>df.fieldname===name);
    assert.equal(field.depends_on({mode:'Hotel'}),false);assert.equal(field.depends_on({mode:'Motel'}),true);
  }
  assert.equal(fields.find(df=>df.fieldname==='block_hours').default,3);
  assert.equal(fields.find(df=>df.fieldname==='included_people').depends_on,undefined);
});
test('cash and refund controls follow the selected intent without changing wire values or hiding the amount',()=>{
  const desk=fixture(),fields=['kind','source_payment','credit_note','reason','tendered','shift','method','amount','reference','refund_help'].map(name=>input(name,{reqd:name==='amount'}));
  fields[0].default='Payment';const layout=desk.form_layout(fields),byName=Object.fromEntries(fields.map(df=>[df.fieldname,df]));
  assert.equal(byName.kind.default,'Payment');assert.equal(byName.amount.reqd,true);assert.equal(byName.amount.depends_on,undefined);
  assert.equal(byName.source_payment.depends_on({kind:'Payment'}),false);
  assert.equal(byName.source_payment.depends_on({kind:'Refund'}),true);
  assert.equal(byName.source_payment.depends_on({kind:'Guarantee Refund'}),true);
  assert.equal(byName.credit_note.depends_on({kind:'Guarantee Refund'}),false);
  assert.equal(byName.credit_note.depends_on({kind:'Refund'}),true);
  assert.equal(byName.tendered.depends_on({method:'cash'}),true);
  assert.equal(byName.tendered.depends_on({method:'bank'}),false);
  assert.equal(byName.reference.depends_on({method:'cash'}),false);
  assert.equal(byName.reference.mandatory_depends_on({method:'bank'}),true);
  const refundTab=layout.fields.find(df=>df.fieldtype==='Tab Break'&&df.label==='Devolución');
  assert.equal(refundTab.depends_on({kind:'Advance'}),false);assert.equal(refundTab.depends_on({kind:'Refund'}),true);
  assert.equal(fields.find(df=>df.fieldname==='refund_help'),layout.fields.find(df=>df.fieldname==='refund_help'));
});
test('missing required controls reveal their tab while zero and hidden values do not become false errors',()=>{
  const desk=fixture();let activated=0,scrolled=0;
  const field=(value,extra={})=>({df:{reqd:1,...extra},get_value:()=>value});
  const missing={...field(null),tab:{tab_link:{find(selector){assert.equal(selector,'.nav-link');return{trigger(event){assert.equal(event,'click');activated++;}};}}},$wrapper:{0:{scrollIntoView(options){assert.equal(options.block,'nearest');scrolled++;}}}};
  desk.reveal_form_error({fields_dict:{zero:field(0),hidden:field(null,{hidden_due_to_dependency:1}),missing}});
  assert.equal(activated,1);assert.equal(scrolled,1);
  desk.reveal_form_error({fields_dict:{zero:field(0)}});assert.equal(activated,1);
});
test('payment headings and review actions distinguish receiving cash from returning it',()=>{
  const desk=fixture();let kind='Payment',change;const state={},dialog={
    $wrapper:{attr(key,value){state[key]=value;}},get_value(){return kind;},set_title(value){state.title=value;},
    get_primary_btn(){return{text(value){state.action=value;}};},set_df_property(name,key,value){state[key]=value;},
    fields_dict:{kind:{$input:{on(event,callback){change=callback;}}},tendered:{$input:{attr(key,value){state.aria=value;}}}}
  };
  desk.configure_form_dialog(dialog,{kind:'payment'});
  assert.equal(state.title,'Registrar cobro');assert.equal(state.action,'Revisar cobro');assert.match(state.aria,/recibido/);
  kind='Refund';change();assert.equal(state.title,'Devolver un pago');assert.equal(state.action,'Revisar devolución');assert.match(state.aria,/entregado/);
  kind='Guarantee';change();assert.equal(state.title,'Registrar garantía');assert.equal(state.action,'Revisar garantía');
  assert.equal(kind,'Guarantee');
});
test('tab selection has an explicit accessible state after navigation and required-field recovery',()=>{
  const desk=fixture(),events=[],selected=[];
  const tabs=[0,1].map(index=>({active:index===0,is_active(){return this.active;},tab_link:{find(){return{on(name,callback){events[index]=callback;},attr(name,value){assert.equal(name,'aria-selected');selected[index]=value;}};}}}));
  const dialog={tabs,$wrapper:{attr(){}}};desk.configure_form_dialog(dialog,{kind:'property'});
  assert.deepEqual(selected,['true','false']);tabs[0].active=false;tabs[1].active=true;events[1]();assert.deepEqual(selected,['false','true']);
  tabs[0].active=true;tabs[1].active=false;dialog._hsSyncFormTabs();assert.deepEqual(selected,['true','false']);
});
test('a review hides and makes its parent inert, then restores its unchanged draft on cancellation',()=>{
  const attributes={},classes=new Set(['hs-form-dialog']);let cancel;
  const parent={display:true,values:{guest:'unchanged',amount:1500},$wrapper:{hasClass:key=>classes.has(key),
    addClass(key){classes.add(key);return this;},removeClass(key){classes.delete(key);return this;},
    attr(values){Object.assign(attributes,values);return this;},removeAttr(key){delete attributes[key];return this;}}};
  const desk=fixture([parent]);
  desk.configure_form_dialog({$wrapper:{one(event,callback){assert.equal(event,'hide.bs.modal.hsFormParent');cancel=callback;}}},null);
  assert(classes.has('hs-form-suspended'));assert.equal(attributes.inert,'');assert.equal(attributes['aria-hidden'],'true');
  cancel();assert(!classes.has('hs-form-suspended'));assert.equal(attributes.inert,undefined);assert.equal(attributes['aria-hidden'],undefined);
  assert.deepEqual(parent.values,{guest:'unchanged',amount:1500});
});
