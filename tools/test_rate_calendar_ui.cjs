const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
function fixture(){
  const nodes=new Map();
  const el={find(key){if(!nodes.has(key))nodes.set(key,{attrs:{},htmlValue:'',attr(name,value){this.attrs[name]=value;return this;},html(value){this.htmlValue=value;return this;}});return nodes.get(key);}};
  const context={window:{hospitality_suite:{}},frappe:{utils:{escape_html:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;')}},
    __:(value,args)=>args?value.replace(/\{(\d+)\}/g,(_,i)=>args[i]):value};context.hospitality_suite=context.window.hospitality_suite;
  for(const name of ['hospitality.js','hospitality_extras.js'])vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js',name),'utf8'),context);
  const desk=Object.create(context.window.hospitality_suite.Desk.prototype);
  Object.assign(desk,{property:'hotel',prop:{mode:'Hotel',time_zone:'America/Managua'},data:{categories:[{name:'standard',category_name:'Estándar',capacity:2}]},amount:(value,currency)=>`${value} ${currency}`});
  return {desk,el,nodes};
}
const selection={category:'standard',from_date:'2026-10-24',days:7,people:1,mode:'Hotel',hours:3};
const response=(overrides={})=>({property:'hotel',category:'standard',from_date:'2026-10-24',days:7,read_only:true,
  rows:Array.from({length:7},(_,i)=>({date:`2026-10-${24+i}`,available:i===0?0:2,rate_status:i===1?'no_rate':'ok',amount:i===1?null:'750',currency:'NIO',rate:'rate-1',rate_title:'Temporada alta'})),...overrides});

test('rate calendar separates no rate from no inventory and displays the winning rule',async()=>{
  const f=fixture();let call;f.desk.call=async(method,args)=>{call={method,args};return response();};
  await f.desk.drawRateCalendar(f.el,selection);
  assert.equal(call.method,'rate_calendar');assert.equal(call.args.property_name,'hotel');assert.equal(call.args.category,'standard');
  const html=f.nodes.get('.hs-rate-results').htmlValue;
  assert.match(html,/Temporada alta/);assert.match(html,/750 NIO/);assert.match(html,/Sin cupo/);assert.match(html,/Sin tarifa/);
  assert.match(html,/se vuelven a comprobar al reservar|no garantiza el cupo futuro/);assert.equal(f.nodes.get('.hs-rate-results').attrs['aria-busy'],'false');
});
test('invalid filters and old property responses do not show prices',async()=>{
  const f=fixture();let calls=0;f.desk.call=async()=>{calls++;return response();};
  await f.desk.drawRateCalendar(f.el,{...selection,people:3});assert.equal(calls,0);assert.match(f.nodes.get('.hs-rate-results').htmlValue,/Revise fecha/);
  const pending=deferred();f.desk.call=()=>pending.promise;const first=f.desk.drawRateCalendar(f.el,selection);
  f.desk.property='other';pending.resolve(response());await first;assert.doesNotMatch(f.nodes.get('.hs-rate-results').htmlValue,/750 NIO/);
});
test('mismatched response does not show a different property or fabricated zero',async()=>{
  const f=fixture();f.desk.call=async()=>response({property:'other'});await f.desk.drawRateCalendar(f.el,selection);
  assert.match(f.nodes.get('.hs-rate-results').htmlValue,/No se pudo consultar/);assert.doesNotMatch(f.nodes.get('.hs-rate-results').htmlValue,/Sin cupo|750 NIO/);
});
test('duplicate priority and wrong currency remain review states without a displayed price',async()=>{
  const f=fixture(),rows=response().rows;
  rows[0]={...rows[0],rate_status:'collision',amount:null};rows[1]={...rows[1],rate_status:'wrong_currency',amount:null};
  f.desk.call=async()=>response({rows});await f.desk.drawRateCalendar(f.el,selection);
  const html=f.nodes.get('.hs-rate-results').htmlValue;
  assert.match(html,/Tarifas con la misma prioridad/);assert.match(html,/Tarifa en otra moneda/);
  assert.match(html,/Tarifas con la misma prioridad<\/td><td>—<\/td>/);
});
