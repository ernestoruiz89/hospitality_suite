// Native authenticated transport. Main receives invalidations only; business writes stay in acceptance.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process'),{createRequire}=require('node:module');
const bench='/home/frappe/benches/hospitality-bench',root=path.resolve(__dirname,'..');
const {io}=createRequire(bench+'/apps/frappe/package.json')('socket.io-client');
const main='hospitality.localhost',acceptance='hospitality-acceptance.localhost';
const mainAccounts=JSON.parse(fs.readFileSync(bench+'/.hospitality-transport-users.json','utf8'));
const passwords=JSON.parse(fs.readFileSync(bench+'/sites/'+acceptance+'/private/hospitality-demo-users.json','utf8'));
const clients=[],children=new Set();
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(fn,label,ms=30000){const end=Date.now()+ms;while(Date.now()<end){if(fn())return;await delay(50);}throw Error('Timeout: '+label);}
function native(action,site,token,defer=false){
 const args=[root+'/tools/realtime_origin_probe.py',action,'--site',site];
 if(token)args.push('--token',token);if(defer)args.push('--defer');
 const child=spawn(bench+'/env/bin/python',args,{cwd:bench,stdio:['pipe','pipe','pipe']});children.add(child);
 let output='',errors='',ended=false,exitCode;
 child.stdout.on('data',s=>output+=s);child.stderr.on('data',s=>errors+=s);
 child.on('exit',code=>{ended=true;exitCode=code;children.delete(child);});
 return {async ready(){await until(()=>output.includes('"ready": true')||ended,'native transaction');assert(!ended,'Native transaction ended early: '+errors.slice(-250));},
  async finish(decision){if(defer)child.stdin.end(decision+'\n');else child.stdin.end();await until(()=>ended,'native transaction exit');assert.equal(exitCode,0,'Native probe failed: '+errors.slice(-500));return JSON.parse(output.trim().split('\n').at(-1));}};
}
async function login(site,port,account){
 const response=await fetch(`http://${site}:${port}/api/method/login`,{method:'POST',body:new URLSearchParams({usr:account.user,pwd:account.password})});
 assert.equal(response.status,200,'Native login failed');
 const cookie=response.headers.getSetCookie().find(x=>x.startsWith('sid='))?.split(';')[0];assert(cookie);return cookie;
}
async function connect(site,port,cookie){
 const socket=io(`http://${site}:9001/${site}`,{autoConnect:false,transports:['websocket'],reconnection:false,extraHeaders:{Cookie:cookie,Origin:`http://${site}:${port}`}});
 const client={socket,events:[]};clients.push(client);socket.on('hospitality_changed',e=>client.events.push(e));
 await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Native connection timeout')),10000);socket.once('connect',()=>{clearTimeout(timer);resolve();});socket.once('connect_error',e=>{clearTimeout(timer);reject(Error('Native connection rejected: '+e.message));});socket.connect();});
 return client;
}
async function transaction(action,site,decision,token){const call=native(action,site,token,true);await call.ready();return{end:()=>call.finish(decision)};}
(async()=>{
 const mainMeta=await native('metadata',main).finish(),acceptanceMeta=await native('metadata',acceptance).finish();
 const hotelCookie=await login(main,8086,mainAccounts.hotel),motelCookie=await login(main,8086,mainAccounts.motel);
 const a=await connect(main,8086,hotelCookie),b=await connect(main,8086,hotelCookie),excluded=await connect(main,8086,motelCookie);
 const rollback=await transaction('broadcast',main,'rollback');await delay(300);assert.equal(a.events.length+b.events.length+excluded.events.length,0);
 await rollback.end();await delay(300);assert.equal(a.events.length+b.events.length+excluded.events.length,0);
 const commit=await transaction('broadcast',main,'commit');await delay(300);assert.equal(a.events.length,0);await commit.end();
 await until(()=>a.events.length===1&&b.events.length===1,'main authorized invalidations');assert.equal(excluded.events.length,0);
 for(const e of [...a.events,...b.events])assert.deepEqual(e,{property:mainMeta.property});
 const acceptanceAccounts=['receptionist','cashier'].map(role=>({user:role+'@hospitality.example.invalid',password:passwords[role+'@hospitality.example.invalid']}));
 assert(acceptanceAccounts.every(x=>typeof x.password==='string'));
 const cookies=await Promise.all(acceptanceAccounts.map(account=>login(acceptance,8089,account)));
 const c=await connect(acceptance,8089,cookies[0]),d=await connect(acceptance,8089,cookies[1]);
 const token='realtime-origins-'+Date.now();
 const rolled=await transaction('guest',acceptance,'rollback',token+'-rollback');await delay(300);assert.equal(c.events.length+d.events.length,0);
 await rolled.end();await delay(300);assert.equal(c.events.length+d.events.length,0);
 const first=await transaction('guest',acceptance,'commit',token+'-commit');await delay(300);assert.equal(c.events.length+d.events.length,0);await first.end();
 await until(()=>c.events.length===1&&d.events.length===1,'acceptance commit to both roles');
 d.socket.io.engine.close();await until(()=>!d.socket.connected,'acceptance transport disconnected');
 const gap=await native('guest',acceptance,token+'-gap').finish();await until(()=>c.events.length===2,'connected reception receives gap commit');assert.equal(d.events.length,1);
 await new Promise((resolve,reject)=>{d.socket.once('connect',resolve);d.socket.once('connect_error',reject);d.socket.connect();});
 const response=await fetch(`http://${acceptance}:8089/api/method/hospitality_suite.api.bootstrap?property_name=${encodeURIComponent(acceptanceMeta.property)}`,{headers:{Cookie:cookies[0]}});
 assert.equal(response.status,200);const state=await response.json();assert(state.message.guests.some(g=>g.name===gap.guest));
 await native('guest',acceptance,token+'-reconnected').finish();await until(()=>c.events.length===3&&d.events.length===2,'both roles receive after reconnect');
 for(const e of [...c.events,...d.events])assert.deepEqual(e,{property:acceptanceMeta.property});
 await delay(300);assert.equal(a.events.length,1);assert.equal(b.events.length,1);assert.equal(excluded.events.length,0);
 const result={main_origin:`http://${main}:8086`,acceptance_origin:`http://${acceptance}:8089`,authenticated_socket_sessions:5,main_distinct_users:2,acceptance_roles:['HS Receptionist','HS Cashier'],
  main_business_writes:0,main_authorized_receivers:2,other_property_events:0,cross_site_events:0,payload_keys:['property'],before_commit_events:0,after_rollback_events:0,
  acceptance_committed_test_guests:3,acceptance_authorized_receivers:2,disconnect:true,reconnect:true,missed_commit_recovered_by_native_bootstrap:true,event_after_reconnect:true,
  provider_requests:0,ui_replay:false};
 fs.writeFileSync(root+'/docs/evidence/realtime-origins-transport.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
})().catch(e=>{console.error(e.message);process.exitCode=1;}).finally(()=>{for(const client of clients)client.socket.disconnect();for(const child of children){child.stdin.end('rollback\n');child.kill('SIGTERM');}});
setTimeout(()=>{for(const child of children)child.kill('SIGTERM');console.error('Named-origin transport deadline exceeded');process.exit(1);},210000).unref();
