const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(open_dialogs=[],document){
  class Desk{constructor(){this.prop={guest_id_required:0};this.data={payment_methods:[{name:'cash',is_cash:1},{name:'bank',is_cash:0,reference_required:1}]};}}
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_forms.js'),'utf8'),{document,window:{hospitality_suite:{Desk}},frappe:{ui:{open_dialogs}},__:(text,args)=>String(text).replace(/\{(\d+)\}/g,(_,n)=>args?.[n]??_)});
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

test('a mandatory unchecked checklist is the first error while a numeric zero is still valid',()=>{
  const desk=fixture();let selected;
  desk.focus_form_error=(_,field)=>selected=field;
  const numeric={df:{reqd:1,fieldtype:'Float'},get_value:()=>0},check={df:{reqd:1,fieldtype:'Check'},get_value:()=>0};
  desk.reveal_form_error({fields_dict:{numeric,check}});assert.equal(selected,check);
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

function validationFixture(){
  class Element{
    constructor(){this.children=[];this.attrs={};}
    append(node){node.parent=this;this.children.push(node);}
    prepend(node){node.parent=this;this.children.unshift(node);}
    remove(){this.parent.children=this.parent.children.filter(node=>node!==this);}
    setAttribute(key,value){this.attrs[key]=String(value);}getAttribute(key){return this.attrs[key]??null;}removeAttribute(key){delete this.attrs[key];}
    querySelector(selector){return this.children.find(node=>node.className===selector.slice(1))||this.children.map(node=>node.querySelector(selector)).find(Boolean)||null;}
  }
  const document={createElement:()=>new Element()},desk=fixture([],document),root=new Element(),body=new Element();body.className='modal-body';root.append(body);
  const events={},dialog={fields_dict:{},$wrapper:{0:root,on(name,selector,callback){events[name]=callback;}}};
  let focused;desk.reveal_form_error=d=>focused=d._hsFormErrors[0];
  const add=(name,value,extra={})=>{
    const wrapper=new Element(),input=new Element();input.validity={valid:true};wrapper.append(input);body.append(wrapper);
    const control={df:{fieldname:name,label:name,fieldtype:'Data',...extra},$wrapper:[wrapper],$input:[input],get_value:()=>value,set(value_){value=value_;}};
    dialog.fields_dict[name]=control;return control;
  };
  return{desk,dialog,root,body,document,add,events,focused:()=>focused};
}

test('inline required messages retain zero amounts and skip hidden, dependent or read-only fields',()=>{
  const f=validationFixture(),zero=f.add('amount',0,{fieldtype:'Currency',reqd:1}),check=f.add('bath',0,{fieldtype:'Check',reqd:1}),blank=f.add('name','   ',{reqd:1});
  for(const key of ['hidden','hidden_due_to_dependency','read_only'])f.add(key,'',{reqd:1,[key]:1});
  assert.equal(f.desk.validate_form_dialog(f.dialog),false);assert.equal(f.dialog._hsFormErrors.length,2);assert.equal(f.focused().field,check);
  assert.match(check.$wrapper[0].querySelector('.hs-field-error').textContent,/Marque/);assert.equal(zero.$input[0].getAttribute('aria-invalid'),null);
  check.set(1);blank.set('Visitante');assert.equal(f.desk.validate_form_dialog(f.dialog),true);
  assert.equal(check.$wrapper[0].querySelector('.hs-field-error'),null);assert.equal(blank.get_value(),'Visitante');assert.equal(zero.get_value(),0);
});

test('table errors identify the row and column without changing row identity, values or optional fields',()=>{
  const f=validationFixture(),rows=[{name:'existing',people:2,category:''},{name:'other',people:0,category:'category'}],table=f.add('rooms',rows,{fieldtype:'Table',reqd:1,fields:[input('category',{reqd:1,label:'Categoría'}),input('people',{fieldtype:'Int',reqd:1}),input('room'),input('hidden',{reqd:1,hidden:1})]});
  delete table.$input;table.grid={docfields:table.df.fields,grid_rows:[]};
  assert.equal(f.desk.validate_form_dialog(f.dialog),false);assert.equal(f.dialog._hsFormErrors.length,1);
  const message=table.$wrapper[0].querySelector('.hs-field-error');assert.match(message.textContent,/Fila 1: revise Categoría/);assert.equal(f.focused().focus.$input[0],message);
  assert.equal(table.get_value(),rows);assert.equal(rows[1].people,0);assert.equal(rows[0].category,'');
  rows[0].category='category';assert.equal(f.desk.validate_form_dialog(f.dialog),true);assert.equal(table.$wrapper[0].querySelector('.hs-field-error'),null);
  table.set([]);assert.equal(f.desk.validate_form_dialog(f.dialog),false);assert.match(table.$wrapper[0].querySelector('.hs-field-error').textContent,/Complete rooms/);
});

test('native invalid flags and incomplete browser dates cannot pass as complete optional values',()=>{
  const f=validationFixture(),link=f.add('room','missing',{fieldtype:'Link',invalid:1}),date=f.add('starts_at','');date.$input[0].validity.valid=false;
  assert.equal(f.desk.validate_form_dialog(f.dialog),false);assert.equal(f.dialog._hsFormErrors.length,2);
  delete link.df.invalid;date.$input[0].validity.valid=true;assert.equal(f.desk.validate_form_dialog(f.dialog),true);
});

test('stay intervals require a later end while report and rate date ranges include the same final day',()=>{
  const f=validationFixture(),start=f.add('starts_at','2026-10-22T14:00'),end=f.add('ends_at','2026-10-22T14:00');
  assert.equal(f.desk.validate_form_dialog(f.dialog),false);assert.equal(f.focused().field,end);assert.match(f.focused().message,/posterior/);
  end.set('2026-10-23T14:00');assert.equal(f.desk.validate_form_dialog(f.dialog),true);
  start.set('');assert.equal(f.desk.validate_form_dialog(f.dialog),true,'optional missing bounds remain optional');
  for(const [a,b] of [['from_date','to_date'],['valid_from','valid_to']]){
    f.add(a,'2026-10-22');const last=f.add(b,'2026-10-22');assert.equal(f.desk.validate_form_dialog(f.dialog),true);
    last.set('2026-10-21');assert.equal(f.desk.validate_form_dialog(f.dialog),false);assert.equal(f.focused().field,last);last.set('2026-10-22');
  }
});

test('inline errors preserve native descriptions and invalid markers, use text, and do not accumulate on retry',()=>{
  const f=validationFixture(),field=f.add('name','',{reqd:1,label:'<img src=x onerror=alert(1)>'}),target=field.$input[0];target.setAttribute('aria-describedby','native-help');target.setAttribute('aria-invalid','false');
  f.desk.validate_form_dialog(f.dialog);const old=field.$wrapper[0].querySelector('.hs-field-error');assert.equal(old.children.length,0);assert.match(old.textContent,/<img/);assert.equal(target.getAttribute('aria-invalid'),'true');
  f.desk.validate_form_dialog(f.dialog);const next=field.$wrapper[0].querySelector('.hs-field-error');assert.notEqual(old.id,next.id);
  assert.equal(target.getAttribute('aria-describedby'),'native-help '+next.id);assert.equal(field.$wrapper[0].children.length,2);
  field.set('Corrected');f.desk.validate_form_dialog(f.dialog);assert.equal(target.getAttribute('aria-describedby'),'native-help');assert.equal(target.getAttribute('aria-invalid'),'false');
  field.set('');target.setAttribute('aria-invalid','true');f.desk.validate_form_dialog(f.dialog);field.set('Corrected');f.desk.validate_form_dialog(f.dialog);assert.equal(target.getAttribute('aria-invalid'),'true','pre-existing native marker is retained');
});

test('editing clears corrected messages after the first attempt without moving focus or validating a busy draft',()=>{
  const f=validationFixture(),field=f.add('name','',{reqd:1});f.desk.prepare_form_validation(f.dialog);const change=f.events['input.hsValidation change.hsValidation'];
  change();assert.equal(f.dialog._hsValidationAttempted,undefined);f.desk.validate_form_dialog(f.dialog);const first=f.focused();
  field.set('Corrected');change();assert.equal(field.$wrapper[0].querySelector('.hs-field-error'),null);assert.equal(f.focused(),first);
  field.set('');f.dialog._hsBusy=true;change();assert.equal(field.$wrapper[0].querySelector('.hs-field-error'),null);
  f.dialog._hsBusy=false;change();assert.match(field.$wrapper[0].querySelector('.hs-field-error').textContent,/Complete/);assert.equal(f.focused(),first);
});

test('each dialog owns its accessible messages and processing state without declaring server success',()=>{
  const a=validationFixture(),b=validationFixture(),fa=a.add('name','',{reqd:1}),fb=b.add('name','',{reqd:1});b.desk=a.desk; // two dialogs in the same installed module
  a.desk.validate_form_dialog(a.dialog);b.desk.validate_form_dialog(b.dialog);
  assert.notEqual(fa.$wrapper[0].querySelector('.hs-field-error').id,fb.$wrapper[0].querySelector('.hs-field-error').id);
  a.desk.set_form_status(a.dialog,'busy','Procesando…');assert.equal(a.root.getAttribute('aria-busy'),'true');assert.equal(b.root.getAttribute('aria-busy'),'false');
  a.desk.set_form_status(a.dialog,'error','Sin confirmación');assert.equal(a.root.getAttribute('aria-busy'),'false');assert.equal(a.root.querySelector('.hs-form-status').textContent,'Sin confirmación');
  a.desk.set_form_status(a.dialog,'ready');assert.equal(a.root.querySelector('.hs-form-status').hidden,true);assert.equal(a.body.children.filter(node=>node.className==='hs-form-status').length,1);
});

test('explicit positive integer bounds reject zero, fractions, negatives and malformed drafts without affecting valid zero amounts',()=>{
  const f=validationFixture(),field=f.add('quantity',1,{fieldtype:'Int',_hsBounds:{min:1,integer:true}}),amount=f.add('amount',0,{fieldtype:'Currency',reqd:1});
  for(const value of [0,-1,1.5,'1.5','2abc',Infinity,NaN]){
    field.set(value);assert.equal(f.desk.validate_form_dialog(f.dialog),false,String(value));assert.match(f.dialog._hsFormErrors[0].message,/número entero de 1 o más/);
    assert.equal(amount.get_value(),0);
  }
  field.set(2);assert.equal(f.desk.validate_form_dialog(f.dialog),true);
});

test('bounds inspect the saved raw draft before native integer truncation and keep that mistake visible without writing the model',()=>{
  const f=validationFixture(),field=f.add('people',1,{fieldtype:'Int',_hsBounds:{min:1,integer:true}});field.$input[0].value='1';
  assert.equal(f.desk.validate_form_dialog(f.dialog,{onlyNumeric:true,pending:[{control:field,raw:'1.5'}]}),false);
  assert.equal(field.$input[0].value,'1.5');assert.equal(field.get_value(),1);assert.equal(f.focused().field,field);
  assert.match(f.dialog._hsFormErrors[0].message,/número entero/);
});

test('bounds use the control native expression/locale evaluator and leave optional blanks, read-only fields and unrelated integers alone',()=>{
  const f=validationFixture(),field=f.add('quantity',2,{fieldtype:'Int',_hsBounds:{min:1,integer:true}});let received;
  field.eval_expression=raw=>{received=raw;return raw==='1+2'?3:raw==='2,000'?2000:NaN;};
  for(const raw of ['1+2','2,000'])assert.equal(f.desk.validate_form_dialog(f.dialog,{onlyNumeric:true,pending:[{control:field,raw}]}),true);
  assert.equal(received,'2,000');assert.equal(f.dialog._hsValidationAttempted,undefined,'a passing preflight does not clear other validation state');
  field.set('');assert.equal(f.desk.validate_form_dialog(f.dialog),true);field.set(-1);field.df.read_only=1;
  f.add('priority',-5,{fieldtype:'Int'});assert.equal(f.desk.validate_form_dialog(f.dialog),true);
});

test('an explicit maximum and a nonnegative decimal bound keep zero and optional blank values valid',()=>{
  const f=validationFixture(),field=f.add('percentage',0,{fieldtype:'Float',_hsBounds:{min:0,max:100}});
  for(const value of [0,1.5,100,'']){field.set(value);assert.equal(f.desk.validate_form_dialog(f.dialog),true,String(value));}
  field.set(101);assert.equal(f.desk.validate_form_dialog(f.dialog),false);assert.match(f.dialog._hsFormErrors[0].message,/máximo permitido es 100/);
  field.set(-0.5);assert.equal(f.desk.validate_form_dialog(f.dialog),false);assert.match(f.dialog._hsFormErrors[0].message,/número de 0 o más/);
});
