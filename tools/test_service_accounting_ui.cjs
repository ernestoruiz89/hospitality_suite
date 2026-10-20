const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
test('service accounting uses scoped native links and writes only reviewed accounting fields',async()=>{
  const writes=[];
  const config={modified:'saved-version',company:'Company A',defaults:{income_account:'Income A',expense_account:null,cost_center:'Center A'},services:[{item:'sku',item_name:'Agua <uno>',income_account:'Income B'}]};
  class Desk{
    table(headers,rows){return rows.flat().join('|');}
    render_setup(){} async call(){return config;}async mutate(...args){writes.push(args);}
    async dialog(title,fields,submit){return {title,fields,submit,hide(){this.hidden=true;}};}
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_service_accounting.js'),'utf8'),{window:{hospitality_suite:{Desk}},__:value=>value,frappe:{utils:{get_random:()=> 'stable-key',escape_html:value=>String(value).replaceAll('<','&lt;').replaceAll('>','&gt;')}}});
  const desk=new Desk(),dialog=await desk.action_service_accounting();
  const income=dialog.fields.find(row=>row.fieldname==='income_account');
  assert.equal(income.default,'Income A');assert.deepEqual(JSON.parse(JSON.stringify(income.get_query().filters)),{company:'Company A',is_group:0,disabled:0,root_type:'Income'});
  assert.match(dialog.fields[0].options,/notas de crédito.*factura original/);
  assert.match(dialog.fields.find(row=>row.fieldname==='current').options,/Agua &lt;uno&gt;/);
  await dialog.submit({income_account:'Income A',cost_center:'Center A',services:[{name:'opaque-row',item:'sku',item_name:'Edited label',income_account:'Income B',company:'Other'}]},dialog);
  assert.equal(writes[0][0],'service_accounting');assert.equal(writes[0][2],'stable-key');
  const data=JSON.parse(JSON.stringify(writes[0][1]));
  assert.equal(data.modified,'saved-version');assert.deepEqual(data.services,[{item:'sku',income_account:'Income B',expense_account:null,cost_center:null}]);
  assert.equal(data.defaults.expense_account,null);assert.equal(dialog.hidden,true);
});
