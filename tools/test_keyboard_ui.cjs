const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');

// A small DOM boundary model. Actual browser Tab, Escape and native modal/grid
// behavior are checked separately in the acceptance walkthrough.
function fixture(){
  const document={activeElement:null,handlers:{},addEventListener(type,fn){this.handlers[type]=fn;}};
  class Element{
    constructor(tag,attrs={},children=[]){this.tagName=tag.toUpperCase();this.attrs={...attrs};this.children=[];this.disabled=false;this.readOnly=false;this.hidden=false;this._connected=true;this.clicks=0;this.classList={contains:value=>(this.attrs.class||'').split(' ').includes(value),add:value=>{if(!this.classList.contains(value))this.attrs.class=((this.attrs.class||'')+' '+value).trim();},remove:value=>{this.attrs.class=(this.attrs.class||'').split(' ').filter(c=>c!==value).join(' ');}};for(const child of children)this.append(child);}
    get id(){return this.attrs.id||'';}set id(value){this.attrs.id=value;}
    get tabIndex(){return this.attrs.tabindex!==undefined?Number(this.attrs.tabindex):['BUTTON','INPUT','SELECT','TEXTAREA','SUMMARY'].includes(this.tagName)||this.tagName==='A'&&this.attrs.href?0:-1;}set tabIndex(value){this.attrs.tabindex=String(value);}
    get isConnected(){return this._connected&&(!this.parentElement||this.parentElement.isConnected);}
    append(child){child.parentElement=this;this.children.push(child);return child;}
    remove(){this.parentElement.children=this.parentElement.children.filter(child=>child!==this);this._connected=false;}
    getAttribute(key){return this.attrs[key]??null;}setAttribute(key,value){this.attrs[key]=String(value);}hasAttribute(key){return key in this.attrs;}removeAttribute(key){delete this.attrs[key];}
    matches(selector){
      if(selector.includes(','))return selector.split(',').some(s=>this.matches(s.trim()));
      if(selector.includes(' ')){const parts=selector.split(' ');return this.matches(parts.at(-1))&&!!this.parentElement?.closest(parts.slice(0,-1).join(' '));}
      if(selector==='input:not([type="hidden"])')return this.tagName==='INPUT'&&this.attrs.type!=='hidden';
      const attribute=selector.match(/^([a-z]*)\[([^=\]]+)(?:="([^"]*)")?\]$/i);
      if(attribute)return (!attribute[1]||this.tagName===attribute[1].toUpperCase())&&(attribute[3]===undefined?attribute[2] in this.attrs:this.attrs[attribute[2]]===attribute[3]);
      const compound=selector.match(/^(\.[\w-]+)(\[.*\])$/);if(compound)return this.matches(compound[1])&&this.matches(compound[2]);
      if(selector.startsWith('.'))return selector.slice(1).split('.').every(name=>this.classList.contains(name));
      return this.tagName===selector.toUpperCase();
    }
    querySelectorAll(selector){return this.children.flatMap(child=>[...(child.matches(selector)?[child]:[]),...child.querySelectorAll(selector)]);}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    closest(selector){return this.matches(selector)?this:this.parentElement?.closest(selector)||null;}
    contains(node){return node===this||this.children.some(child=>child.contains(node));}
    getClientRects(){return !this.isConnected||this.hidden||this.parentElement&&!this.parentElement.getClientRects().length?[]:[{}];}
    focus(){document.activeElement=this;document.handlers.focusin?.({target:this});}
    click(){this.clicks++;this.onClick?.();}
    setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}
  }
  const el=(tag,attrs,children)=>new Element(tag,attrs,children);
  document.body=el('body');document.activeElement=document.body;
  document.querySelectorAll=selector=>document.body.querySelectorAll(selector);
  const root=document.body.append(el('main',{class:'hs-app'})),heading=root.append(el('h1'));
  const open_dialogs=[],events=new Map();class Desk{render(){this.onRender?.();}}
  const $=node=>{if(!events.has(node))events.set(node,{});return {0:node,on(type,...args){events.get(node)[type]=args.at(-1);return this;},off(type){delete events.get(node)[type];return this;},data(key){return node[key];}};};
  class NativeDialog{constructor(node){this.$wrapper=$(node);}show(){this.display=true;open_dialogs.push(this);for(const [type,fn] of Object.entries(events.get(document)||{}))if(type.startsWith('frappe.ui.Dialog:shown'))fn();for(const [type,fn] of Object.entries(events.get(this.$wrapper[0])||{}))if(type.startsWith('shown.'))fn();return this;}hide(){this.display=false;open_dialogs.splice(open_dialogs.indexOf(this),1);this.$wrapper[0].hidden=true;for(const [type,fn] of Object.entries(events.get(this.$wrapper[0])||{}))if(type.startsWith('hidden.'))fn();}}
  const originalShow=NativeDialog.prototype.show;
  const context={document,window:{location:{pathname:'/desk/hospitality-maintenance'},hospitality_suite:{Desk}},frappe:{ui:{open_dialogs,Dialog:NativeDialog}},$,__:(text,args)=>String(text).replace(/\{(\d+)\}/g,(_,n)=>args?.[n]??_)};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_keyboard.js'),'utf8'),context);
  const api=context.window.hospitality_suite.keyboard;
  function modal(){return document.body.append(el('div',{class:'modal show'},[el('h4',{class:'modal-title'}),el('button',{'aria-label':'Cerrar'})]));}
  const enter=modal=>{api.register(modal);const d={display:true,$wrapper:[modal]};open_dialogs.push(d);api.shown(modal);return d;};
  const leave=(modal,d)=>{d.display=false;open_dialogs.splice(open_dialogs.indexOf(d),1);modal.hidden=true;api.hidden(modal);};
  const key=(name,extra={})=>{const event={key:name,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;},...extra};api.keydown(event);return event;};
  return {api,document,root,heading,el,modal,enter,leave,key,open_dialogs,context,Desk,NativeDialog,originalShow};
}

