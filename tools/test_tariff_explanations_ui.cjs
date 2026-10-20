const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(){
  class Desk{amount(value,currency){return value+' '+currency;}}
  const context={window:{hospitality_suite:{Desk}},__:value=>value,frappe:{utils:{escape_html:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_tariffs.js'),'utf8'),context);
  return new Desk();
}
test('price explanation starts collapsed, distinguishes recorded and reference amounts and escapes every historical string',()=>{
  const desk=fixture(),charge={pricing:{title:'<b>Tarifa antigua</b>',scope:'Diferencia <script>x</script>',recorded_amount:'100.00',currency:'NIO',entries:[{label:'Noche <img src=x>',amount:'1500.00',currency:'NIO',details:['Base <script>x</script>']}],notes:['Motivo <svg>']}};
  const before=JSON.stringify(charge),html=desk.priceExplanation(charge);
  assert.match(html,/<details class="hs-price-explanation">/);assert.doesNotMatch(html,/<details[^>]*open/);
  assert.match(html,/Importe de este movimiento.*100.00 NIO/);assert.match(html,/Importe histórico de referencia.*1500.00 NIO/);
  assert.match(html,/&lt;script&gt;/);assert.match(html,/&lt;img/);assert.match(html,/&lt;svg/);assert.match(html,/&lt;b&gt;/);
  assert.doesNotMatch(html,/<script>|<img |<svg>/);assert.equal(JSON.stringify(charge),before);
});
test('legacy missing explanation leaves the account usable and recorded-only notes invent no tariff',()=>{
  const desk=fixture();assert.equal(desk.priceExplanation({amount:7}),'');
  const html=desk.priceExplanation({pricing:{title:'Explicación del cargo',scope:'Importe registrado',recorded_amount:7,currency:'NIO',entries:[],notes:['Sin desglose histórico válido']}});
  assert.match(html,/7 NIO/);assert.match(html,/Sin desglose histórico válido/);assert.doesNotMatch(html,/Importe histórico de referencia/);
});
test('account renders the server explanation in its own charge row while retaining financial and account actions',()=>{
  const source=fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality.js'),'utf8');
  const calls=[];let captured;
  const context={window:{hospitality_suite:{}},hospitality_suite:{},__:value=>value,frappe:{utils:{escape_html:String},ui:{Dialog:class{constructor(options){captured=options;}show(){}$wrapper={on(){}};}}}};
  context.hospitality_suite=context.window.hospitality_suite;
  vm.runInNewContext(source,context);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_tariffs.js'),'utf8'),context);
  const desk=Object.create(context.window.hospitality_suite.Desk.prototype);
  Object.assign(desk,{call:async()=>({stay:{name:'stay',room:'room',guest:'guest',status:'Active'},folios:[{name:'folio',label:'Cuenta',balance:{outstanding:7}}],charges:[{name:'charge',description:'Alojamiento',folio:'folio',amount:7,currency:'NIO',status:'Pending',pricing:{title:'Regla histórica',recorded_amount:7,currency:'NIO',entries:[],notes:[]}}]}),roomName:()=> 'H101',guestName:()=> 'Visitante',date:()=> '',amount:value=>String(value),badge:()=> '',allowed:()=>true,button:(action,label,id)=>{calls.push({action,id});return label;}});
  return desk.action_detail('stay').then(()=>{assert.match(captured.fields[0].options,/Ver cálculo del precio/);assert.match(captured.fields[0].options,/Regla histórica/);assert(calls.some(call=>call.action==='invoice'));assert(calls.some(call=>call.action==='move_charge'&&call.id==='charge'));});
});
