const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');

function fixture(){
  const mutations=[];
  class Desk{
    constructor(){this.property='P';this.prop={time_zone:'America/Managua'};this.data={system_timezone:'UTC',
      travel_experiences:{agents:[{name:'A',agent_name:'<img src=x>',agent_type:'OTA',commission_pct:10,active:1}],
        experiences:[{name:'E',experience_name:'Tour',experience_category:'Tour',item:'ITEM',active:1}],
        orders:[{name:'O',booking:'B',experience:'E',quantity:2,amount:150,currency:'NIO',status:'Confirmed',
          modified:'v1',participants:2}]},
      bookings:[{name:'B',travel_agent:'A',status:'Completed',amount:1000,agent_commission_estimate:100,
        currency:'NIO',modified:'b1'}],stays:[{name:'S',booking:'B',status:'Active',room:'R'}],
      folios:[{name:'F',booking:'B',status:'Open',label:'Principal'}]};}
    allowed(){return true;}
    bookingLabel(value){return value;}
    roomName(value){return value;}
    amount(value){return String(value);}
    date(value){return value;}
    button(action,label,id=''){return `<button data-act="${action}" data-id="${id}">${label}</button>`;}
    table(_,rows){return `<table>${rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join('')}</table>`;}
    async dialog(title,fields,submit){const d={hide(){}};return {title,fields,submit:values=>submit(values,d)};}
    async mutate(action,data,key){mutations.push({action,data,key});}
    async call(method){if(method==='preview')return {base:'1000.00',percent:'10',amount:'100.00',currency:'NIO',modified:'b1'};}
  }
  const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const window={hospitality_suite:{Desk}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_travel_experiences.js'),'utf8'),
    {window,frappe:{utils:{escape_html:escape,get_random:()=> 'key'}},__:value=>value,moment:{tz:()=>({tz:()=>({format:()=>''})})}});
  return {desk:new Desk(),mutations};
}

test('agency page escapes names and exposes completed commission settlement',()=>{
  const {desk}=fixture(),target={html(markup){this.markup=markup;}};
  desk['render_travel-agents'](target);
  assert.match(target.markup,/&lt;img src=x&gt;/);
  assert.doesNotMatch(target.markup,/<img src=x>/);
  assert.match(target.markup,/data-act="agent_commission" data-id="B"/);
});

test('experience delivery and agent settlement submit recorded versions',async()=>{
  const {desk,mutations}=fixture();
  const experience=await desk.action_experience_status('O');
  await experience.submit({status:'Delivered',stay:'S',folio:'F'});
  const agent=await desk.action_agent_commission('B');
  await agent.submit({});
  assert.equal(mutations[0].action,'experience_status');
  assert.equal(mutations[0].data.modified,'v1');
  assert.equal(mutations[1].action,'agent_commission');
  assert.equal(mutations[1].data.modified,'b1');
});
