const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

function fixture(){
  class Desk {
    constructor(){this.property='hotel';this.route='hospitality-reception';this.data={rooms:[{name:'R1'}]};}
    render(){} render_reception(){} filterRooms(){} render_home(){} updateTimers(){}
    date(value){return value;}
    amount(value,currency){return `${value} ${currency}`;}
  }
  const escape=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const context={window:{hospitality_suite:{Desk}},frappe:{utils:{escape_html:escape}},__:(text,args)=>args?text.replace(/\{(\d+)\}/g,(_,i)=>args[i]):text};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_room_view.js'),'utf8'),context);
  const desk=new Desk(),holder={value:'',html(value){this.value=value;}};
  const panel={property:'hotel',room:'R1',tab:'now',sequence:0,sectionSequence:0,
    dialog:{$wrapper:{find(){return {each(){}};}},fields_dict:{body:{$wrapper:holder}}}};
  desk.roomPanel=panel;
  return {desk,panel,holder};
}

function snapshot(){return {property:'hotel',checked_at:'2026-10-22T10:00:00-06:00',time_zone:'America/Managua',
  room:{name:'R1',room_number:'101',category_label:'<Suite>',floor:'1',occupied:false,cleaning_status:'Clean',blocked:false,active:true},
  current:null,next_arrival:null,tasks:[],maintenance:[],can:{history:true,clean:false,maintain:false,reserve:true},details:{}};}

function deferred(){let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};}

test('room detail escapes server labels and presents physical state in Spanish',()=>{
  const {desk,panel,holder}=fixture();panel.data=snapshot();desk.renderRoomPanel(panel);
  assert.match(holder.value,/&lt;Suite&gt;/);
  assert(!holder.value.includes('<Suite>'));
  assert.match(holder.value,/Limpia/);
  assert(!holder.value.includes('>Clean<'));
  assert.match(holder.value,/aria-selected="true" tabindex="0">Ahora/);
});

test('late detail response cannot replace another property or selected room',async()=>{
  const {desk,panel,holder}=fixture(),old=deferred();
  desk.call=()=>old.promise;
  const pending=desk.loadRoomSnapshot(panel);
  desk.property='other';desk.roomPanel=null;
  old.resolve(snapshot());await pending;
  assert.equal(holder.value,'');
  desk.property='hotel';desk.roomPanel=panel;desk.call=async()=>snapshot();
  await desk.loadRoomSnapshot(panel);
  assert.match(holder.value,/Ficha|Estancia actual/);
});
