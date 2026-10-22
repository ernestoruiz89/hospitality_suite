const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');

function fixture(){
  const mutations=[];
  class Desk{
    constructor(){this.data={rooms:[{name:'room',room_number:'101',active:1}],server_time:'2026-10-22 12:00:00',
      system_timezone:'UTC',room_blocks:{active:[{name:'B1',room:'room',reason:'VIP Hold',
        starts_at:'2026-10-23 12:00:00',ends_at:'2026-10-24 12:00:00',status:'Active',
        note:'<img src=x onerror=alert(1)>',modified:'v1'}],recently_released:[]}};}
    render_reception(){}
    serverNow(){return 0;}
    roomName(){return '101';}
    date(value){return value;}
    button(action,label,id=''){return `<button data-act="${action}" data-id="${id}">${label}</button>`;}
    table(_headings,rows){return `<table>${rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join('')}</table>`;}
    empty(){return '<p>Vacío</p>';}
    async dialog(title,fields,submit){const d={hide(){d.hidden=true;}};return {title,fields,submit:values=>submit(values,d)};}
    async mutate(action,data,key){mutations.push({action,data,key});}
  }
  const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const window={hospitality_suite:{Desk}};
  const moment={tz:()=>({valueOf:()=>0}),parseZone:()=>({seconds(){return this;},add(){return this;},format(){return '2026-10-22T12:00';}})};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_room_blocks.js'),'utf8'),
    {window,frappe:{utils:{escape_html:escape,get_random:()=> 'key'}},__:value=>value,moment});
  return {desk:new Desk(),mutations};
}

test('room block board escapes notes and offers release for the recorded block',()=>{
  const {desk}=fixture(),target={html(markup){this.markup=markup;}};
  desk['render_room-blocks'](target);
  assert.match(target.markup,/&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(target.markup,/<img src=x onerror/);
  assert.match(target.markup,/data-act="room_unblock" data-id="B1"/);
});

test('create and release submit scoped inputs through Suite commands',async()=>{
  const {desk,mutations}=fixture();
  const create=await desk.action_room_block('room');
  assert.equal(create.fields.find(row=>row.fieldname==='room').default,'room');
  await create.submit({room:'room',reason:'VIP Hold',starts_at:'2026-10-23T12:00',ends_at:'2026-10-24T12:00'});
  const release=await desk.action_room_unblock('B1');
  await release.submit({reason:'Ya no se necesita'});
  assert.equal(mutations[0].action,'room_block');
  assert.equal(mutations[1].action,'room_unblock');
  assert.equal(mutations[1].data.modified,'v1');
  assert.equal(mutations[1].data.reason,'Ya no se necesita');
});
