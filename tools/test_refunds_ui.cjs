const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(){
  class Desk{
    constructor(){this.data={payments:[{name:'opaque-source',kind:'Advance',status:'Posted',creation:'19/10 12:00',amount:10,currency:'USD',payment_entry:'ACC-PAY-0001'},{name:'refund-key',kind:'Refund',status:'Posted'}]};}
    date(value){return value;}amount(value,currency){return value+' '+currency;}async dialog(title,fields){return fields;}
  }
  const context={window:{hospitality_suite:{Desk}},__:value=>value,frappe:{utils:{escape_html:value=>String(value).replaceAll('<','&lt;').replaceAll('>','&gt;')}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_refunds.js'),'utf8'),context);
  return new Desk();
}
test('refund source shows date, amount and native receipt while preserving its key',async()=>{
  const desk=fixture(),fields=await desk.dialog('Payment',[{fieldname:'source_payment',options:[{value:'',label:'Seleccione'},{value:'opaque-source',label:'opaque-source'},{value:'refund-key',label:'refund-key'}]}]);
  assert.equal(fields[0].options.length,2);assert.equal(fields[0].options[1].value,'opaque-source');
  assert.equal(fields[0].options[1].label,'Anticipo · 19/10 12:00 · 10 USD · ACC-PAY-0001');
  assert.match(fields[1].options,/anticipo ya aplicado/);
});
test('applied refund review distinguishes original book value and current FX without rendering untrusted HTML',()=>{
  const desk=fixture(),html=desk.refundSummary({base_currency:'NIO',refund:{mode:'Applied Advance',credit_note:'CREDIT <unsafe>',party_amount:'366.24',party_currency:'NIO',exchange_difference:'3.76'}});
  assert.match(html,/anticipo aplicado/);assert.match(html,/366.24 NIO/);assert.match(html,/3.76 NIO/);assert.match(html,/CREDIT &lt;unsafe&gt;/);assert.doesNotMatch(html,/<unsafe>/);
  assert.equal(desk.refundSummary({}),'');
});
