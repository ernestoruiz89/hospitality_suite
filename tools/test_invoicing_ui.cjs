const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(){
  const dialogs=[],calls=[],movements=[],messages=[];
  class Desk{
    constructor(){this.property='hotel';this.data={};this.permission=true;}
    allowed(){return this.permission;}
    amount(value,currency){return value+' '+currency;}
    table(headers,rows){return rows.flat().join('|');}
    invoiceLink(name){return 'Invoice '+name;}
    async call(method,args){calls.push({method,args});return method==='stay_detail'?{folios:[{name:'folio-key',label:'Cuenta principal',status:'Open'}]}:this.quote;}
    async dialog(title,fields,submit,label){const dialog={title,fields,submit,label,hidden:false,hide(){this.hidden=true;}};dialogs.push(dialog);return dialog;}
    async mutate(action,data,key){movements.push({action,data,key});if(this.fail){this.fail=false;throw Error('response lost');}return{invoice:'INV-TEST',outstanding:'0.00'};}
  }
  const context={window:{hospitality_suite:{Desk}},__:value=>value,frappe:{utils:{get_random:()=> 'stable-invoice-key',escape_html:value=>String(value).replaceAll('<','&lt;').replaceAll('>','&gt;')},msgprint:value=>messages.push(value)}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_invoicing.js'),'utf8'),context);
  const desk=new Desk();desk.quote={ready:true,folio:'folio-key',label:'Cuenta principal',customer:'<Cliente>',posting_date:'2026-10-20',currency:'NIO',
    net_total:'0.00',taxes:'0.00',total:'0.00',payable:'0.00',advance:'0.00',outstanding:'0.00',outstanding_currency:'NIO',scheduled:'0.00',acceptance:'review-proof'};
  return{desk,dialogs,calls,movements,messages};
}
test('zero invoice needs review and confirmation, preserves its account key and creates no cash action',async()=>{
  const {desk,dialogs,calls,movements,messages}=fixture();
  await desk.action_invoice('stay-key');
  assert.equal(dialogs[0].label,'Revisar factura');assert.equal(dialogs[0].fields[1].default,'folio-key');
  await dialogs[0].submit({folio:'folio-key'},dialogs[0]);
  assert.equal(calls[1].args.action,'invoice');assert.equal(movements.length,0);
  const review=dialogs[1];assert.equal(review.label,'Emitir factura');assert.match(review.fields[0].options,/0.00 NIO/);
  assert.match(review.fields[0].options,/&lt;Cliente&gt;/);assert(!review.fields[0].options.includes('<Cliente>'));
  await review.submit({},review);
  assert.equal(movements.length,1);assert.equal(movements[0].action,'invoice');
  assert.equal(movements[0].data.folio,'folio-key');assert.equal(movements[0].data.invoice_acceptance,'review-proof');
  assert.equal(dialogs[0].hidden,true);assert.equal(review.hidden,true);assert.equal(messages[0].title,'Factura emitida');
  assert.match(messages[0].message,/Total facturado.*0.00 NIO/);assert.match(messages[0].message,/estancia permanece activa/);
});
test('a lost response keeps the invoice confirmation open and retries with exactly the same identity',async()=>{
  const {desk,dialogs,movements}=fixture();await desk.action_invoice('stay-key');await dialogs[0].submit({folio:'folio-key'},dialogs[0]);
  desk.fail=true;const review=dialogs[1];await assert.rejects(review.submit({},review),/response lost/);
  assert.equal(review.hidden,false);assert.equal(dialogs[0].hidden,false);
  await review.submit({},review);assert.deepEqual(movements[0],movements[1]);
});
test('unauthorized staff cannot quote and an already billed account never opens an emission confirmation',async()=>{
  const denied=fixture();denied.desk.permission=false;await denied.desk.action_invoice('stay-key');assert.equal(denied.calls.length,0);assert.equal(denied.dialogs.length,0);
  const empty=fixture();empty.desk.quote={ready:false};await empty.desk.action_invoice('stay-key');await empty.dialogs[0].submit({folio:'folio-key'},empty.dialogs[0]);
  assert.equal(empty.dialogs.length,1);assert.equal(empty.movements.length,0);assert.match(empty.messages[0],/no tiene cargos nuevos/);
});
