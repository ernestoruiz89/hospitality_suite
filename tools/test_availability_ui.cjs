const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(){
  class Desk{date(value){return value||'—';}allowed(){return true;}}
  const wrapper={htmlValue:'',events:{},attrs:{},html(value){this.htmlValue=value;return this;},attr(value){Object.assign(this.attrs,value);return this;},addClass(){return this;},on(events,selector,fn){for(const event of events.split(' '))this.events[event]=fn;return this;},one(event,fn){this.events[event]=fn;return this;}};
  const dialog={fields_dict:{_availability_result:{$wrapper:wrapper}},$wrapper:wrapper,hide(){wrapper.events['hide.bs.modal.hsAvailability']();}};
  const context={window:{hospitality_suite:{Desk}},frappe:{utils:{escape_html:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}},
    __:(text,args)=>args?text.replace(/\{(\d+)\}/g,(_,i)=>args[i]):text,moment:()=>({add:()=>({format:()=> '2026-10-23 14:00:00'})})};
  context.moment.tz=(value,zone)=>({tz(target){assert.equal(zone,'UTC');assert.equal(target,'America/Managua');return this;},format(){return value.replace('20:00:00','14:00:00').replace('18:00:00','12:00:00').replace(' ','T')+'-06:00';}});
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_availability.js'),'utf8'),context);
  const desk=new Desk();desk.property='hotel';desk.prop={mode:'Hotel',time_zone:'America/Managua'};
  desk.data={property_now:'2026-10-22T14:00:00-06:00',system_timezone:'UTC',rooms:[{name:'INTERNAL-ID',category:'CAT-ID'},{name:'ROOM-2',category:'CAT-ID'}],categories:[{name:'CAT-ID',category_name:'Doble'}]};
  desk.dialog=async(title,fields,submit,label)=>{Object.assign(dialog,{title,fields,submit,label});return dialog;};
  return{desk,dialog,wrapper};
}
const values={category:'CAT-ID',quantity:2,people:1,starts_at:'2026-10-22T14:00',ends_at:'2026-10-23T12:00'};
const answer=()=>({property:'hotel',category:'CAT-ID',category_label:'Doble',quantity:2,people:1,available:1,enough:false,physical_available:5,rooms:[{name:'INTERNAL-ID',room_number:'<H101>'}],needs_assignment_review:false});
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}

test('quantity form has five operational inputs, inline results and an explicit query action',async()=>{
  const {desk,dialog,wrapper}=fixture();let sent;
  desk.call=async(method,args)=>{sent={method,args};return answer();};await desk.action_availability();
  assert.equal(dialog.label,'Buscar disponibilidad');
  assert.deepEqual(Array.from(dialog.fields.filter(df=>df.reqd).map(df=>df.fieldname)),['category','quantity','people','starts_at','ends_at']);
  assert.equal(dialog.fields.find(df=>df.fieldname==='category').default,'CAT-ID');
  await dialog.submit({...values,_ignored_layout:'unsafe'},dialog);
  assert.equal(sent.method,'availability_search');assert.equal(sent.args.quantity,2);assert.equal(sent.args.property_name,'hotel');assert(!('_ignored_layout' in sent.args));
  assert.match(wrapper.htmlValue,/No alcanza el cupo para 2/);assert.match(wrapper.htmlValue,/Cupo disponible: 1/);assert.match(wrapper.htmlValue,/Ver opciones de habitación \(5\)/);
  assert.match(wrapper.htmlValue,/&lt;H101&gt;/);assert(!wrapper.htmlValue.includes('INTERNAL-ID'));assert(!wrapper.htmlValue.includes('<H101>'));
  assert.equal(wrapper.attrs['aria-busy'],'false');
});