test('a native modal is named and Tab cycles between enabled visible controls in both directions',()=>{
  const f=fixture(),m=f.modal(),first=m.children[1],hidden=m.append(f.el('input')),disabled=m.append(f.el('button')),last=m.append(f.el('button'));hidden.hidden=true;disabled.disabled=true;
  f.enter(m);assert.equal(m.getAttribute('aria-modal'),'true');assert.equal(m.getAttribute('aria-labelledby'),m.children[0].id);
  last.focus();assert.equal(f.key('Tab').prevented,true);assert.equal(f.document.activeElement,first);
  first.focus();assert.equal(f.key('Tab',{shiftKey:true}).prevented,true);assert.equal(f.document.activeElement,last);
  assert.equal(f.api.nodes(m).includes(hidden),false);assert.equal(f.api.nodes(m).includes(disabled),false);
});

test('tabs use one Tab stop, arrow wrapping and Home/End while hidden tabs and native selects stay independent',()=>{
  const f=fixture(),m=f.modal(),group=m.append(f.el('ul',{role:'tablist'}));
  const tabs=['one','two','hidden'].map((id,i)=>group.append(f.el('button',{role:'tab',id,'aria-controls':'pane-'+id,class:i===0?'active':''})));
  const panes=tabs.map(tab=>m.append(f.el('div',{id:'pane-'+tab.id,role:'tabpanel'})));tabs[2].hidden=true;
  for(const tab of tabs)tab.onClick=()=>{for(const t of tabs)t.attrs.class=t===tab?'active':'';};
  f.enter(m);assert.deepEqual(tabs.map(tab=>tab.tabIndex),[0,-1,-1]);tabs[0].focus();f.key('ArrowRight');assert.equal(f.document.activeElement,tabs[1]);
  assert.equal(tabs[1].getAttribute('aria-selected'),'true');assert.equal(panes[0].getAttribute('aria-hidden'),'true');f.key('ArrowRight');assert.equal(f.document.activeElement,tabs[0]);
  f.key('End');assert.equal(f.document.activeElement,tabs[1]);f.key('Home');assert.equal(f.document.activeElement,tabs[0]);
  const select=m.append(f.el('select'));select.focus();assert.equal(f.key('ArrowRight').prevented,undefined);assert.equal(tabs[0].clicks,2);
});

test('a read-only review starts on its title and never activates confirmation by focusing it',()=>{
  const f=fixture(),m=f.modal(),confirm=m.append(f.el('button'));f.enter(m);
  assert.equal(f.document.activeElement,m.children[0]);assert.equal(confirm.clicks,0);assert.equal(confirm.tabIndex,0);
});

