/* Structural evidence: translation may change labels, never wire identifiers. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{execFileSync}=require('node:child_process');
const {createRequire}=require('node:module');
const parser=createRequire('/home/frappe/benches/hospitality-bench/apps/frappe/package.json')('@babel/parser');
const root=path.resolve(__dirname,'..');
function walk(node,fn){if(!node||typeof node!=='object')return;if(node.type)fn(node);for(const [key,value] of Object.entries(node)){
  if(['loc','extra','comments','leadingComments','trailingComments','innerComments'].includes(key))continue;
  if(Array.isArray(value))for(const v of value)walk(v,fn);else if(value&&typeof value==='object')walk(value,fn);
}}
function wires(source){
  const values=[];
  walk(parser.parse(source,{sourceType:'unambiguous'}),node=>{
    const add=(kind,n)=>{if(n?.type==='StringLiteral')values.push(kind+':'+n.value);};
    if(node.type==='ObjectProperty'&&['fieldname','value','doctype'].includes(node.key.name))add(node.key.name,node.value);
    if(node.type==='ObjectProperty'&&['action','operation','method'].includes(node.key.name)&&node.value.type==='StringLiteral'&&/^[A-Za-z0-9_.]+$/.test(node.value.value))add(node.key.name,node.value);
    if(node.type==='BinaryExpression'&&['===','!==','==','!='].includes(node.operator)){add('comparison',node.left);add('comparison',node.right);}
    if(node.type==='CallExpression'){
      const name=node.callee.name||node.callee.property?.name;
      if(['call','mutate','button'].includes(name))add(name,node.arguments[0]);
      if(['f','field','select','pick','n'].includes(name)){add('field',node.arguments[0]);add('field-type',node.arguments[2]);}
    }
  });
  return values.sort();
}
const files=fs.readdirSync(path.join(root,'hospitality_suite/public/js')).filter(n=>n.endsWith('.js')).map(n=>'hospitality_suite/public/js/'+n).concat('hospitality_suite/www/hospitality.js');
const proof=[];
for(const file of files){
  const previous=execFileSync('git',['-c','safe.directory='+root,'show','HEAD:'+file],{cwd:root,encoding:'utf8'});
  const before=wires(previous),after=wires(fs.readFileSync(path.join(root,file),'utf8'));
  // New security helpers introduce their own implementation literals; all old
  // protocol values must still exist, with their original occurrence counts.
  const counts=list=>list.reduce((m,k)=>(m[k]=(m[k]||0)+1,m),{}),old=counts(before),current=counts(after);
  const missing=Object.entries(old).filter(([k,n])=>(current[k]||0)<n);
  if(missing.length)throw new Error(file+': wire identifiers removed/translated: '+JSON.stringify(missing));
  proof.push({file,existing_wire_literals:before.length,unchanged:true,sha256:crypto.createHash('sha256').update(JSON.stringify(before)).digest('hex')});
}
fs.writeFileSync(path.join(root,'docs/evidence/localization-wire-invariants.json'),JSON.stringify({baseline:execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim(),files:proof},null,2)+'\n');
console.log('Verified existing wire literals in '+proof.length+' JavaScript sources');
