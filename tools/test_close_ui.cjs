const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(blocked=false){
  const commands=[];
  const period={currency:'NIO',time_zone:'America/Managua',financial:{posting_date:'2026-10-19',business_date:'2026-10-18',currencies:[{currency:'NIO',payments:'100.00',advances:'20.00'}],sources:{unattributed_movements:[]}}};
  class Desk{
    constructor(){this.prop={time_zone:'America/Managua'};this.data={close_financial_groups:[{title:'Movimientos',metrics:[{key:'payments',label:'Cobros'},{key:'advances',label:'Anticipos'}]}],closes:[{name:'saved',business_date:'2026-10-18',summary:JSON.stringify(period),blockers:'[]'}]};}
    allowed(){return true;}
    table(headers,rows){return rows.flat().join('|');}empty(message){return message;}
    async mutate(action,data,key){commands.push({action,data,key});return {period,blockers:blocked?[{type:'Turnos sin cerrar',documents:['shift']}]:[],review_acceptance:'review-proof'};}
    async dialog(title,fields,submit){const button={disabled:false,prop(k,v){this[k]=v;return this;}};return {title,fields,submit,get_primary_btn:()=>button,hide(){}};}
  }
  const __=(text,args)=>args?text.replace('{0}',args[0]):text;
  const context={window:{hospitality_suite:{Desk}},__,frappe:{utils:{escape_html:value=>String(value).replaceAll('<','&lt;'),get_random:()=> 'command-key'},msgprint(){}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_close.js'),'utf8'),context);
  return {desk:new Desk(),commands,period};
}
test('historical close reads only the saved financial values, with distinct date bases',async()=>{
  const {desk,commands}=fixture();desk.mutate=async()=>{throw new Error('Saved snapshots must not be re-summed');};
  const dialog=await desk.action_view_close('saved');
  assert.match(dialog.fields[0].options,/2026-10-19/);assert.match(dialog.fields[0].options,/2026-10-18/);
  assert.match(dialog.fields[0].options,/Cobros\|100.00\|NIO\|Anticipos\|20.00\|NIO/);
  assert.equal(commands.length,0);
});
test('close confirmation carries the reviewed digest and blockers disable confirmation',async()=>{
  const {desk,commands}=fixture();const dialog=await desk.action_daily_close();
  await dialog.submit({},dialog);
  assert.equal(commands.length,2);assert.equal(commands[1].data.confirm,true);
  assert.equal(commands[1].data.review_acceptance,'review-proof');assert.equal(commands[1].key,'command-key');
  const other=fixture(true),blocked=await other.desk.action_daily_close();
  assert.equal(blocked.get_primary_btn().disabled,true);
});
test('close groups with amounts open while zero groups retain expandable details',()=>{
  const {desk,period}=fixture();
  desk.data.close_financial_groups.push({title:'Sin movimientos',metrics:[{key:'refunds',label:'Devoluciones'}]});
  period.financial.currencies[0].refunds='0.00';
  const html=desk.close_summary_html(period);
  assert.match(html,/<details class="hs-close-group" open><summary>Movimientos<\/summary>/);
  assert.match(html,/<details class="hs-close-group"><summary>Sin movimientos<\/summary>Devoluciones\|0.00\|NIO<\/details>/);
  assert.match(html,/100.00/);assert.match(html,/20.00/);
});
