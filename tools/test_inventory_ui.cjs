const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function fixture(){
  const requests=[],mutations=[],alerts=[];
  class Element{
    constructor(){this.markup='';this.attributes={};this.children=new Map();this.events={};}
    appendTo(parent){parent.section=this;return this;}
    html(value){if(value===undefined)return this.markup;this.markup=value;return this;}
    attr(key,value){this.attributes[key]=value;return this;}
    find(selector){if(!this.children.has(selector))this.children.set(selector,new Element());return this.children.get(selector);}
    on(event,...args){this.events[event]=args.at(-1);return this;}
  }
  class Desk{
    constructor(){this.property='hotel';this.data={default_warehouse:'main',warehouses:[{name:'main',warehouse_name:'Principal'},{name:'floor',warehouse_name:'Piso'}],services:[]};this.approver=true;}
    render_services(){}
    table(headers,rows){return JSON.stringify({headers,rows});}
    call(method,args){return new Promise((resolve,reject)=>requests.push({method,args,resolve,reject}));}
    allowed(){return this.approver;}
    itemName(){return '<Agua>'}
    async mutate(action,values,key){mutations.push({action,values,key});}
    async action_return_direct_sale(id){this.directReturn=id;return 'direct';}
    async dialog(title,fields,submit,label){const values=Object.fromEntries(fields.map(df=>[df.fieldname,df.default])),button={label,text(value){this.label=value;}};
      const d={title,fields,values,submit,hidden:false,fields_dict:Object.fromEntries(fields.map(df=>[df.fieldname,{df}])),get_value(name){return values[name]},set_df_property(name,key,value){this.fields_dict[name].df[key]=value},get_primary_btn(){return button},hide(){this.hidden=true}};this.lastDialog=d;return d;}
  }
  const escape=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_inventory.js'),'utf8'),{window:{hospitality_suite:{Desk}},frappe:{utils:{escape_html:escape,get_random:()=> 'original-request'},msgprint:s=>alerts.push(s)},__:s=>s,$:()=>new Element()});
  const desk=new Desk(),el=new Element();desk.render_services(el);
  return {desk,el,requests,mutations,alerts,Element,results:()=>desk._inventoryView.section.find('[data-hs-inventory-results]'),flush:()=>new Promise(resolve=>setImmediate(resolve))};
}
test('inventory shows loading, scoped names, zero stock, assets and an explicit replenishment alert',async()=>{
  const f=fixture();assert.match(f.results().markup,/Consultando/);assert.equal(f.results().attributes['aria-busy'],'true');assert.equal(f.requests[0].args.warehouse_name,'main');
  f.requests[0].resolve({warehouse:'main',items:[{item_name:'<Agua>',purpose:'Cleaning',actual_qty:0,minimum:4,reorder_quantity:8,needs_restock:true},{item_name:'Equipo',purpose:'Asset',stock_managed:false,actual_qty:null}]});await f.flush();
  assert.match(f.results().markup,/&lt;Agua&gt;/);assert.match(f.results().markup,/Consumible de limpieza/);assert.match(f.results().markup,/Reponer/);assert.match(f.results().markup,/Registro de activos/);assert.equal(f.results().attributes['aria-busy'],'false');assert.equal(f.mutations.length,0);
});
test('older warehouse successes and errors cannot replace the selected warehouse',async()=>{
  const f=fixture(),view=f.desk._inventoryView;view.warehouse='floor';const latest=f.desk.load_inventory_status(view);
  f.requests[1].resolve({warehouse:'floor',items:[{item_name:'Piso actual',purpose:'Linen',actual_qty:2}]});await latest;const expected=f.results().markup;
  f.requests[0].reject(Error('old network failure'));await f.flush();assert.equal(f.results().markup,expected);assert.match(expected,/Piso actual/);
  const old=f.desk.load_inventory_status(view);view.warehouse='main';const newer=f.desk.load_inventory_status(view);f.requests[3].resolve({warehouse:'main',items:[]});await newer;f.requests[2].resolve({warehouse:'floor',items:[{item_name:'Obsoleto'}]});await old;
  assert.doesNotMatch(f.results().markup,/Obsoleto/);assert.match(f.results().markup,/No hay existencias/);
});
test('property changes and a replaced Page discard pending replies without clearing the new busy state',async()=>{
  const f=fixture(),old=f.desk._inventoryView,previous=f.results();f.desk.property='other';f.requests[0].resolve({warehouse:'main',items:[{item_name:'Private old stock'}]});await f.flush();assert.doesNotMatch(previous.markup,/Private/);
  f.desk.property='hotel';f.desk.render_services(new f.Element());const current=f.results();f.requests[1].resolve({warehouse:'main',items:[]});await f.flush();assert.match(current.markup,/No hay existencias/);
  assert.notEqual(f.desk._inventoryView,old);
});
test('context mismatches and network failures offer retry; empty and unconfigured locations remain distinct',async()=>{
  const f=fixture();f.requests[0].resolve({warehouse:'foreign',items:[{item_name:'Must not render'}]});await f.flush();assert.match(f.results().markup,/Reintentar consulta/);assert.doesNotMatch(f.results().markup,/Must not render/);
  const retry=f.desk.load_inventory_status(f.desk._inventoryView);f.requests[1].reject(Error('offline'));await retry;assert.match(f.results().markup,/role="alert"/);
  f.desk.data.warehouses=[];f.desk.data.default_warehouse=null;f.desk.render_services(new f.Element());assert.match(f.results().markup,/Configure un almacén/);assert.equal(f.requests.length,2);
});
test('service actions follow the current state and show reason only for cancellation or return',async()=>{
  const f=fixture();f.desk.data.services=[{name:'service',stay:'stay',item:'water',quantity:2,status:'In Progress',modified:'v1'}];const d=await f.desk.action_service_status('service');
  assert.deepEqual(Array.from(d.fields_dict.status.df.options,x=>x.value),['Delivered','Cancelled']);assert.equal(d.get_primary_btn().label,'Confirmar entrega');assert.equal(d.fields_dict.reason.df.hidden,true);assert.match(d.fields[0].options,/&lt;Agua&gt;/);
  d.values.status='Cancelled';d.fields_dict.status.df.onchange();assert.equal(d.get_primary_btn().label,'Cancelar solicitud');assert.equal(d.fields_dict.reason.df.hidden,false);assert.equal(d.fields_dict.reason.df.reqd,false);
  await d.submit({status:'Cancelled',reason:'Pedido cancelado'},d);assert.equal(f.mutations[0].values.modified,'v1');assert.equal(f.mutations[0].key,'original-request');assert.equal(d.hidden,true);
  f.desk.data.services[0].status='Delivered';const returned=await f.desk.action_service_status('service');assert.equal(returned.fields_dict.reason.df.reqd,true);assert.equal(returned.get_primary_btn().label,'Confirmar devolución');
});
test('finished or missing services and unauthorized returns never submit; direct sale keeps its native return flow',async()=>{
  const f=fixture();f.desk.data.services=[{name:'service',status:'Delivered',stay:'stay'}];f.desk.approver=false;await f.desk.action_service_status('service');assert.match(f.alerts[0],/autorización/);assert.equal(f.desk.lastDialog,undefined);
  f.desk.approver=true;f.desk.data.services[0].status='Cancelled';await f.desk.action_service_status('service');await f.desk.action_service_status('missing');assert.equal(f.mutations.length,0);
  f.desk.data.services[0]={name:'service',status:'Delivered'};assert.equal(await f.desk.action_service_status('service'),'direct');assert.equal(f.desk.directReturn,'service');
});
