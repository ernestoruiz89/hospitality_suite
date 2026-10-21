const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function fixture(){
  const opened=[],appended=[];
  class Desk{
    constructor(){this.data={cleaning:[{name:'TASK/&1'}],print_formats:{}};this.permission=true;}
    allowed(){return this.permission;}
    button(action,label,id){return `<button data-action="${action}" data-id="${id}">${label}</button>`;}
    async action_detail(){return {$wrapper:{addClass(){},find(){return{append(value){appended.push(value);}};}}};}
  }
  const escape=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const context={window:{hospitality_suite:{Desk},open:(...args)=>opened.push(args)},__:value=>value,frappe:{utils:{escape_html:escape}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_workflows.js'),'utf8'),context);
  return {desk:new Desk(),opened,appended};
}
test('receipt and invoice links honor configured formats, encode identifiers and retain secure new-tab attributes',()=>{
  const {desk}=fixture();desk.data.print_formats={invoice:'Factura local & especial',receipt:'Recibo local "A"'};
  for(const [link,format,type] of [[desk.receiptLink('PAY/&1'),'Recibo local "A"','HS Payment'],[desk.invoiceLink('INV/&1'),'Factura local & especial','Sales Invoice']]){
    assert.match(link,/target="_blank" rel="noopener"/);
    const url=new URL(link.match(/href="([^"]+)/)[1],'http://localhost');
    assert.equal(url.searchParams.get('format'),format);assert.equal(url.searchParams.get('doctype'),type);assert.match(url.searchParams.get('name'),/\/&1$/);
  }
  desk.data.print_formats={};assert.match(desk.receiptLink('PAY-1'),/format=HS%20Recibo/);assert.equal(desk.receiptLink(''),'—');
});
test('stay panel offers account and guest-registration printing with guest permission',async()=>{
  const {desk,appended}=fixture();await desk.action_detail('STAY-1');assert.match(appended[0],/Imprimir cuenta/);assert.match(appended[0],/Imprimir registro de huésped/);
  desk.permission=false;await desk.action_detail('STAY-1');assert.match(appended[1],/Imprimir cuenta/);assert.doesNotMatch(appended[1],/print_registration/);
});
test('registration and cleaning actions open their real native formats without a save or state change',()=>{
  const {desk,opened}=fixture(),before=JSON.stringify(desk.data);
  desk.action_print_registration('STAY/&1');desk.action_print_cleaning('TASK/&1');
  for(const [i,doctype,format] of [[0,'HS Stay','HS Registro de huésped'],[1,'HS Cleaning Task','HS Orden de limpieza']]){
    const [url,target,features]=opened[i],parsed=new URL(url,'http://localhost');assert.equal(parsed.searchParams.get('doctype'),doctype);assert.equal(parsed.searchParams.get('format'),format);assert.equal(target,'_blank');assert.equal(features,'noopener');
  }
  desk.action_print_cleaning('not-in-this-page');desk.permission=false;desk.action_print_registration('STAY/&1');assert.equal(opened.length,2);assert.equal(JSON.stringify(desk.data),before);
});
test('cashier recent movements retain the accounting reference and offer the configured receipt after reloading',()=>{
  const suite={},escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const context={window:{hospitality_suite:suite},hospitality_suite:suite,__:(value)=>value,frappe:{utils:{escape_html:escape}}};
  for(const name of ['hospitality.js','hospitality_workflows.js'])vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js',name),'utf8'),context);
  const desk=Object.create(suite.Desk.prototype);desk.data={payments:[{name:'PAY/&1',kind:'Payment',amount:500,currency:'NIO',status:'Posted',payment_entry:'PE-00001'}],shifts:[],print_formats:{receipt:'Recibo de la propiedad'}};
  desk.button=()=>'';desk.amount=(value,currency)=>value+' '+currency;let html='';
  desk.render_cashier({html(value){html=value;}});
  assert.match(html,/PE-00001/);assert.match(html,/Ver recibo/);assert.match(html,/format=Recibo%20de%20la%20propiedad/);assert.match(html,/name=PAY%2F%261/);
});
