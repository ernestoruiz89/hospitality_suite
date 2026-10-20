const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(){
  const requests=[],saves=[];
  const config={modified:'version-1',values:{lodging_item:'lodging',extra_hour_item:'hours',timing_item:'timing',price_list:'prices'},mappings:[{field:'lodging_item',label:'Alojamiento',item_name:'Suite <principal>'},{field:'extra_hour_item',label:'Horas adicionales',item_name:'Hora adicional'},{field:'timing_item',label:'Horario',item_name:'Servicio horario'}]};
  class Desk{
    constructor(){this.property='authorized';this.data={};}render_setup(){}
    table(headers,rows){return rows.flat().join('|');}item_field(label,purpose,extra){return {fieldname:'item',fieldtype:'Select',label,purpose,...extra};}
    amount(value,currency){return Number(value).toFixed(2)+' '+currency;}
    async load(){}
    async call(method,args){if(method==='save_setup'){saves.push(args);return {};}if(!args.item)return config;return new Promise((resolve,reject)=>requests.push({args,resolve,reject}));}
    async dialog(title,fields,submit){
      const values=Object.fromEntries(fields.map(df=>[df.fieldname,df.default]));let html='';
      const view={text(value){html=value;},html(value){html=value;},empty(){html='';}};
      const d={fields,submit,values,visible:true,fields_dict:Object.fromEntries(fields.map(df=>[df.fieldname,{df,$wrapper:view}])),
        get_value:field=>values[field],hide(){this.visible=false;},$wrapper:{is:()=>d.visible,on(event,fn){d.closed=fn;}},get html(){return html;}};
      return d;
    }
  }
  const context={window:{hospitality_suite:{Desk}},__:s=>s,frappe:{utils:{get_random:()=> 'one-key',escape_html:s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;')}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_items.js'),'utf8'),context);
  return {desk:new Desk(),requests,saves};
}
test('service setup shows escaped names and saves only mappings/list with the reviewed version',async()=>{
  const f=fixture(),d=await f.desk.action_service_items();
  assert.match(d.fields[0].options,/Suite &lt;principal&gt;/);
  const input={...d.values,item:'preview-only',_hs_item_search:'not-a-setting'};
  await d.submit(input,d);
  const save=f.saves[0];assert.equal(save.expected_modified,'version-1');assert.equal(save.request_key,'one-key');
  assert.deepEqual(JSON.parse(save.data),{lodging_item:'lodging',extra_hour_item:'hours',timing_item:'timing',price_list:'prices'});
});
test('old service prices cannot overwrite a newer selection or a closed dialog',async()=>{
  const f=fixture(),d=await f.desk.action_service_items();
  d.values.item='first';const first=d.fields_dict.item.df.onchange();
  d.values.item='second';const second=d.fields_dict.item.df.onchange();
  f.requests[1].resolve({currency:'NIO',price_list:'prices',service:{item_name:'Otro <servicio>',status:'Priced',rate:35,is_stock_item:false}});await second;
  const fresh=d.html;assert.match(fresh,/Otro &lt;servicio&gt;/);assert.match(fresh,/35.00 NIO/);
  f.requests[0].resolve({currency:'USD',service:{item_name:'Old',status:'Missing'}});await first;assert.equal(d.html,fresh);
  d.values.item='third';const third=d.fields_dict.item.df.onchange();d.closed();const waiting=d.html;
  f.requests[2].resolve({currency:'NIO',service:{item_name:'Closed',status:'Missing'}});await third;assert.equal(d.html,waiting);
});