test('Enter on No activates only No and cannot also reach the native global confirmation shortcut',()=>{
  const f=fixture(),m=f.modal(),yes=m.append(f.el('button')),no=m.append(f.el('button')),link=m.append(f.el('a',{href:'/receipt'}));f.enter(m);
  for(const active of [no,yes,link]){
    active.focus();const event=f.key('Enter');
    if(!event.stopped)yes.click(); // native global confirmation shortcut
    if(!event.prevented)active.click(); // browser default activation
    assert.equal(event.stopped,true);assert.equal(active.clicks,1);
  }
  assert.equal(yes.clicks,1);no.focus();assert.equal(f.key('Enter',{repeat:true}).prevented,true);
  const input=m.append(f.el('input'));input.focus();assert.equal(f.key('Enter').stopped,undefined,'input submission remains native');
});

test('a result dialog returns to the Page action when its filter parent closes first',()=>{
  const f=fixture(),opener=f.root.append(f.el('button',{'data-act':'report','data-id':'production'}));opener.focus();
  const filters=f.modal(),parent=f.enter(filters),query=filters.append(f.el('button'));query.focus();
  const results=f.modal(),child=f.enter(results);f.leave(filters,parent);
  assert.equal(f.api.states.has(results),true);assert.equal(f.document.activeElement,results.children[0]);
  f.leave(results,child);assert.equal(f.document.activeElement,opener);
});

test('native construction blurring onto body preserves the last Page action and nested parent trigger',()=>{
  const f=fixture(),opener=f.root.append(f.el('button',{'data-act':'report','data-id':'production'}));opener.focus();
  const filters=f.modal();f.document.activeElement=f.document.body;const parent=f.enter(filters),query=filters.append(f.el('button'));query.focus();
  const results=f.modal();f.document.activeElement=f.document.body;const child=f.enter(results);f.leave(filters,parent);f.leave(results,child);
  assert.equal(f.document.activeElement,opener);
});

test('an error field remains pending while a native message is opening and receives focus when that message closes',()=>{
  const f=fixture(),m=f.modal(),input=m.append(f.el('input'));const parent=f.enter(m);input.focus();
  const message=f.modal();f.api.register(message); // before Frappe pushes it at shown.bs.modal
  const desk=new f.Desk();desk.focus_form_error({$wrapper:[m]},{$input:[input]});assert.equal(m._hsErrorFocus,input);
  const child={display:true,$wrapper:[message]};f.open_dialogs.push(child);f.api.shown(message);f.leave(message,child);
  assert.equal(f.document.activeElement,input);assert.equal(m._hsErrorFocus,undefined);assert.equal(parent.display,true);
});

test('a native message in its opening transition preserves the field target before the public shown notification',()=>{
  const f=fixture(),m=f.modal(),input=m.append(f.el('input'));f.enter(m);input.focus();const message=f.modal();
  new f.Desk().focus_form_error({$wrapper:[m]},{$input:[input]});assert.equal(m._hsErrorFocus,input);
  const child=new f.NativeDialog(message);child.show();assert.equal(f.document.activeElement,message.children[0]);child.hide();assert.equal(f.document.activeElement,input);
});

test('cancelling a nested review restores the unchanged parent control after suspension is removed',()=>{
  const f=fixture(),parent=f.modal(),input=parent.append(f.el('input'));f.enter(parent);input.focus();
  const review=f.modal();const child=f.enter(review);parent.attrs.inert='';parent.attrs.class+=' hs-form-suspended';
  delete parent.attrs.inert;parent.attrs.class='modal show';f.leave(review,child);assert.equal(f.document.activeElement,input);
});

test('closing after a Page refresh finds the replacement action; a different route never receives the old focus',()=>{
  const f=fixture(),opener=f.root.append(f.el('button',{'data-act':'maintenance','data-id':'order'}));opener.focus();const m=f.modal(),d=f.enter(m);
  opener.remove();const replacement=f.root.append(f.el('button',{'data-act':'maintenance','data-id':'order'}));f.leave(m,d);assert.equal(f.document.activeElement,replacement);
  replacement.focus();const other=f.modal(),next=f.enter(other);f.context.window.location.pathname='/desk/another';f.leave(other,next);assert.notEqual(f.document.activeElement,replacement);
});

