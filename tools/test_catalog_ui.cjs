const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

function fixture(){
  let id=0;const timers=new Map(),requests=[],alerts=[],submissions=[];
  class Desk {
    constructor(){this.property='authorized-property';this.data={items:[{name:'first',item_name:'Agua',is_sales_item:1}]};}
    async dialog(title,fields,submit){
      const values={},events={},button={disabled:false,prop(key,value){this[key]=value;return this;}};
      const d={fields_dict:Object.fromEntries(fields.map(df=>[df.fieldname,{df,$input:{on(event,fn){events[df.fieldname]=fn;}}}])),values,events,button,visible:true,
        $wrapper:{is(){return d.visible;},on(event,fn){d.closed=fn;}},get_primary_btn(){return button;},get_value(name){return values[name];},
        set_df_property(name,key,value){this.fields_dict[name].df[key]=value;},async set_value(name,value){values[name]=value;},submit};
      return d;
    }
    call(method,args){return new Promise((resolve,reject)=>requests.push({method,args,resolve,reject}));}
  }
  const ctx={window:{hospitality_suite:{Desk}},__:s=>s,frappe:{msgprint:s=>alerts.push(s)},setTimeout(fn){const n=++id;timers.set(n,fn);return n;},clearTimeout(n){timers.delete(n);}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_catalog.js'),'utf8'),ctx);
  const desk=new Desk();
  return {desk,requests,alerts,submissions,async open(extra={}){return desk.dialog('Consumo',[desk.item_field('Artículo','sale',extra)],v=>submissions.push(v));},
    async search(d,term){d.values._hs_item_search=term;d.events._hs_item_search();const job=[...timers.values()].at(-1);timers.clear();return {pending:job()};}};
}

test('catalogue keeps human names and immutable item keys, including duplicate descriptions',async()=>{
  const f=fixture(),d=await f.open();
  const job=await f.search(d,'Catálogo');
  assert.equal(d.button.disabled,true);
  f.requests[0].resolve({items:[{name:'sku-605',item_name:'Agua especial'},{name:'sku-606',item_name:'Agua especial'}],has_more:false});
  await job.pending;
  assert.equal(d.button.disabled,false);
  const options=d.fields_dict.item.df.options;
  assert.equal(options[1].label,'Agua especial · sku-605');
  assert.equal(options[1].value,'sku-605');
  await d.set_value('item','sku-605');
  await d.submit({...d.values,quantity:2},d);
  assert.equal(f.submissions[0].item,'sku-605');
  assert.equal(f.submissions[0].quantity,2);
  assert.equal(Object.hasOwn(f.submissions[0],'_hs_item_search'),false);
  const next=await f.search(d,'Otro');
  f.requests[1].resolve({items:[{name:'different',item_name:'Jabón'}],has_more:true});
  await next.pending;
  assert.equal(d.values.item,'sku-605');
  assert.equal(d.fields_dict.item.df.options[1].value,'sku-605');
  assert.match(d.fields_dict.item.df.description,/más de 50/);
  assert.match(d.fields_dict.item.df.description,/Se conserva el artículo seleccionado/);
});

test('outdated catalogue responses cannot overwrite results or authorize a failed search',async()=>{
  const f=fixture(),d=await f.open();
  const older=await f.search(d,'anterior'),newer=await f.search(d,'actual');
  f.requests[1].resolve({items:[{name:'new',item_name:'Resultado actual'}],has_more:false});
  await newer.pending;
  f.requests[0].resolve({items:[{name:'old',item_name:'Resultado obsoleto'}],has_more:false});
  await older.pending;
  assert.equal(d.fields_dict.item.df.options[1].value,'new');
  const failed=await f.search(d,'fallará');
  f.requests[2].reject(new Error('offline'));
  await failed.pending;
  await d.submit({item:'new'},d);
  assert.equal(f.submissions.length,0);
  assert.equal(d.button.disabled,true);
  assert.equal(d._hsCatalogBlocked,true);
  assert.equal(f.alerts.length,1);
  const closed=await f.search(d,'cerrado');
  d.visible=false;d.closed();
  f.requests[3].resolve({items:[{name:'closed',item_name:'No debe aplicarse'}],has_more:false});
  await closed.pending;
  assert.equal(d.fields_dict.item.df.options[1].value,'new');
});
