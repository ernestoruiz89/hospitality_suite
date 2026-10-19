const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
async function fixture(){
 const ids=['property','category','start','end','quantity','people','name','email','phone','quote','request','form','empty','result','zone'];
 const elements=Object.fromEntries(ids.map(id=>['hp-'+id,{value:['quantity','people'].includes(id)?'1':'',hidden:id==='request',disabled:false,handlers:{},options:[],
   addEventListener(event,callback){this.handlers[event]=callback;},add(option){this.options.push(option);if(!this.value)this.value=option.value;},replaceChildren(){this.options=[];this.value='';}}]));
 elements['hp-form'].elements=ids.filter(id=>!['form','empty','result','zone'].includes(id)).map(id=>elements['hp-'+id]);
 const requests=[];let init,quote=async()=>({amount:'1500.00',currency:'NIO',acceptance:'accepted'}),request=async()=>({confirmation_url:'/signed-confirmation'}),redirect;
 const context={__:(value,args)=>typeof value==="string"&&args?value.replace(/\{(\d+)\}/g,(m,n)=>args[n]??m):value,document:{getElementById:id=>elements[id]},Option:class{constructor(text,value){this.text=text;this.value=value;}},crypto:{randomUUID:()=> 'stable-request-key'},
  window:{location:{assign:url=>{redirect=url;}}},frappe:{ready:callback=>{init=callback();},call:async({method,args})=>({message:method.endsWith('.catalog')?[{name:'hotel',property_name:'Hotel ficticio',time_zone:'America/Managua',categories:[{name:'standard',category_name:'Estándar'}]}]:method.endsWith('.quote')?await quote(args):await (async()=>{requests.push(args);return request(args);})()})}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/www/hospitality.js'),'utf8'),context);await init;
 return{elements,requests,setQuote:fn=>{quote=fn;},setRequest:fn=>{request=fn;},redirect:()=>redirect};
}
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
