const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
test('cashier identifies native POS cash, refunds and missing attribution without exposing raw shift IDs',()=>{
  class Desk{
    constructor(){this.data={shifts:[{name:'opaque-shift',opened_at:'19/10 10:00',cashier:'Caja <uno>'}],native_pos:[{name:'INV-1',shift:'opaque-shift',creation:'19/10 11:00',is_cash:true,mapped:true,amount:'60',currency:'NIO'},{name:'INV-2',creation:'19/10 12:00',is_cash:false,mapped:false,amount:'-20',currency:'USD'},{name:'JV<cash>',doctype:'Journal Entry',shift:'opaque-shift',creation:'19/10 13:00',is_cash:true,mapped:true,amount:'-30',currency:'NIO'}]};}
    render_cashier(el){el.append('Original');}date(value){return value;}amount(value,currency){return value+' '+currency;}invoiceLink(name){return name;}table(headers,rows){return rows.flat().join('|');}
  }
  const context={window:{hospitality_suite:{Desk}},__:value=>value,frappe:{utils:{escape_html:value=>String(value).replaceAll('<','&lt;').replaceAll('>','&gt;')}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_pos.js'),'utf8'),context);
  let html='';new Desk().render_cashier({append:value=>html+=value});
  assert.match(html,/Original/);assert.match(html,/Cobros POS de ERPNext/);assert.match(html,/netos de vuelto y devoluciones/);
  assert.match(html,/Caja &lt;uno&gt;/);assert.match(html,/Efectivo\|60 NIO\|Contabilizado/);assert.match(html,/-20 USD\|Revisar turno/);
  assert.doesNotMatch(html,/opaque-shift|Caja <uno>/);
  assert.match(html,/doctype=Journal%20Entry/);assert.match(html,/JV%3Ccash%3E/);assert.match(html,/JV&lt;cash&gt;/);
});
