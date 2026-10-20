const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(){
  const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const context={window:{hospitality_suite:{}},frappe:{utils:{escape_html:escape,get_random:()=> 'key'}},__:(text,args)=>args?text.replace(/\{(\d+)\}/g,(_,i)=>args[i]):text};context.hospitality_suite=context.window.hospitality_suite;
  for(const file of ['hospitality.js','hospitality_booking_summary.js','hospitality_extras.js'])vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js',file),'utf8'),context);
  const desk=Object.create(context.hospitality_suite.Desk.prototype);Object.assign(desk,{property:'p',prop:{},data:{categories:[],rooms:[],guests:[]},allowed:()=>true,date:v=>v,amount:(v,c)=>`${c} ${v}`});
  const info={booking:{name:'OPAQUE-BOOKING',property:'p',status:'Checked In',starts_at:'2026-10-24 14:00',ends_at:'2026-10-25 12:00',amount:750,currency:'NIO',channel:'Recepción',instructions:'<script>unsafe</script>'},allocations:[],summary:{guest_label:'Huésped registrado',customer_label:'Ana',mode_label:'Por tiempo',rooms:[{number:1,room_label:'M103',category_label:'Estándar',people:2,extra_beds:0,stays:[{name:'STAY-ID',status:'Active',room_label:'M104',guest_label:'Huésped registrado'}]}]}};
  return{desk,info};
}
test('entered booking opens a complete Spanish summary instead of the opaque identifier',async()=>{
  const {desk,info}=fixture();let fields,label;desk.call=async()=>info;
  const dialog={$wrapper:{on(){}},hide(){}};desk.dialog=async(title,inputs,submit,action)=>{fields=inputs;label=action;return dialog;};
  assert.equal(await desk.action_booking('OPAQUE-BOOKING'),dialog);assert.equal(label,'Cerrar');
  const html=fields[0].options;assert.match(html,/Entrada registrada/);assert.match(html,/Huésped registrado/);assert.match(html,/Ana/);assert.match(html,/M103/);assert.match(html,/M104/);assert.match(html,/Personas: 2/);assert.match(html,/Por tiempo/);assert.match(html,/NIO 750/);assert.match(html,/&lt;script&gt;/);
  assert.doesNotMatch(html,/OPAQUE-BOOKING|Checked In|<script>/);
  info.booking.name='RES-2026-00001';assert.match(desk.booking_summary(info),/Número de reserva.*RES-2026-00001/);
});
test('confirmed and partially entered bookings keep the same summary above their available actions',async()=>{
  for(const status of ['Hold','Confirmed','Checked In']){
    const {desk,info}=fixture();info.booking.status=status;info.allocations=[{name:'a',booking_room:'row',category:'cat'}];info.booking.rooms=[];desk.call=async()=>info;
    let fields;desk.dialog=async(title,inputs)=>{fields=inputs;return {$wrapper:{on(){}}};};await desk.action_booking('OPAQUE-BOOKING');
    assert.equal(fields[0].fieldname,'booking_summary');assert.equal(fields[1].fieldtype,'Section Break');assert(fields.some(row=>row.fieldname==='status'));
  }
});
test('read-only roles see the summary, stale property replies are ignored and account links respect permissions',async()=>{
  const {desk,info}=fixture();desk.allowed=()=>false;assert.doesNotMatch(desk.booking_summary(info),/data-act="detail"/);
  desk.call=async()=>info;let count=0;desk.dialog=async()=>{count++;return {$wrapper:{on(){}}};};await desk.action_booking('OPAQUE-BOOKING');assert.equal(count,1);
  desk.call=async()=>{desk.property='other';return info;};await desk.action_booking('OPAQUE-BOOKING');assert.equal(count,1);
});
