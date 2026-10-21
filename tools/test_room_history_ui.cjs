const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
function fixture(){
  const requests=[],dialogs=[];
  class Element{
    constructor(){this.markup='';this.attributes={};this.handlers={};}
    html(value){if(value===undefined)return this.markup;this.markup=value;return this;}
    attr(values,value){if(typeof values==='string')this.attributes[values]=value;else Object.assign(this.attributes,values);return this;}
    addClass(){return this;}
    on(events,selector,fn){this.handlers[selector]=fn;return this;}
    one(event,fn){this.hidden=fn;return this;}
  }
  class Desk{
    constructor(){this.property='hotel';this.prop={time_zone:'America/Managua'};this.data={property_now:'2026-10-20T10:00:00-06:00',rooms:[]};this.permissions=new Set(['stay']);}
    allowed(action){return this.permissions.has(action)}
    render_reception(){}roomName(){return '<H101>'}date(value){return value}
    table(headers,rows){return '<table>'+rows.map(row=>'<tr>'+row.map(cell=>'<td>'+cell+'</td>').join('')+'</tr>').join('')+'</table>'}
    call(method,args){return new Promise((resolve,reject)=>requests.push({method,args,resolve,reject}));}
    async dialog(title,fields,submit,primary,size){
      const target=new Element(),d={title,fields,submit,primary,size,$wrapper:new Element(),fields_dict:{_history_result:{$wrapper:target}},target};dialogs.push(d);return d;
    }
  }
  const escape=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const translate=(s,args=[])=>s.replace(/\{(\d+)\}/g,(_,i)=>args[i]);
  const moment=day=>{const d=new Date(day+'T00:00:00Z');return {add(n){d.setUTCDate(d.getUTCDate()+n);return this},subtract(n){d.setUTCDate(d.getUTCDate()-n);return this},format(){return d.toISOString().slice(0,10)+'T00:00:00'}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_room_history.js'),'utf8'),{window:{hospitality_suite:{Desk}},frappe:{utils:{escape_html:escape}},__:translate,moment});
  const desk=new Desk(),values={starts_at:'2026-10-13T00:00:00',ends_at:'2026-10-21T00:00:00',view:'activity'};
  const response=(index=0,extra={})=>({...requests[index].args,property:requests[index].args.property_name,time_zone:'America/Managua',rows:[],total:0,page_length:25,has_more:false,...extra});
  return {desk,requests,dialogs,values,response,flush:()=>new Promise(resolve=>setImmediate(resolve))};
}
test('history presents explicit dated filters in the property zone, without requesting or writing on open',async()=>{
  const f=fixture(),d=await f.desk.action_room_history('internal-room');assert.equal(f.requests.length,0);assert.match(d.title,/H101/);assert.equal(d.primary,'Consultar historial');
  const fields=Object.fromEntries(d.fields.map(df=>[df.fieldname,df]));assert.equal(fields.starts_at.default,'2026-10-13T00:00:00');assert.equal(fields.ends_at.default,'2026-10-21T00:00:00');assert.match(fields.starts_at.label,/America\/Managua/);assert.match(fields.ends_at.label,/sin incluir/);assert.equal(fields.view.options.length,4);assert.match(fields._history_result.options,/Reservas/);
});
test('cleaning and maintenance roles cannot open room history; reporting roles can',async()=>{
  const f=fixture();f.desk.permissions.clear();assert.equal(await f.desk.action_room_history('room'),undefined);assert.equal(f.dialogs.length,0);f.desk.permissions.add('report');assert.ok(await f.desk.action_room_history('room'));
});
test('timeline escapes all recorded values and hides technical identities behind readable detail summaries',()=>{
  const f=fixture(),html=f.desk.room_history_rows({rows:[{id:'secret-id',kind:'change',title:'<Cambio>',occurred_at:'<fecha>',actor:'<usuario>',note:'<nota>',relation:'related',fields:[{label:'<Piso>',before:'<antes>',after:'<después>'}]}]});
  for(const text of ['Cambio','fecha','usuario','nota','Piso','antes','después'])assert.ok(html.includes('&lt;'+text+'&gt;'));assert.doesNotMatch(html,/secret-id/);assert.match(html,/Ver valores registrados \(1\)/);assert.match(html,/no pudo reconstruirse/);
  assert.match(f.desk.room_history_rows({rows:[]}),/No hay movimientos/);assert.match(f.desk.room_history_rows({rows:[{kind:'period',title:'Bloqueo',starts_at:'inicio',ends_at:null}]}),/Sin fecha final registrada/);
});
test('query shows loading, prevents duplicate requests and recovers from a retryable error',async()=>{
  const f=fixture(),d=await f.desk.action_room_history('room'),pending=d.submit(f.values,d);assert.equal(d.target.attributes['aria-busy'],'true');assert.match(d.target.markup,/Consultando/);await d.submit(f.values,d);assert.equal(f.requests.length,1);
  f.requests[0].reject(Error('network'));await pending;assert.match(d.target.markup,/role="alert"/);assert.match(d.target.markup,/reintentar/);assert.equal(d.target.attributes['aria-busy'],'false');
  const retry=d.submit(f.values,d);f.requests[1].resolve(f.response(1));await retry;assert.match(d.target.markup,/No hay movimientos/);
});
test('editing dates or view invalidates outstanding success and error replies',async()=>{
  for(const failure of [false,true]){const f=fixture(),d=await f.desk.action_room_history('room'),pending=d.submit(f.values,d);d.$wrapper.handlers['input,select']();const current=d.target.markup;
    if(failure)f.requests[0].reject(Error('old'));else f.requests[0].resolve(f.response(0));await pending;assert.equal(d.target.markup,current);assert.match(current,/Fechas o vista cambiadas/);
  }
});
test('closing a dialog invalidates its request and a newly opened history keeps its own results',async()=>{
  const f=fixture(),old=await f.desk.action_room_history('room'),first=old.submit(f.values,old);old.$wrapper.hidden();
  const next=await f.desk.action_room_history('other-room'),second=next.submit(f.values,next);f.requests[1].resolve(f.response(1));await second;const current=next.target.markup;f.requests[0].resolve(f.response(0));await first;assert.equal(next.target.markup,current);assert.match(old.target.markup,/Consultando/);
});
test('pagination retains accepted dates and sends zero when returning to the first page',async()=>{
  const f=fixture(),d=await f.desk.action_room_history('room'),first=d.submit(f.values,d);f.requests[0].resolve(f.response(0,{total:51,has_more:true}));await first;
  const next=d.$wrapper.handlers['[data-history-offset]']({currentTarget:{dataset:{historyOffset:'25'}}});assert.equal(f.requests[1].args.offset,25);assert.equal(f.requests[1].args.starts_at,f.values.starts_at);f.requests[1].resolve(f.response(1,{total:51,has_more:true}));await next;
  const back=d.$wrapper.handlers['[data-history-offset]']({currentTarget:{dataset:{historyOffset:'0'}}});assert.equal(f.requests[2].args.offset,0);f.requests[2].resolve(f.response(2));await back;
  d.$wrapper.handlers['input,select']();await d.$wrapper.handlers['[data-history-offset]']({currentTarget:{dataset:{historyOffset:'25'}}});assert.equal(f.requests.length,3);
});
test('property changes block new queries and discard old replies without showing foreign history',async()=>{
  const f=fixture(),d=await f.desk.action_room_history('room'),pending=d.submit(f.values,d);f.desk.property='other';f.requests[0].resolve(f.response(0,{rows:[{title:'Foreign history'}]}));await pending;assert.doesNotMatch(d.target.markup,/Foreign history/);await d.submit(f.values,d);assert.equal(f.requests.length,1);assert.match(d.target.markup,/establecimiento cambió/);
});
test('mismatched room, view, property, timezone or offset is rejected as an inline query error',async()=>{
  for(const extra of [{room:'wrong'},{view:'changes'},{property:'wrong'},{time_zone:'Europe/Madrid'},{offset:25}]){const f=fixture(),d=await f.desk.action_room_history('room'),pending=d.submit(f.values,d);f.requests[0].resolve(f.response(0,extra));await pending;assert.match(d.target.markup,/No se pudo consultar/);}
});
test('invalid and inverted dates are rejected inline before a server request and a valid retry succeeds',async()=>{
  const f=fixture(),d=await f.desk.action_room_history('room');
  for(const changes of [{starts_at:''},{ends_at:'invalid'},{ends_at:f.values.starts_at},{ends_at:'2026-10-01T00:00:00'}]){
    await d.submit({...f.values,...changes},d);assert.match(d.target.markup,/fecha final debe ser posterior/);assert.equal(f.requests.length,0);
  }
  const retry=d.submit(f.values,d);f.requests[0].resolve(f.response(0));await retry;assert.match(d.target.markup,/No hay movimientos/);
});
