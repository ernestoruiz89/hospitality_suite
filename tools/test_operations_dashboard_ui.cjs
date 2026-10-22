const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
function fixture(route){
  class Desk {
    constructor(){this.route=route;this.property='hotel';this.data={rooms:[{name:'R1',room_number:'101'}],properties:[{name:'hotel'}]};this.prop={currency:'USD'};}
    button(action,label,id=''){return `<button data-act="${escape(action)}" data-id="${escape(id)}">${escape(label)}</button>`;}
    table(headers,rows){return `<table>${headers.map(escape).join('')} ${rows.map(row=>row.join(' | ')).join('\n')}</table>`;}
    empty(label){return `<p>${escape(label)}</p>`;}
    badge(value){return `<b>${escape(value)}</b>`;}
    roomName(name){return name==='R1'?'101':name;}
    date(value){return value||'—';}
    amount(value,currency){return `${value} ${currency||'USD'}`;}
    allowed(){return true;}
  }
  const context={window:{hospitality_suite:{Desk,ui_storage:{setItem(){}}}},frappe:{utils:{escape_html:escape}},
    __:(value,args)=>args?value.replace(/\{(\d+)\}/g,(_,i)=>args[i]):value};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_operations_dashboard.js'),'utf8'),context);
  const desk=new Desk(),target={value:'',html(value){this.value=value;return this;}},el={0:{isConnected:true},find(){return target;}};
  return {desk,target,el};
}

test('ticket list escapes user text and shows responsibility and deadlines',async()=>{
  const {desk,target,el}=fixture('hospitality-tickets');
  desk.call=async()=>({now:'2026-10-22 12:00:00',total:1,has_more:false,assignees:[{name:'staff',full_name:'Ana'}],
    rows:[{name:'T1',room:'R1',subject:'<img src=x onerror=alert(1)>',category:'Complaint',priority:'High',status:'Open',assigned_to:'staff',due_at:'2026-10-22 11:00:00'}]});
  await desk.load_tickets(el);
  assert.match(target.value,/&lt;img src=x onerror=alert\(1\)&gt;/);
  assert(!target.value.includes('<img src=x'));
  assert.match(target.value,/Ana/);
  assert.match(target.value,/Vencido/);
  assert.match(target.value,/data-act="ticket_step"/);
});

test('portfolio preserves currency buckets and ignores a stale property response',async()=>{
  const {desk,target,el}=fixture('hospitality-portfolio');
  const response={counts:{properties:2,rooms:10,occupied:5,open_tickets:2,overdue_tickets:1},
    totals:{USD:{receivable:'20',unbilled:'5',overdue:'1'},NIO:{receivable:'700',unbilled:'0',overdue:'20'}},
    properties:[{property:'hotel',property_name:'Hotel <A>',mode:'Hotel',business_date:'2026-10-22',occupied:5,rooms:10,blocked:0,cleaning:1,maintenance:0,tickets:2,overdue_tickets:1}]};
  desk.call=async()=>response;
  await desk.load_portfolio(el);
  assert.match(target.value,/20 USD/);
  assert.match(target.value,/700 NIO/);
  assert.match(target.value,/Hotel &lt;A&gt;/);
  let resolve;desk.call=()=>new Promise(done=>{resolve=done;});
  const pending=desk.load_portfolio(el);
  desk.property='other';resolve(response);await pending;
  assert.match(target.value,/Hotel &lt;A&gt;/);
  assert.equal((target.value.match(/700 NIO/g)||[]).length,1);
});

test('credit and health views escape labels and expose actionable status',async()=>{
  const credit=fixture('hospitality-credit');
  credit.desk.call=async()=>({currency:'USD',total:1,rows:[{party:'P1',customer:'C1',customer_name:'<Empresa>',status:'Overdue',limit:'100',receivable:'70',unbilled:'10',overdue:'20',available:'20',credit_days:30}]});
  await credit.desk.load_credit(credit.el);
  assert.match(credit.target.value,/&lt;Empresa&gt;/);
  assert.match(credit.target.value,/Vencido/);
  assert.match(credit.target.value,/data-act="credit_edit"/);
  const health=fixture('hospitality-health');
  health.desk.call=async()=>({checked_at:'2026-10-22 10:00',status:'Warning',checks:[{title:'Disco',status:'OK',detail:'86% libre'}]});
  await health.desk.load_health(health.el);
  assert.match(health.target.value,/Atención/);
  assert.match(health.target.value,/Correcto/);
});