test('render keeps the active filter and caret or moves to the Page heading when that action no longer exists',()=>{
  const f=fixture(),desk=new f.Desk();desk.root=[f.root];const input=f.root.append(f.el('input',{id:'search'}));input.selectionStart=2;input.selectionEnd=4;input.focus();
  let next;desk.onRender=()=>{input.remove();next=f.root.append(f.el('input',{id:'search'}));};desk.render();assert.equal(f.document.activeElement,next);assert.equal(next.selectionStart,2);assert.equal(next.selectionEnd,4);
  const button=f.root.append(f.el('button',{'data-act':'gone','data-id':'old'}));button.focus();desk.onRender=()=>button.remove();desk.render();assert.equal(f.document.activeElement,f.heading);
});

test('unrelated native dialogs outside operational Pages are left to Frappe',()=>{
  const f=fixture();f.root.hidden=true;const m=f.modal(),d=f.enter(m);assert.equal(f.api.states.has(m),false);
  m.children[1].focus();assert.equal(f.key('Tab').prevented,undefined);assert.equal(d.display,true);
});

test('native lifecycle events delivered only on the exact wrapper still register and restore the dialog',()=>{
  const f=fixture(),opener=f.root.append(f.el('button'));opener.focus();const m=f.modal(),d=new f.NativeDialog(m);d.show();
  assert.equal(f.NativeDialog.prototype.show,f.originalShow);
  assert.equal(f.api.states.has(m),true);assert.equal(f.document.activeElement,m.children[0]);m.children[1].focus();f.key('Tab');assert.equal(f.document.activeElement,m.children[1]);
  d.hide();assert.equal(f.api.states.has(m),false);assert.equal(f.document.activeElement,opener);
});

test('a required checklist starts on its first checkbox and a summary remains in the native Tab cycle',()=>{
  const f=fixture(),m=f.modal(),first=m.append(f.el('input',{type:'checkbox'})),notes=m.append(f.el('textarea')),summary=m.append(f.el('summary'));
  notes.focus();f.enter(m);assert.equal(f.document.activeElement,first);assert.equal(f.api.nodes(m).includes(summary),true);
});

test('overflowing result tables get a named keyboard scroll region which is removed when it fits',()=>{
  const f=fixture(),wrap=f.root.append(f.el('div',{class:'hs-table-wrap'}));wrap.scrollWidth=500;wrap.clientWidth=250;f.api.prepare(f.root);
  assert.equal(wrap.tabIndex,0);assert.equal(wrap.getAttribute('role'),'region');assert.equal(wrap.getAttribute('aria-label'),'Tabla de resultados');
  wrap.clientWidth=500;f.api.prepare(f.root);assert.equal(wrap.hasAttribute('tabindex'),false);assert.equal(wrap.hasAttribute('role'),false);
});

test('editable grid cells have a keyboard action, read-only cells stay unchanged and inline inputs receive labels',()=>{
  const f=fixture(),m=f.modal(),row=m.append(f.el('div')),area=f.el('div',{class:'static-area'}),cell=row.append(f.el('div',{class:'grid-static-col','data-fieldname':'quantity'},[area]));
  cell.df={fieldname:'quantity',fieldtype:'Float',label:'Cantidad'};area.textContent='0';
  const read=row.append(f.el('div',{class:'grid-static-col','data-fieldname':'amount'},[f.el('div',{class:'static-area'})]));read.df={read_only:1,label:'Importe'};
  const d=f.enter(m);d.fields_dict={lines:{grid:{is_editable:()=>true,grid_rows:[{row:[row],doc:{idx:1}}]}}};f.api.prepare(m);
  assert.equal(cell.tabIndex,0);assert.equal(cell.getAttribute('aria-label'),'Editar Cantidad, fila 1. Valor: 0');assert.equal(read.hasAttribute('role'),false);
  let input;cell.onClick=()=>{area.hidden=true;input=cell.append(f.el('input'));input.focus();};cell.focus();const action=f.key('Enter');
  assert.equal(action.prevented,true);assert.equal(action.stopped,true);assert.equal(cell.clicks,1);assert.equal(cell.getAttribute('role'),null);assert.equal(input.getAttribute('aria-label'),'Cantidad');
});

test('Tab skips the native heading that inserts a row on focus and keeps the explicit Add row action reachable',()=>{
  const f=fixture(),m=f.modal(),gridRoot=m.append(f.el('div')),
    header=gridRoot.append(f.el('div',{class:'grid-heading-row'})),
    first=header.append(f.el('div',{class:'grid-static-col',tabindex:'0'})),
    add=gridRoot.append(f.el('button'));
  let rows=0;first.focus=()=>rows++;
  const d=f.enter(m);d.fields_dict={lines:{grid:{wrapper:[gridRoot],is_editable:()=>true,grid_rows:[]}}};f.api.prepare(m);
  assert.equal(first.tabIndex,-1);assert.equal(f.api.nodes(m).includes(first),false);
  assert.equal(f.api.nodes(m).includes(add),true);assert.equal(rows,0);
  add.focus();assert.equal(f.key('Tab').stopped,true);assert.equal(rows,0);
});