const fits=()=>({...answer(),enough:true,available:2,starts_at:'2026-10-22 20:00:00',ends_at:'2026-10-23 18:00:00',time_zone:'America/Managua',people:3});
test('room click opens review with the accepted dates, category, people and full requested quantity, without a mutation',async()=>{
  const {desk,dialog,wrapper}=fixture(),opened=[];desk.call=async(method)=>{assert.equal(method,'availability_search');return fits();};
  desk.reservation=async(...args)=>opened.push(JSON.parse(JSON.stringify(args)));
  await desk.action_availability();await dialog.submit(values,dialog);
  assert.match(wrapper.htmlValue,/button[^>]+data-availability-room="0"/);assert.match(wrapper.htmlValue,/Reservar habitación &lt;H101&gt;/);
  const event={currentTarget:{dataset:{availabilityRoom:'0'}}};
  await wrapper.events['click.hsAvailabilityRoom'](event);await wrapper.events['click.hsAvailabilityRoom'](event);
  assert.equal(opened.length,1);assert.deepEqual(opened[0],['INTERNAL-ID',false,{property:'hotel',starts_at:'2026-10-22T14:00:00-06:00',ends_at:'2026-10-23T12:00:00-06:00',rooms:[{category:'CAT-ID',room:'INTERNAL-ID',people:3,extra_beds:0},{category:'CAT-ID',room:'',people:3,extra_beds:0}]}]);
});
test('room handoff ignores changed filters, a pending requery, old property, closed modal, invalid index and insufficient capacity',async()=>{
  for(const change of ['input','property','hide','pending','index','role','capacity']){
    const {desk,dialog,wrapper}=fixture();let opened=0;desk.reservation=async()=>opened++;desk.call=async()=>change==='capacity'?answer():fits();
    await desk.action_availability();await dialog.submit(values,dialog);
    if(change==='input')wrapper.events['input.hsAvailability']();
    if(change==='property')desk.property='other';
    if(change==='hide')dialog.hide();
    if(change==='role')desk.allowed=()=>false;
    if(change==='pending'){desk.call=()=>new Promise(()=>{});dialog.submit(values,dialog);}
    await wrapper.events['click.hsAvailabilityRoom']({currentTarget:{dataset:{availabilityRoom:change==='index'?'-1':'0'}}});
    assert.equal(opened,0,change);
  }
});
test('zero capacity is not a network error and a category-only fit warns about physical assignment',()=>{
  const {desk}=fixture();
  const zero=desk.availability_result({...answer(),available:0});assert.match(zero,/No alcanza/);assert(!zero.includes('<details>'));
  const fragmented=desk.availability_result({...answer(),enough:true,available:4,physical_available:0,rooms:[],needs_assignment_review:true});
  assert.match(fragmented,/Hay cupo para 2/);assert.match(fragmented,/revisar la asignación física/);assert(!fragmented.includes('<details>'));
});
test('edited filters, closed dialog and property change discard stale availability replies',async()=>{
  const {desk,dialog,wrapper}=fixture();await desk.action_availability();
  for(const action of [()=>wrapper.events['input.hsAvailability'](),()=>{desk.property='other';},()=>wrapper.events['hide.bs.modal.hsAvailability']()]){
    desk.property='hotel';const request=deferred();desk.call=()=>request.promise;
    const pending=dialog.submit(values,dialog);action();const before=wrapper.htmlValue;request.resolve(answer());await pending;assert.equal(wrapper.htmlValue,before);
  }
});
test('query failures and wrong response context never appear as zero capacity',async()=>{
  const {desk,dialog,wrapper}=fixture();await desk.action_availability();
  desk.call=async()=>{throw Error('offline');};await dialog.submit(values,dialog);assert.match(wrapper.htmlValue,/No se pudo consultar/);assert(!wrapper.htmlValue.includes('No alcanza'));
  desk.call=async()=>({...answer(),property:'foreign'});await dialog.submit(values,dialog);assert.match(wrapper.htmlValue,/No se pudo consultar/);assert(!wrapper.htmlValue.includes('H101'));
});
