// Real Frappe sessions and Socket.IO transport; credentials stay in the bench.
const fs=require('node:fs');
const {createRequire}=require('node:module');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const {once}=require('node:events');
const bench='/home/frappe/benches/hospitality-bench';
const {io}=createRequire(bench+'/apps/frappe/package.json')('socket.io-client');
const config=JSON.parse(fs.readFileSync(bench+'/.hospitality-transport-users.json','utf8'));
const clients=[];
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function waitFor(fn,label){const end=Date.now()+8000;while(Date.now()<end){if(fn())return;await delay(50);}throw Error('Timeout: '+label);}
async function login(account){
 const res=await fetch('http://localhost:8086/api/method/login',{method:'POST',body:new URLSearchParams({usr:account.user,pwd:account.password})});
 assert.equal(res.status,200,'Native login failed');
 const cookie=res.headers.getSetCookie().find(c=>c.startsWith('sid='))?.split(';')[0];assert(cookie);
 return cookie;
}
async function connect(cookie){
 const socket=io('http://localhost:9001/hospitality.localhost',{autoConnect:false,transports:['websocket'],reconnection:false,extraHeaders:{Cookie:cookie,Origin:'http://localhost:8086'}});
 const events=[];socket.on('hospitality_changed',event=>events.push(event));
 const connected=once(socket,'connect');socket.connect();await connected;
 const pong=once(socket,'pong');socket.emit('ping');await pong;
 const client={socket,events};clients.push(client);return client;
}
function pending(token){
 const child=spawn(bench+'/env/bin/python',['/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel/tools/transport_probe.py','pending','--token',token],{stdio:['pipe','pipe','pipe']});
 let text='',errors='';child.stdout.on('data',s=>{text+=s;});child.stderr.on('data',s=>{errors+=s;});
 const exited=once(child,'exit');
 return{async ready(){await waitFor(()=>text.includes('"ready": true'),'native transaction ready');},async end(decision){child.stdin.end(decision+'\n');const[code]=await exited;assert.equal(code,0,'Native transaction failed: '+errors.slice(-300));return JSON.parse(text.trim().split('\n').at(-1));}};
}
(async()=>{
 const hotelCookie=await login(config.hotel),motelCookie=await login(config.motel);
 const a=await connect(hotelCookie),b=await connect(hotelCookie),excluded=await connect(motelCookie);
 const token='transport-'+Date.now();
 const rolled=pending(token+'-rollback');await rolled.ready();await delay(350);
 assert.equal(a.events.length+b.events.length+excluded.events.length,0,'Event before commit');
 await rolled.end('rollback');await delay(350);assert.equal(a.events.length+b.events.length+excluded.events.length,0,'Event after rollback');
 const committed=pending(token+'-commit');await committed.ready();await delay(350);assert.equal(a.events.length,0);
 const first=await committed.end('commit');await waitFor(()=>a.events.length&&b.events.length,'both authorized sessions');
 await delay(200);assert.equal(excluded.events.length,0,'Cross-property event leaked');
 for(const event of [...a.events,...b.events]){assert.deepEqual(Object.keys(event),['property']);assert.equal(event.property,config.hotel.property);}
 const countA=a.events.length,countB=b.events.length;
 const disconnected=once(b.socket,'disconnect');b.socket.io.engine.close();await disconnected;assert.equal(b.socket.connected,false);
 const gap=pending(token+'-gap');await gap.ready();const missed=await gap.end('commit');
 await waitFor(()=>a.events.length>countA,'remaining connected session');assert.equal(b.events.length,countB);
 const reconnected=once(b.socket,'connect');b.socket.connect();await reconnected;
 const state=await fetch('http://localhost:8086/api/method/hospitality_suite.api.bootstrap?property_name='+encodeURIComponent(config.hotel.property),{headers:{Cookie:hotelCookie}}).then(r=>r.json());
 assert(state.message.guests.some(g=>g.name===missed.guest),'Missed commit not recovered by server refresh');
 const next=pending(token+'-reconnected');await next.ready();await next.end('commit');await waitFor(()=>b.events.length>countB,'event after reconnect');
 assert.equal(excluded.events.length,0);
 const result={real_authenticated_sessions:3,distinct_users:2,separate_property_scopes:true,no_events_before_commit:true,no_events_after_rollback:true,
   authorized_sessions_received_commit:2,excluded_property_events:0,payload_keys:['property'],transport_closed:true,reconnected:true,missed_commit_recovered_by_bootstrap:true,
   event_after_reconnect:true,committed_guest:first.guest,missed_guest:missed.guest,browser_cut_test_executed:false};
 fs.writeFileSync('/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel/docs/evidence/transport-sessions.json',JSON.stringify(result,null,2)+'\n');
 console.log(JSON.stringify(result));
})().catch(error=>{console.error(error.message);process.exitCode=1;}).finally(()=>{for(const c of clients)c.socket.disconnect();});
setTimeout(()=>{console.error('Transport probe deadline exceeded');process.exit(1);},45000).unref();