test('Tab in an inline grid preserves browser navigation and blur while stopping native row insertion in both directions',()=>{
  const f=fixture(),m=f.modal(),gridRoot=m.append(f.el('div')),input=gridRoot.append(f.el('input')),save=m.append(f.el('button'));
  const d=f.enter(m);d.fields_dict={lines:{grid:{wrapper:[gridRoot],is_editable:()=>true,grid_rows:[]}}};f.api.prepare(m);
  input.focus();const forward=f.key('Tab'),backward=f.key('Tab',{shiftKey:true});
  assert.equal(forward.stopped,true);assert.equal(backward.stopped,true);
  assert.equal(forward.prevented,undefined);assert.equal(backward.prevented,undefined);
  assert.equal(f.key('ArrowDown').stopped,undefined,'native Link autocomplete arrows stay native');
  save.focus();assert.equal(f.key('Tab',{shiftKey:true}).stopped,undefined,'other form controls keep native handlers');
});

test('Select arrows keep native option selection without triggering grid row navigation',()=>{
  const f=fixture(),m=f.modal(),gridRoot=m.append(f.el('div')),select=gridRoot.append(f.el('select')),outside=m.append(f.el('select'));
  const d=f.enter(m);d.fields_dict={lines:{grid:{wrapper:[gridRoot],is_editable:()=>true,grid_rows:[]}}};f.api.prepare(m);
  select.focus();
  for(const key of ['ArrowDown','ArrowUp']){
    const event=f.key(key);assert.equal(event.stopped,true);assert.equal(event.prevented,undefined,'browser default still selects the option');
    assert.equal(f.document.activeElement,select);
  }
  assert.equal(f.key('ArrowDown',{ctrlKey:true}).stopped,undefined,'modified shortcuts stay native');
  assert.equal(f.key('ArrowRight').stopped,undefined);
  outside.focus();assert.equal(f.key('ArrowDown').stopped,undefined,'other Select controls stay native');
});

test('a Select grid cell shows its option label in text and its accessible editing name while preserving the stored code',()=>{
  const f=fixture(),m=f.modal(),row=m.append(f.el('div')),area=f.el('div',{class:'static-area'}),
    cell=row.append(f.el('div',{class:'grid-static-col','data-fieldname':'basis'},[area]));
  cell.df={fieldname:'basis',fieldtype:'Select',label:'Frecuencia',options:[{value:'Stay',label:'Una vez por estancia'},{value:'Night',label:'Por noche (hotel)'}]};
  const doc={idx:1,basis:'Stay'},d=f.enter(m);d.fields_dict={lines:{grid:{is_editable:()=>true,grid_rows:[{row:[row],doc}]}}};
  f.api.prepare(m);assert.equal(doc.basis,'Stay');assert.equal(area.textContent,'Una vez por estancia');
  assert.equal(cell.getAttribute('aria-label'),'Editar Frecuencia, fila 1. Valor: Una vez por estancia');
  doc.basis='Night';f.api.prepare(m);assert.equal(area.textContent,'Por noche (hotel)');assert.equal(doc.basis,'Night');
  cell.df.options[1].label='<img src=x onerror=alert(1)>';f.api.prepare(m);
  assert.equal(area.textContent,'<img src=x onerror=alert(1)>','labels use textContent, never HTML');
});

test('grid actions are removed when their field or whole grid becomes read-only',()=>{
  const f=fixture(),m=f.modal(),gridRoot=m.append(f.el('div')),row=gridRoot.append(f.el('div')),
    cell=row.append(f.el('div',{class:'grid-static-col','data-fieldname':'quantity'},[f.el('div',{class:'static-area'})]));
  cell.df={fieldname:'quantity',label:'Cantidad'};let editable=true;
  const d=f.enter(m);d.fields_dict={lines:{grid:{wrapper:[gridRoot],is_editable:()=>editable,grid_rows:[{row:[row],doc:{idx:1}}]}}};
  f.api.prepare(m);assert.equal(cell.getAttribute('role'),'button');
  cell.df.read_only=1;f.api.prepare(m);assert.equal(cell.getAttribute('role'),null);assert.equal(cell.getAttribute('data-hs-grid-action'),null);
  cell.df.read_only=0;f.api.prepare(m);assert.equal(cell.getAttribute('role'),'button');
  editable=false;f.api.prepare(m);assert.equal(cell.getAttribute('role'),null);assert.equal(cell.hasAttribute('tabindex'),false);
  assert.equal(gridRoot.classList.contains('hs-keyboard-grid'),false);
});

