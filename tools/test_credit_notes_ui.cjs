const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(){
  class Desk{
    constructor(){this.property='property-key';this.data={shifts:[{name:'opaque-shift',status:'Open',opened_at:'19/10 12:00',cashier:'Caja <uno>',currency:'NIO'}]};this.dialogs=[];this.queries=[];this.writes=[];}
    date(value){return value;}amount(value,currency){return value+' '+currency;}
    table(headers,rows){return rows.map(row=>row.join('|')).join('\n');}invoiceLink(name){return 'native:'+name;}
    async dialog(title,fields,submit,label){const entry={title,fields,submit,label,hidden:false,hide(){this.hidden=true;}};this.dialogs.push(entry);return entry;}
    async call(method,args){this.queries.push({method,...args});const data=JSON.parse(args.data);return {invoice:'INV-1',currency:'NIO',total:data.items?'30.00':'60.00',is_pos:true,update_stock:true,acceptance:data.items?'partial-proof':'full-proof',items:[{invoice_item:'opaque-line',item_name:'Agua <servicio>',quantity:data.items?'1':'2',amount:data.items?'30':'60'}],pos:{party_amount:data.items?'30':'60',party_currency:'NIO',offset:'0',write_off_base:'0',exchange_difference:'0',base_currency:'NIO',payments:[{mode_of_payment:'Efectivo <medio>',is_cash:true,amount:data.items?'30':'60',currency:'NIO'}]}};}
    async mutate(action,values,key){this.writes.push({action,values,key});return {credit_note:'CREDIT-1',refund_journal:'JV<cash>'};}
  }
  const messages=[],context={window:{hospitality_suite:{Desk}},__:value=>value,frappe:{utils:{get_random:()=> 'one-intention-key',escape_html:value=>String(value).replaceAll('<','&lt;').replaceAll('>','&gt;')},msgprint:value=>messages.push(value),throw:message=>{throw Error(message);}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_credits.js'),'utf8'),context);
  return {desk:new Desk(),messages};
}
test('full credit reviews net money and escaped labels before one stable intention posts',async()=>{
  const {desk,messages}=fixture(),source=await desk.action_credit();
  const shift=source.fields.find(field=>field.fieldname==='shift');
  assert.equal(shift.options[1].value,'opaque-shift');assert.match(shift.options[1].label,/19\/10.*Caja <uno>.*NIO/);
  await source.submit({invoice:'INV-1',shift:'opaque-shift',reason:'Motivo'},source);
  assert.equal(desk.writes.length,0);const review=desk.dialogs[1],html=review.fields[0].options;
  assert.match(html,/60.00 NIO/);assert.match(html,/neta del vuelto/);assert.match(html,/Agua &lt;servicio&gt;/);assert.match(html,/Efectivo &lt;medio&gt;/);assert.doesNotMatch(html,/<servicio>|<medio>|opaque-line/);
  await review.submit({},review);
  assert.equal(desk.writes[0].values.acceptance,'full-proof');assert.equal(desk.writes[0].key,'one-intention-key');
  assert.equal(desk.writes[0].values.partial,undefined);assert.equal(source.hidden,true);assert.equal(review.hidden,true);
  assert.match(messages[0].message,/native:CREDIT-1/);assert.match(messages[0].message,/Journal%20Entry/);assert.match(messages[0].message,/JV%3Ccash%3E/);assert.doesNotMatch(messages[0].message,/JV<cash>/);
  const recovery=desk.creditSummary({currency:'NIO',total:'60',is_pos:true,items:[],pos:{payments:[{mode_of_payment:'Efectivo',is_cash:true,amount:'-40',currency:'NIO'}]}});
  assert.match(recovery,/Recibir\|40 NIO/);
  const rounded=desk.creditSummary({currency:'NIO',total:'60',rounding_adjustment:'-0.15',items:[]});
  assert.match(rounded,/Redondeo de la nota:/);assert.match(rounded,/-0.15 NIO/);
});
test('partial return sends selected source lines, requotes changed quantities and preserves its intention',async()=>{
  const {desk}=fixture(),source=await desk.action_credit();
  await source.submit({invoice:'INV-1',shift:'opaque-shift',partial:1,reason:'Motivo'},source);
  const selection=desk.dialogs[1];assert.equal(selection.fields[0].data[0].quantity,2);
  await selection.submit({items:[{invoice_item:'opaque-line',item_name:'Nombre modificado',quantity:1},{invoice_item:'unused',quantity:0}]},selection);
  assert.equal(desk.queries.length,2);const values=JSON.parse(desk.queries[1].data);
  assert.deepEqual(values.items,[{invoice_item:'opaque-line',quantity:1}]);assert.equal(values.partial,undefined);
  const review=desk.dialogs[2];assert.match(review.fields[0].options,/30.00 NIO/);
  await review.submit({},review);assert.equal(desk.writes[0].values.acceptance,'partial-proof');
  assert.equal(desk.writes[0].values.items[0].invoice_item,'opaque-line');assert.equal(desk.writes[0].key,'one-intention-key');assert.equal(selection.hidden,true);
});

test('additional receipts show remaining credit, dates and native documents without opaque source keys',async()=>{
  const {desk,messages}=fixture();
  const pos={remaining_credit:'30.00',party_currency:'NIO',additional_sources:[{source:'opaque-source',kind:'Payment',creation:'19/10 14:00',amount:'30.00',currency:'NIO',original:'REC<01>'}]};
  const html=desk.creditRemaining(pos);
  assert.match(html,/Crédito pendiente de devolver:.*30.00 NIO/);
  assert.match(html,/Cobrar.*Devolución/);assert.match(html,/Cobro\|19\/10 14:00\|30.00 NIO\|REC&lt;01&gt;/);
  assert.doesNotMatch(html,/opaque-source|REC<01>/);assert.equal(desk.creditRemaining({remaining_credit:'0'}),'');
  desk.mutate=async()=>({credit_note:'CREDIT-1',pos});
  const source=await desk.action_credit();await source.submit({invoice:'INV-1',reason:'Motivo'},source);
  await desk.dialogs[1].submit({},desk.dialogs[1]);
  assert.match(messages[0].message,/Crédito pendiente de devolver/);assert.match(messages[0].message,/REC&lt;01&gt;/);
});
