// Static Page action/RPC inventory. This is not a substitute for UI acceptance.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{createRequire}=require('node:module');
const parser=createRequire('/home/frappe/benches/hospitality-bench/apps/frappe/package.json')('@babel/parser');
const root=path.resolve(__dirname,'..'),folder=path.join(root,'hospitality_suite/public/js');
const handlers={},buttons=[],dynamic=[],rpc=[],mutations=[],sources={};
const bundle='hospitality_suite/public/hospitality.bundle.js',bundleSource=fs.readFileSync(path.join(root,bundle),'utf8');
const imports=parser.parse(bundleSource,{sourceType:'module'}).program.body.filter(node=>node.type==='ImportDeclaration').map(node=>node.source.value);
if(!imports.every(name=>/^\.\/js\/[a-z_]+\.js$/.test(name)))throw Error('Review nonliteral/local bundle dependency before inferring load order');
const loadOrder=imports.map(name=>name.split('/').at(-1));
if(new Set(loadOrder).size!==loadOrder.length)throw Error('Duplicate bundle imports need explicit review');
const diskFiles=fs.readdirSync(folder).filter(name=>name.endsWith('.js')).sort();
if(JSON.stringify([...loadOrder].sort())!==JSON.stringify(diskFiles))throw Error('Inventory must account for every loaded and unloaded source');
sources[bundle]=crypto.createHash('sha256').update(bundleSource).digest('hex');
function walk(node,fn,parents=[]){if(!node||typeof node!=='object')return;if(node.type)fn(node,parents);for(const [key,value] of Object.entries(node)){
 if(['loc','extra','comments','leadingComments','trailingComments','innerComments'].includes(key))continue;
 if(Array.isArray(value))for(const item of value)walk(item,fn,[node,...parents]);else if(value&&typeof value==='object')walk(value,fn,[node,...parents]);
}}
const strings=node=>node?.type==='StringLiteral'?[node.value]:node?.type==='ConditionalExpression'?[...strings(node.consequent),...strings(node.alternate)]:[];
const rowActions=node=>node?.type==='ArrayExpression'?node.elements.flatMap(row=>row?.type==='ArrayExpression'?strings(row.elements[0]):[]):node?.type==='ConditionalExpression'?[...rowActions(node.consequent),...rowActions(node.alternate)]:[];
for(const name of loadOrder){
 const file='hospitality_suite/public/js/'+name,source=fs.readFileSync(path.join(root,file),'utf8');sources[file]=crypto.createHash('sha256').update(source).digest('hex');
 const add=(name,node)=>{if(!name.startsWith('action_'))return;(handlers[name.slice(7)]??=[]).push({file,line:node.loc.start.line});};
 walk(parser.parse(source,{sourceType:'unambiguous'}),(node,parents)=>{
  if(['ClassMethod','ObjectMethod'].includes(node.type))add(node.key.name||node.key.value||'',node);
  if(node.type==='AssignmentExpression'&&node.left.type==='MemberExpression'){
   const key=node.left.property;const names=key.type==='Identifier'&&!node.left.computed?[key.name]:strings(key);
   for(const value of names)add(value,node);
   if(!names.length&&key.type==='TemplateLiteral'&&key.quasis.some(q=>q.value.raw.includes('action_')))
    dynamic.push({kind:'computed_handler',file,line:node.loc.start.line,source:source.slice(node.start,node.end).slice(0,600)});
  }
  if(node.type==='CallExpression'){
   const method=node.callee.type==='MemberExpression'&&!node.callee.computed?node.callee.property.name:null;
   if(!['button','call','mutate'].includes(method))return;
   const names=strings(node.arguments[0]);const record={file,line:node.loc.start.line};
   if(!names.length){if(method==='button'){
    let resolved=[];
    const parameter=node.arguments[0];
    if(parameter?.type==='Identifier'){
     const scope=parents.find(parent=>['ArrowFunctionExpression','ClassMethod','FunctionExpression'].includes(parent.type));
     const declarations=[];walk(scope,child=>{if(child.type==='VariableDeclarator'&&child.id.name===parameter.name)declarations.push(child);});
     if(declarations.length===1)resolved=strings(declarations[0].init).filter(Boolean);
     if(!resolved.length&&scope?.params?.[0]?.type==='ArrayPattern'&&scope.params[0].elements[0]?.name===parameter.name){
      const owner=parents.find(parent=>parent.type==='ClassMethod');const arrays=[];
      walk(owner,child=>{if(child.type==='VariableDeclarator'&&child.id.name==='actions')arrays.push(child);});
      if(arrays.length===1)resolved=rowActions(arrays[0].init);
     }
    }
    dynamic.push({kind:'computed_button',...record,resolved_actions:resolved,source:source.slice(node.start,node.end).slice(0,600)});
   }return;}
   for(const name of names)(method==='button'?buttons:method==='call'?rpc:mutations).push({name,...record});
  }
  if(node.type==='TemplateElement'){
   for(const match of node.value.raw.matchAll(/data-act=["']([a-z][a-z0-9_]*)["']/g))buttons.push({name:match[1],file,line:node.loc.start.line,source:'literal HTML attribute'});
  }
 });
}
const dynamicActions=dynamic.flatMap(row=>row.resolved_actions||[]);
const unbound=[...new Set([...buttons.map(row=>row.name),...dynamicActions].filter(name=>!handlers[name]))].sort();
const effectiveHandlers=Object.fromEntries(Object.entries(handlers).map(([name,definitions])=>[name,definitions.at(-1)]));
const proof={scope:'Static literal action/RPC bindings in explicit bundle load order; dynamic bindings listed for review, no UI replay and no behavioral completion claim.',
 sources_sha256:sources,load_order:loadOrder,handler_count:Object.keys(handlers).length,handlers,effective_handlers:effectiveHandlers,buttons,rpc,mutations,dynamic_bindings:dynamic,unbound_literal_actions:unbound,
 unresolved_dynamic_buttons:dynamic.filter(row=>row.kind==='computed_button'&&!row.resolved_actions?.length).length};
fs.writeFileSync(path.join(root,'docs/evidence/phase-review-actions.json'),JSON.stringify(proof,null,2)+'\n');
console.log(JSON.stringify({sources:Object.keys(sources).length,handlers:proof.handler_count,button_occurrences:buttons.length,unbound_literal_actions:unbound,dynamic_bindings:dynamic}));
