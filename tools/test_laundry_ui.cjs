const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');

function fixture(){
  const actions=[];
  class Desk{
    constructor(){
      this.property='P1';this.prop={currency:'NIO'};this.data={rooms:[{name:'room',room_number:'101'}],system_timezone:'UTC',
        laundry:{stays:[{name:'stay',room:'room'}],rates:[{name:'rate',garment:'Camisa',service_type:'Wash & Iron',rate:40,currency:'NIO',active:1}],
          orders:[{name:'order',room:'room',stay:'stay',status:'Ready',currency:'NIO',total:80,modified:'v1',notes:'<img src=x onerror=alert(1)>',
            items:[{name:'line',garment:'Camisa',service_type:'Wash & Iron',quantity:2,returned_quantity:1,rate:40}]}],
          last_30_days:{charges:40,currency:'NIO',by_service:[{service_type:'Wash & Iron',pieces:1,charges:40}]}}};
    }
    allowed(action){return action==='service'||action==='setup';}
    roomName(){return '101';}amount(value){return `${value} NIO`;}
    date(value){return value;}serverNow(){return 0;}
    button(action,label,id=''){return `<button data-act="${action}" data-id="${id}">${label}</button>`;}
    table(headings,rows){return `<table>${rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join('')}</table>`;}
    empty(text){return `<p>${text}</p>`;}
    async dialog(title,fields,submit,label){const dialog={hide(){dialog.hidden=true;}};return {title,fields,label,dialog,submit:values=>submit(values,dialog)};}
    async mutate(action,data,key){actions.push({action,data,key});return {ok:true};}
  }
  const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_laundry.js'),'utf8'),
    {window:{hospitality_suite:{Desk}},frappe:{utils:{escape_html:escape,get_random:()=> 'key'}},__:value=>value,
      moment:{tz:()=>({valueOf:()=>0})}});
  return {desk:new Desk(),actions};
}

test('laundry board escapes guest notes and separates quoted and returned charges',()=>{
  const {desk}=fixture(),target={html(markup){this.markup=markup;}};
  desk.render_laundry(target);
  assert.match(target.markup,/&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(target.markup,/<img src=x onerror/);
  assert.match(target.markup,/80 NIO/);
  assert.match(target.markup,/40 NIO/);
  assert.match(target.markup,/data-act="laundry_return"/);
});

test('delivery sends the counted shortage and version for a server decision',async()=>{
  const {desk,actions}=fixture(),form=await desk.action_laundry_deliver('order');
  assert.match(form.fields[0].options,/40 NIO/);
  assert.equal(form.fields[1].fieldname,'shortage_note');
  await form.submit({shortage_note:'Falta una camisa'});
  assert.equal(actions.length,1);
  assert.equal(actions[0].action,'laundry_deliver');
  assert.equal(actions[0].data.order,'order');
  assert.equal(actions[0].data.modified,'v1');
  assert.equal(actions[0].data.shortage_note,'Falta una camisa');
});

test('walk-up collection submits selected stay and item counts through the command',async()=>{
  const {desk,actions}=fixture(),form=await desk.action_laundry_collect_now();
  assert.ok(form.fields.some(field=>field.fieldname==='stay'));
  assert.ok(form.fields.some(field=>field.fieldname==='items'));
  await form.submit({stay:'stay',express:1,items:[{rate:'rate',quantity:2}]});
  assert.equal(actions[0].action,'laundry_collect');
  assert.equal(actions[0].data.stay,'stay');
  assert.equal(actions[0].data.items[0].quantity,2);
});
