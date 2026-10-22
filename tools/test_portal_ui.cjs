const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
async function fixture(){
 const ids=['property','category','category-info','category-image','stay-mode','request-mode','start','end','quantity','people','name','email','phone','quote','request','form','empty','result','breakdown','zone'];
 const elements=Object.fromEntries(ids.map(id=>['hp-'+id,{value:['quantity','people'].includes(id)?'1':'',hidden:id==='request',disabled:false,handlers:{},options:[],
   addEventListener(event,callback){this.handlers[event]=callback;},add(option){this.options.push(option);if(!this.value)this.value=option.value;},replaceChildren(){this.options=[];this.value='';},removeAttribute(name){delete this[name];}}]));
 elements['hp-form'].elements=ids.filter(id=>!['form','empty','result','breakdown','category-info','category-image','zone'].includes(id)).map(id=>elements['hp-'+id]);
 elements['hp-request-mode'].value='Hold';
 const document={getElementById:id=>elements[id],body:{}};document.activeElement=document.body;
 for(const element of Object.values(elements))element.focus=()=>{document.activeElement=element;};
 const requests=[];let nativeMessages=0,init,quote=async()=>({amount:'1500.00',estimated_total:'1650.00',currency:'NIO',acceptance:'accepted',explanation:['Tarifa de temporada']}),request=async()=>({confirmation_url:'/signed-confirmation'}),redirect;
 const context={__:(value,args)=>typeof value==="string"&&args?value.replace(/\{(\d+)\}/g,(m,n)=>args[n]??m):value,document,$:()=>({length:0}),Option:class{constructor(text,value){this.text=text;this.value=value;}},crypto:{randomUUID:()=> 'stable-request-key'},
  window:{location:{assign:url=>{redirect=url;}}},frappe:{ready:callback=>{init=callback();},call:async({method,args,error_msg})=>{
   try{return{message:method.endsWith('.catalog')?[{name:'hotel',property_name:'Hotel ficticio',mode:'Mixed',time_zone:'America/Managua',categories:[{name:'standard',category_name:'Estándar',capacity:2,amenities:'Wi-Fi',portal_description:'Vista al jardín',portal_image:'/files/room.png'}]}]:method.endsWith('.quote')?await quote(args):await (async()=>{requests.push(args);return request(args);})()};}
   catch(error){if(error.responseJSON?._server_messages&&!error_msg)nativeMessages++;throw error;} // native Website ignores silent
  }}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/www/hospitality.js'),'utf8'),context);await init;
 return{elements,requests,document,nativeMessages:()=>nativeMessages,setQuote:fn=>{quote=fn;},setRequest:fn=>{request=fn;},redirect:()=>redirect};
}

test('quote results recover focus after a disabled button, without stealing focus from another field',async()=>{
 const f=await fixture(),form=f.elements['hp-form'],result=f.elements['hp-result'];
 assert.match(f.elements['hp-category-info'].textContent,/Capacidad: 2/);assert.match(f.elements['hp-category-info'].textContent,/Wi-Fi/);assert.match(f.elements['hp-category-info'].textContent,/Vista al jardín/);
 assert.equal(f.elements['hp-category-image'].src,'/files/room.png');assert.equal(f.elements['hp-category-image'].hidden,false);
 let resolve;f.setQuote(()=>new Promise(done=>{resolve=done;}));f.elements['hp-quote'].focus();
 const first=form.handlers.submit({preventDefault(){}});f.document.activeElement=f.document.body; // native disabled button loses focus
 resolve({amount:'1500.00',currency:'NIO',acceptance:'current'});await first;
 assert.equal(f.document.activeElement,result);assert.equal(result.tabIndex,-1);assert.equal(f.elements['hp-request'].hidden,false);
 const next=form.handlers.submit({preventDefault(){}});f.elements['hp-name'].focus();resolve({amount:'1500.00',currency:'NIO',acceptance:'next'});await next;
 assert.equal(f.document.activeElement,f.elements['hp-name']);
 f.document.activeElement=f.document.body;f.setQuote(async()=>{throw{responseJSON:{_server_messages:'No queda cupo'}};});await form.handlers.submit({preventDefault(){}});
 assert.equal(f.document.activeElement,result);assert.match(result.textContent,/No se encontró disponibilidad/);assert.equal(f.elements['hp-request'].hidden,true);
 assert.equal(f.nativeMessages(),0,'Website must not open a second modal for the same business rejection');
});
test('portal explains quoted rate and estimated timing costs as text, then clears obsolete details',async()=>{
 const f=await fixture();await f.elements['hp-form'].handlers.submit({preventDefault(){}});
 assert.match(f.elements['hp-breakdown'].textContent,/Tarifa de temporada/);
 assert.match(f.elements['hp-breakdown'].textContent,/1650.00 NIO/);
 f.elements['hp-form'].handlers.input();assert.equal(f.elements['hp-breakdown'].textContent,'');
});
test('request without hold is explicit and submitted with the same reviewed mode',async()=>{
 const f=await fixture();f.elements['hp-request-mode'].value='Requested';f.elements['hp-request-mode'].handlers.change();f.elements['hp-form'].handlers.input();
 assert.match(f.elements['hp-zone'].textContent,/no reserva cupo/);assert.match(f.elements['hp-request'].textContent,/sin retención/);
 await f.elements['hp-form'].handlers.submit({preventDefault(){}});
 assert.match(f.elements['hp-result'].textContent,/no reserva cupo/);
 await f.elements['hp-request'].handlers.click();
 assert.equal(JSON.parse(f.requests[0].data).request_mode,'Requested');
});
test('portal Day Pass uses the same-day interval and preserves its mode through confirmation',async()=>{
 const f=await fixture();f.elements['hp-start'].value='2026-10-22T09:00';f.elements['hp-stay-mode'].value='Day Pass';
 f.elements['hp-stay-mode'].handlers.change();
 assert.equal(f.elements['hp-end'].value,'2026-10-22T17:00');
 assert.match(f.elements['hp-zone'].textContent,/mismo día/);
 f.setQuote(async args=>{assert.equal(JSON.parse(args.data).mode,'Day Pass');return{amount:'800.00',currency:'NIO',acceptance:'day-pass'};});
 await f.elements['hp-form'].handlers.submit({preventDefault(){}});
 await f.elements['hp-request'].handlers.click();
 assert.equal(JSON.parse(f.requests[0].data).mode,'Day Pass');
});
test('editing dates while a quote is in flight invalidates its response',async()=>{
 const f=await fixture();let resolve;f.setQuote(()=>new Promise(done=>{resolve=done;}));
 const submit=f.elements['hp-form'].handlers.submit({preventDefault(){}});
 f.elements['hp-end'].value='2026-11-03T12:00';f.elements['hp-form'].handlers.input();
 resolve({amount:'1500.00',currency:'NIO',acceptance:'obsolete'});await submit;
 assert.equal(f.elements['hp-request'].hidden,true);
 await f.elements['hp-request'].handlers.click();assert.equal(f.requests.length,0);
});
test('an uncertain request unlocks controls and retries the same quote and key',async()=>{
 const f=await fixture();await f.elements['hp-form'].handlers.submit({preventDefault(){}});
 let attempts=0;f.setRequest(async()=>{if(++attempts===1)throw Error('response lost');return{confirmation_url:'/signed-confirmation'};});
 await f.elements['hp-request'].handlers.click();
 assert.match(f.elements['hp-result'].textContent,/Sin confirmación del servidor/);
 assert(f.elements['hp-form'].elements.every(control=>!control.disabled));
 await f.elements['hp-request'].handlers.click();assert.equal(f.requests.length,2);
 assert.equal(f.requests[0].request_key,f.requests[1].request_key);assert.equal(f.requests[0].data,f.requests[1].data);
 assert.equal(f.redirect(),'/signed-confirmation');
});
