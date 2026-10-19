const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(policies,approved=false){
  class Desk{constructor(){this.data={payment_policies:policies};}allowed(){return approved;}async dialog(title,fields){return fields;}render_setup(){}}
  const context={window:{hospitality_suite:{Desk}},__:(text,args)=>args?text.replace('{0}',args[0]):text,frappe:{utils:{escape_html:String}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_policies.js'),'utf8'),context);
  const desk=new Desk();
  return async()=>{const fields=await desk.dialog('Cash',[{fieldname:'kind',fieldtype:'Select',options:['Payment','Advance','Guarantee','Refund','Guarantee Refund'].map(value=>({value,label:value}))}]);return fields[0].options;};
}
test('disabled receipts keep existing-fund refunds available and wire values stable',async()=>{
  const options=await fixture({Advance:'Disabled',Guarantee:'Disabled'})();
  assert.deepEqual(Array.from(options,o=>o.value),['Payment','Refund','Guarantee Refund']);
  const legacy=await fixture(undefined)();assert.equal(legacy.length,5);
});
test('approval options explain the restriction and remain available to an approver',async()=>{
  const restricted=await fixture({Advance:'Approval',Guarantee:'Manual'})();
  assert.equal(restricted.find(o=>o.value==='Advance').disabled,true);
  assert.match(restricted.find(o=>o.value==='Advance').label,/requiere gerencia/);
  assert.equal(restricted.find(o=>o.value==='Guarantee').disabled,undefined);
  const authorized=await fixture({Advance:'Approval'},true)();
  assert.equal(authorized.find(o=>o.value==='Advance').disabled,undefined);
});
