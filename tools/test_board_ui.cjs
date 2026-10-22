const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(){
  const nodes=new Map();
  const find=key=>{if(!nodes.has(key))nodes.set(key,{htmlValue:'',attrs:{},html(v){this.htmlValue=v;return this;},empty(){this.htmlValue='';return this;},attr(k,v){this.attrs[k]=v;return this;},text(v){this.textValue=v;return this;},toggle(v){this.visible=v;return this;},each(){return this;}});return nodes.get(key);};
  class Desk{
    constructor(){this.property='hotel';}
    table(headers,rows){return headers.join('|')+'\n'+rows.map(row=>row.join('|')).join('\n');}
    button(action,label,id){return `<button data-act="${action}" data-id="${id}">${label}</button>`;}
    badge(text){return text;}
    date(value){return value||'—';}
    amount(value,currency){return `${value} ${currency}`;}
    empty(text){return text;}
  }
  const context={window:{hospitality_suite:{Desk}},frappe:{utils:{escape_html:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}},
    __:(text,args)=>args?text.replace(/\{(\d+)\}/g,(_,i)=>args[i]):text,$:value=>value};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_board.js'),'utf8'),context);
  return{desk:new Desk(),el:{find},nodes};
}
function response(view='hosted',rows=[]){return{property:'hotel',view,date:'2026-10-20',counts:{hosted:1,arrivals:2,departures:0,accounts:1},rows,total:rows.length,offset:0,page_length:25,has_more:false,server_time:'2026-10-20 12:00:00'};}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}

test('a future reservation has its own arrival description without claiming the room is occupied',()=>{
  const {desk}=fixture(),next={starts_at:'2026-10-23 14:00:00',status:'Hold'};
  const html=desk.roomTiming(null,next);
  assert.match(html,/Próxima llegada pendiente/);assert.match(html,/Retención temporal · aún sin entrada/);assert(!html.includes('Salida prevista'));assert(!html.includes('Alojado'));
  const both=desk.roomTiming({starts_at:'2026-10-20 14:00:00',ends_at:'2026-10-21 12:00:00'},next);
  assert.match(both,/Entrada prevista/);assert.match(both,/Salida prevista/);assert.match(both,/Próxima llegada/);
});
test('operational rows use human labels and escape data while action identities remain stable',()=>{
  const {desk}=fixture();
  const arrivals=desk.boardRows(response('arrivals',[{room_label:'Por asignar',category_label:'<Doble>',guest_label:'<Ana>',customer_label:'Empresa',starts_at:'2026-10-20 14:00:00',status:'Confirmed',booking:'BOOK-KEY'}]));
  assert.match(arrivals,/&lt;Ana&gt;/);assert.match(arrivals,/&lt;Doble&gt;/);assert(!arrivals.includes('<Ana>'));assert.match(arrivals,/Gestionar llegada/);assert.match(arrivals,/data-id="BOOK-KEY"/);
  assert.match(arrivals,/Sin habitación asignada/);assert.match(arrivals,/Sin cuenta abierta/);
  const hosted=desk.boardRows(response('hosted',[{name:'STAY-KEY',room_label:'H101',guest_label:'Ana',starts_at:'2026-10-20 14:00:00',ends_at:'2026-10-21 11:00:00',status:'Active',cleaning_status:'Dirty',shared_account:true,account_balances:[{currency:'NIO',outstanding:'3000.00'}]}]));
  assert.match(hosted,/Dirty/);assert.match(hosted,/3000.00 NIO/);assert.match(hosted,/Cuenta compartida/);
  const accounts=desk.boardRows(response('accounts',[{label:'Principal',customer_label:'Empresa',room_label:'H101, H102',shared:true,currency:'NIO',balance:{outstanding:'0.00'},detail_stay:'STAY-KEY'}]));
  assert.match(accounts,/Grupo · H101, H102/);assert.match(accounts,/0.00 NIO/);assert.match(accounts,/data-id="STAY-KEY"/);
});
test('an older board success or failure cannot replace a newer selection or clear its busy state',async()=>{
  const {desk,el,nodes}=fixture(),old=deferred(),fresh=deferred();let n=0;desk.call=()=>++n===1?old.promise:fresh.promise;
  const one=desk.loadBoard(el,{view:'hosted',date:'2026-10-20',offset:0});
  const two=desk.loadBoard(el,{view:'arrivals',date:'2026-10-20',offset:0});
  old.resolve(response('hosted'));await one;
  assert.equal(nodes.get('.hs-board-results').attrs['aria-busy'],'true');
  fresh.resolve(response('arrivals'));await two;
  assert.equal(nodes.get('.hs-board-results').htmlValue,'No hay llegadas pendientes hasta esa fecha.');
  assert.equal(nodes.get('.hs-board-results').attrs['aria-busy'],'false');
  const late=deferred();desk.call=()=>late.promise;const pending=desk.loadBoard(el,{view:'accounts',date:'2026-10-20',offset:0});
  desk.property='other';const before=nodes.get('.hs-board-results').htmlValue;late.reject(Error('late network failure'));await pending;
  assert.equal(nodes.get('.hs-board-results').htmlValue,before);
});
test('pagination preserves zero and context mismatches show an actionable error instead of another property data',async()=>{
  const {desk,el,nodes}=fixture();desk.call=async()=>({...response('accounts'),total:51,offset:25,page_length:25,has_more:true});
  await desk.loadBoard(el,{view:'accounts',date:'2026-10-20',offset:25});
  const html=nodes.get('.hs-board-pagination').htmlValue;
  assert.match(html,/26–50 de 51/);assert.match(html,/data-board-offset="0"/);assert.match(html,/data-board-offset="50"/);
  desk.call=async()=>({...response('hosted'),property:'other'});await desk.loadBoard(el,{view:'hosted',date:'2026-10-20',offset:0});
  assert.match(nodes.get('.hs-board-results').htmlValue,/No se pudo consultar esta vista/);assert.match(nodes.get('.hs-board-results').htmlValue,/Actualizar/);
});
