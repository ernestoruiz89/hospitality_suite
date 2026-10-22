const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(){
  class Desk{}
  const notices=[],escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const context={window:{hospitality_suite:{Desk}},frappe:{utils:{escape_html:escape,get_random:()=> 'stable-key'},msgprint:message=>notices.push(message)},__:(text,args)=>args?text.replace(/\{(\d+)\}/g,(_,i)=>args[i]):text};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_extras.js'),'utf8'),context);
  const desk=new Desk(),dialogs=[],mutations=[];
  desk.property='property';desk.prop={time_zone:'America/Managua'};desk.date=value=>'Fecha '+value;desk.amount=value=>'C$ '+value;
  desk.data={portal_requests:[{name:'SOL-2026-00001',property:'property',full_name:'Visitante <ficticio>',category:'category',rooms:2,people:2,
    starts_at:'entrada',ends_at:'salida',hold_until:'límite',amount:3000,currency:'NIO'}],categories:[{name:'category',category_name:'Estándar'}],
    guests:[{name:'guest',full_name:'Huésped <prueba>'}],customers:[{name:'customer',customer_name:'Pagador <prueba>'}]};
  desk.guestName=id=>desk.data.guests.find(row=>row.name===id)?.full_name;
  desk.dialog=async(title,fields,submit,action)=>{const dialog={title,fields,submit,action,hidden:0,hide(){this.hidden++;}};dialogs.push(dialog);return dialog;};
  desk.call=async(method,args)=>{assert.equal(method,'preview');const data=JSON.parse(args.data);assert.deepEqual(data,{guest:'guest',customer:'customer',portal_request:'SOL-2026-00001'});return{amount:'3000.00',currency:'NIO',acceptance:'server-review'};};
  desk.mutate=async(...args)=>mutations.push(args);
  return{desk,dialogs,mutations,notices};
}
test('portal conversion retains legible request context and selected parties through review without changing its command',async()=>{
  const f=fixture();await f.desk.action_portal_convert('SOL-2026-00001');
  const initial=f.dialogs[0];assert.equal(initial.fields[0].fieldname,'portal_summary');
  const html=initial.fields[0].options;
  for(const text of ['Visitante &lt;ficticio&gt;','Estándar','2 habitaciones','2 personas','Fecha entrada','Fecha salida','Fecha límite','America/Managua'])assert(html.includes(text),text);
  assert(!html.includes('category'));assert(!html.includes('Visitante <ficticio>'));
  await initial.submit({guest:'guest',customer:'customer'},initial);
  const review=f.dialogs[1],summary=review.fields[0].options;
  for(const text of ['Huésped &lt;prueba&gt;','Pagador &lt;prueba&gt;','Fecha entrada','Fecha salida','C$ 3000.00'])assert(summary.includes(text),text);
  assert.equal(f.mutations.length,0,'opening the review must not reserve or collect');
  await review.submit({},review);
  assert.equal(f.mutations.length,1);const [action,data,key]=f.mutations[0];assert.equal(action,'convert_portal');assert.equal(key,'stable-key');
  assert.deepEqual({...data},{guest:'guest',customer:'customer',portal_request:'SOL-2026-00001',acceptance:'server-review'});
  assert.equal(initial.hidden,1);assert.equal(review.hidden,1);
});
test('a missing or foreign cached portal request cannot open a conversion form',async()=>{
  for(const foreign of [false,true]){
    const f=fixture();if(foreign)f.desk.data.portal_requests[0].property='other';else f.desk.data.portal_requests=[];
    await f.desk.action_portal_convert('SOL-2026-00001');assert.equal(f.dialogs.length,0);assert.equal(f.notices.length,1);assert.equal(f.mutations.length,0);
  }
});