test('activating a Select cell focuses its editor even when the native click only reveals it',()=>{
  const f=fixture(),m=f.modal(),row=m.append(f.el('div')),area=f.el('div',{class:'static-area'}),
    cell=row.append(f.el('div',{class:'grid-static-col','data-fieldname':'basis'},[area]));
  cell.df={fieldname:'basis',fieldtype:'Select',label:'Frecuencia'};
  const d=f.enter(m);d.fields_dict={lines:{grid:{is_editable:()=>true,grid_rows:[{row:[row],doc:{idx:1,basis:'Stay'}}]}}};
  let select;cell.onClick=()=>{area.hidden=true;select=cell.append(f.el('select'));};
  f.api.prepare(m);cell.focus();f.key('Enter');
  assert.equal(f.document.activeElement,select);assert.equal(select.getAttribute('aria-label'),'Frecuencia');
  assert.equal(cell.getAttribute('data-hs-grid-action'),null);assert.equal(cell.getAttribute('role'),null);
});

test('focusing a native grid outside operational Pages does not prepare or change its controls',()=>{
  const f=fixture();f.root.hidden=true;
  const m=f.modal(),gridRoot=m.append(f.el('div')),header=gridRoot.append(f.el('div',{class:'grid-heading-row'})),
    heading=header.append(f.el('div',{class:'grid-static-col',tabindex:'0'})),row=gridRoot.append(f.el('div')),
    cell=row.append(f.el('div',{class:'grid-static-col','data-fieldname':'quantity'},[f.el('div',{class:'static-area'})])),input=row.append(f.el('input'));
  cell.df={fieldname:'quantity',label:'Cantidad'};
  const d=f.enter(m);d.fields_dict={lines:{grid:{wrapper:[gridRoot],is_editable:()=>true,grid_rows:[{row:[row],doc:{idx:1}}]}}};
  input.focus();f.api.prepare(m);
  assert.equal(f.api.states.has(m),false);assert.equal(heading.tabIndex,0);
  assert.equal(cell.getAttribute('role'),null);assert.equal(gridRoot.classList.contains('hs-keyboard-grid'),false);
  assert.equal(f.key('Tab').stopped,undefined);
});

test('operational field-name tooltips are excluded from spoken labels while unrelated dialogs stay unchanged',()=>{
  const f=fixture(),m=f.modal(),tip=m.append(f.el('span',{class:'tooltip-content'}));tip.textContent='amount';f.enter(m);f.api.prepare(m);
  assert.equal(tip.getAttribute('aria-hidden'),'true');assert.equal(tip.textContent,'amount');
  const other=f.modal(),native=other.append(f.el('span',{class:'tooltip-content'}));f.api.prepare(other);
  assert.equal(native.getAttribute('aria-hidden'),null);
});

test('the native mobile menu receives a label only inside the operational Page container',()=>{
  const f=fixture(),page=f.el('div',{class:'page-container'}),header=page.append(f.el('div',{class:'page-head'})),menu=header.append(f.el('button',{class:'sidebar-toggle-btn'}));
  f.document.body.children=[];f.document.body.append(page);page.append(f.root);
  const other=f.document.body.append(f.el('div',{class:'page-container'})),otherHeader=other.append(f.el('div',{class:'page-head'})),native=otherHeader.append(f.el('button',{class:'sidebar-toggle-btn'}));
  f.api.prepare(f.root);assert.equal(menu.getAttribute('aria-label'),'Menú de navegación');assert.equal(menu.classList.contains('hs-keyboard-menu'),true);
  assert.equal(native.getAttribute('aria-label'),null);assert.equal(native.classList.contains('hs-keyboard-menu'),false);
  menu.setAttribute('aria-label','Nombre nativo');f.api.prepare(f.root);assert.equal(menu.getAttribute('aria-label'),'Nombre nativo');
});
