// Exercise the shipped Desk methods with reordered/failed server responses.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function fixture(){
  const timers=new Map();let timer=0;
  const hospitality_suite={};
  const context={window:{hospitality_suite},hospitality_suite,frappe:{utils:{escape_html:String,get_random:()=>"fallback"},show_alert(){}},
    moment:{tz:()=>({valueOf:()=>0})},localStorage:{setItem(){}},$:()=>({is:()=>true}),
    setTimeout:fn=>{timers.set(++timer,fn);return timer;},clearTimeout:id=>timers.delete(id)};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality.js'),'utf8'),context);
  const desk=Object.create(hospitality_suite.Desk.prototype);
  desk.property='hotel';desk.root={attr(k,v){desk.aria=v;return this;},html(v){desk.html=v;return this;}};
  desk.data={tag:'initial'};desk.render=()=>{desk.rendered=desk.data.tag;};desk.bind=()=>{};desk.connection=()=>{};
  return {desk,timers};
}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}
const snapshot=(tag,property='hotel')=>({tag,server_time:'2026-10-19 10:00:00',system_timezone:'America/Managua',properties:[{name:property}]});
test('an older success cannot overwrite a newer property response',async()=>{
  const {desk}=fixture(),old=deferred(),fresh=deferred();let count=0;
  desk.call=()=>++count===1?old.promise:fresh.promise;
  const first=desk.load();desk.property='motel';const second=desk.load();
  fresh.resolve(snapshot('new','motel'));await second;old.resolve(snapshot('old'));await first;
  assert.equal(desk.rendered,'new');assert.equal(desk.property,'motel');
});
test('an old failure cannot clear busy or replace a newer result with an error',async()=>{
  const {desk}=fixture(),old=deferred(),fresh=deferred();let count=0;
  desk.call=()=>++count===1?old.promise:fresh.promise;
  const first=desk.load(),second=desk.load();old.reject(Error('old connection failed'));await first;
  assert.equal(desk.aria,'true');assert.equal(desk.html,undefined);
  fresh.resolve(snapshot('new'));await second;assert.equal(desk.rendered,'new');assert.equal(desk.aria,'false');
});
test('an invalidation during a failed mutation is refreshed once the request ends',async()=>{
  const {desk,timers}=fixture(),pending=deferred();desk.call=()=>pending.promise;
  const mutation=desk.mutate('payment',{amount:30},'stable-key');
  desk.scheduleRefresh();[...timers.values()].at(-1)();assert.equal(desk.refreshPending,true);
  pending.reject(Error('response lost'));await assert.rejects(mutation,/response lost/);
  assert.equal(desk.busy,false);
  let refreshed=0;desk.load=()=>{refreshed++;};[...timers.values()].at(-1)();assert.equal(refreshed,1);
});
