/* Keyboard behavior for operational Pages and their native Frappe dialogs. */
(() => {
  const ns=window.hospitality_suite,Desk=ns.Desk,states=new WeakMap(),rootFocus=new WeakMap(),stack=[];let sequence=0;
  const visible=node=>Boolean(node?.isConnected&&!node.disabled&&node.getAttribute?.('aria-disabled')!=='true'&&!node.closest?.('[inert],.hs-form-suspended')&&node.getClientRects?.().length);
  const nodes=root=>Array.from(root?.querySelectorAll('a[href],button,input:not([type="hidden"]),select,textarea,summary,[tabindex],[contenteditable="true"]')||[])
    .filter(node=>visible(node)&&node.tabIndex>=0)
    .map((node,index)=>({node,index,order:node.tabIndex>0?node.tabIndex:Infinity}))
    .sort((a,b)=>a.order-b.order||a.index-b.index).map(row=>row.node);
  const top=()=>{const core=frappe.ui.open_dialogs?.filter(dialog=>dialog.display).at(-1)?.$wrapper?.[0];return core&&!states.has(core)?core:stack.at(-1)||core;};
  const scope=()=>Array.from(document.querySelectorAll('.hs-app')).find(visible);
  const describe=(node,root)=>({node,root,path:window.location.pathname,id:node?.id,
    action:node?.getAttribute?.('data-act'),reference:node?.getAttribute?.('data-id'),href:node?.getAttribute?.('href'),
    caret:node?.selectionStart==null?null:[node.selectionStart,node.selectionEnd]});
  const find=origin=>{
    const root=visible(origin.root)?origin.root:scope();if(!root||origin.path!==window.location.pathname)return null;
    if(visible(origin.node)&&root.contains(origin.node))return origin.node;
    const found=Array.from(root.querySelectorAll('[id],[data-act],a[href]')).find(node=>visible(node)&&(
      origin.id&&node.id===origin.id||origin.action&&node.getAttribute('data-act')===origin.action&&node.getAttribute('data-id')===origin.reference||origin.href&&node.getAttribute('href')===origin.href));
    if(found)return found;
    const heading=root.querySelector('h1');if(heading)heading.tabIndex=-1;return heading;
  };
  const focus=node=>{if(visible(node)){node.focus();return true;}return false;};
  const clearGridAction=cell=>{
    if(!cell.classList.contains('hs-grid-editor'))return;
    cell.classList.remove('hs-grid-editor');for(const key of ['tabindex','role','data-hs-grid-action','aria-label'])cell.removeAttribute(key);
  };
  const prepare=root=>{
    if(!root||root.classList?.contains('modal')&&!states.has(root))return;
    if(root.classList?.contains('hs-app'))for(const button of root.closest('.page-container')?.querySelectorAll('.page-head .sidebar-toggle-btn')||[]){
      if(!button.getAttribute('aria-label'))button.setAttribute('aria-label',__('Menú de navegación'));
      button.classList.add('hs-keyboard-menu');
    }
    // Native field-name copy tooltips are developer hints, not spoken labels.
    for(const tip of root.querySelectorAll('.tooltip-content'))tip.setAttribute('aria-hidden','true');
    for(const wrap of root.querySelectorAll('.hs-table-wrap')){
      if(wrap.scrollWidth>wrap.clientWidth+1&&!wrap.hasAttribute('tabindex')){wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label',__('Tabla de resultados'));wrap.setAttribute('data-hs-scroll-region','true');}
      else if(wrap.getAttribute('data-hs-scroll-region')&&wrap.scrollWidth<=wrap.clientWidth+1)for(const key of ['tabindex','role','aria-label','data-hs-scroll-region'])wrap.removeAttribute(key);
    }
    const dialog=frappe.ui.open_dialogs?.find(entry=>entry.$wrapper?.[0]===root);
    for(const control of Object.values(dialog?.fields_dict||{})){
      const grid=control.grid;if(!grid)continue;
      const gridRoot=grid.wrapper?.[0],editable=grid.is_editable?.();
      // Frappe's first heading cell opens an editor and adds an empty row on
      // focus. Navigation must reach the explicit Add row button without
      // changing the form. Only data cells are keyboard editing actions.
      for(const cell of gridRoot?.querySelectorAll('.grid-heading-row .grid-static-col')||[])cell.tabIndex=-1;
      if(!editable){gridRoot?.classList.remove('hs-keyboard-grid');for(const cell of gridRoot?.querySelectorAll('.hs-grid-editor')||[])clearGridAction(cell);continue;}
      gridRoot?.classList.add('hs-keyboard-grid');
      for(const check of grid.wrapper?.[0]?.querySelectorAll('.grid-heading-row .row-check input[type="checkbox"]')||[]){check.tabIndex=0;check.setAttribute('aria-label',__('Seleccionar todas las filas'));}
      for(const row of grid.grid_rows||[]){
        const wrapper=row.row?.[0];if(!wrapper)continue;
        for(const check of wrapper.querySelectorAll('.row-check input[type="checkbox"]'))if(!check.getAttribute('aria-label')&&!check.labels?.length)check.setAttribute('aria-label',__('Seleccionar fila {0}',[row.doc.idx]));
        for(const col of wrapper.querySelectorAll('.grid-static-col[data-fieldname]')){
          const df=$(col).data('df');if(!df||df.read_only||df.hidden){clearGridAction(col);continue;}
          const area=col.querySelector('.static-area');if(!area)continue;
          // Native static Select cells render the stored code, even when their
          // editor has value/label options. Show the same label in both views.
          if(df.fieldtype==='Select'&&Array.isArray(df.options)){
            const option=df.options.find(entry=>entry&&typeof entry==='object'&&String(entry.value)===String(row.doc[df.fieldname]));
            if(option?.label!=null)area.textContent=df._hsDataOptions?String(option.label):__(String(option.label),null,df.context||df.parent);
          }
          const staticCell=visible(area);col.tabIndex=staticCell?0:-1;col.classList.add('hs-grid-editor');
          if(staticCell){col.setAttribute('role','button');col.setAttribute('data-hs-grid-action','cell');col.setAttribute('aria-label',__('Editar {0}, fila {1}. Valor: {2}',[__(df.label),row.doc.idx,area.textContent?.trim()||__('Sin valor')]));}
          else for(const key of ['role','data-hs-grid-action','aria-label'])col.removeAttribute(key);
          for(const input of col.querySelectorAll('input:not([type="hidden"]),select,textarea'))if(!input.getAttribute('aria-label')&&!input.getAttribute('aria-labelledby')&&!input.labels?.length)input.setAttribute('aria-label',__(df.label));
        }
        const open=wrapper.querySelector('.btn-open-row')?.parentElement;
        if(open){open.tabIndex=0;open.classList.add('hs-grid-editor');open.setAttribute('role','button');open.setAttribute('data-hs-grid-action','row');open.setAttribute('aria-label',__('Editar fila {0}',[row.doc.idx]));}
      }
    }
  };
  const focusOrigin=origin=>{
    const target=find(origin);if(!focus(target))return;
    if(origin.caret&&typeof target.setSelectionRange==='function')target.setSelectionRange(...origin.caret);
  };
  const heading=modal=>{
    const node=modal.querySelector('.modal-title');if(!node)return null;
    if(!node.id)node.id='hs-dialog-title-'+(++sequence);
    node.tabIndex=-1;modal.setAttribute('aria-labelledby',node.id);return node;
  };
  const syncTabs=modal=>{
    const groups=new Map();
    for(const tab of modal?.querySelectorAll('[role="tab"]')||[]){const group=tab.closest('[role="tablist"]')||tab.parentElement.parentElement;if(!groups.has(group))groups.set(group,[]);groups.get(group).push(tab);}
    for(const tabs of groups.values()){
      const available=tabs.filter(visible),active=available.find(tab=>tab.classList.contains('active')),stop=active||available[0];
      if(!available.length)continue;
      for(const tab of tabs){
        tab.tabIndex=tab===stop?0:-1;tab.setAttribute('aria-selected',String(tab===active));
        const pane=Array.from(modal.querySelectorAll('[role="tabpanel"]')).find(node=>node.id===tab.getAttribute('aria-controls'));
        if(pane){pane.setAttribute('aria-hidden',String(tab!==active));pane.tabIndex=tab===active&&!nodes(pane).length?0:-1;}
      }
    }
  };
  const restore=state=>{
    const modal=top(),parent=states.get(modal),pending=modal?._hsErrorFocus;
    if(focus(pending)){delete modal._hsErrorFocus;return;}
    if(modal){if(state.origin.node&&modal.contains(state.origin.node)&&focus(state.origin.node))return;focus(parent?.last)||focus(heading(modal));return;}
    const current=document.activeElement;
    if(current!==document.body&&visible(current)&&!current.closest('.modal'))return;
    focusOrigin(state.origin);
  };
  const register=modal=>{
    if(!modal?.classList?.contains('modal'))return;
    const root=scope(),parent=stack.at(-1);if(!root&&!states.has(parent))return;
    const active=document.activeElement;
    // Native construction can blur the trigger onto body before registration.
    // Only an element in the Page or parent dialog can be a usable opener.
    const opener=visible(active)&&!modal.contains(active)&&(root?.contains(active)||parent?.contains(active))?active:states.get(parent)?.last||rootFocus.get(root);
    const state={origin:describe(opener,root||states.get(parent)?.origin.root),last:null};states.set(modal,state);stack.push(modal);
    modal.classList.add('hs-keyboard-dialog');modal.setAttribute('role','dialog');modal.setAttribute('aria-modal','true');heading(modal);
  };
  const shown=modal=>{
    if(!states.has(modal))return;prepare(modal);syncTabs(modal);
    const inputs=nodes(modal).filter(node=>['INPUT','SELECT','TEXTAREA'].includes(node.tagName)&&!node.readOnly);
    if(!inputs.length)focus(heading(modal));else focus(inputs.find(input=>input.autofocus)||inputs[0]);
  };
  const keydown=event=>{
    const modal=top();if(!states.has(modal)||event.altKey||event.ctrlKey||event.metaKey)return;
    prepare(modal);const active=document.activeElement;
    // Native grid row navigation also intercepts Select arrows. Let the
    // browser choose an option without moving to another row. Link inputs
    // retain Frappe's autocomplete keys.
    if(active?.tagName==='SELECT'&&active.closest('.hs-keyboard-grid')&&['ArrowUp','ArrowDown'].includes(event.key)){
      event.stopPropagation();return;
    }
    if(event.key==='Tab'){
      // Native inline-grid Tab adds a new row after its last input. Keep
      // browser focus order and blur validation, requiring an explicit action
      // to add rows. Other keys (including Link selection) remain native.
      if(active?.closest('.hs-keyboard-grid'))event.stopPropagation();
      const list=nodes(modal),index=list.indexOf(active);
      if(!list.length){event.preventDefault();focus(heading(modal));}
      else if(!modal.contains(active)||index===-1&&event.shiftKey||index===0&&event.shiftKey||index===list.length-1&&!event.shiftKey){event.preventDefault();focus(event.shiftKey?list.at(-1):list[0]);}
      return;
    }
    // Frappe's global Enter shortcut clicks the primary confirmation action.
    // A focused native button/link already has its own browser activation;
    // prevent a second click (and keep Enter on No from also choosing Yes).
    if(event.key==='Enter'&&(active?.tagName==='BUTTON'||active?.tagName==='A'&&active.hasAttribute('href'))&&modal.contains(active)){
      event.stopPropagation();if(event.repeat)event.preventDefault();return;
    }
    if(active?.getAttribute('data-hs-grid-action')&&['Enter',' '].includes(event.key)&&!event.repeat){
      const action=active.getAttribute('data-hs-grid-action');event.preventDefault();event.stopPropagation();active.click();prepare(modal);
      // Native grid clicks focus text inputs only. A Select or checkbox editor
      // also needs focus after activation, without an extra Tab or mouse click.
      if(action==='cell')focus(nodes(active).find(node=>['INPUT','SELECT','TEXTAREA'].includes(node.tagName)&&!node.readOnly));
      return;
    }
    if(active?.getAttribute('role')!=='tab'||!modal.contains(active))return;
    const group=active.closest('[role="tablist"]')||active.parentElement.parentElement,vertical=group.getAttribute('aria-orientation')==='vertical';
    const next=vertical?'ArrowDown':'ArrowRight',previous=vertical?'ArrowUp':'ArrowLeft';
    if(![next,previous,'Home','End'].includes(event.key))return;
    const tabs=Array.from(group.querySelectorAll('[role="tab"]')).filter(visible),index=tabs.indexOf(active);
    const target=tabs[event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key===next?1:-1)+tabs.length)%tabs.length];
    if(target){event.preventDefault();target.click();syncTabs(modal);focus(target);}
  };
  const hidden=modal=>{const state=states.get(modal);if(state){
    // Reports open their result before hiding the filters. If that parent
    // closes first, the surviving child must return to the parent's opener.
    for(const child of stack){const next=states.get(child);if(child!==modal&&next?.origin.node&&modal.contains(next.origin.node))next.origin=state.origin;}
    const index=stack.indexOf(modal);if(index>=0)stack.splice(index,1);modal.classList.remove('hs-keyboard-dialog');states.delete(modal);restore(state);
  }};
  ns.keyboard={visible,nodes,describe,find,focus,prepare,syncTabs,register,shown,keydown,restore,hidden,states};
  const attach=dialog=>{
    const modal=dialog.$wrapper?.[0];if(!states.has(modal))register(modal);
    if(states.has(modal))dialog.$wrapper
      .off('shown.bs.modal.hsKeyboard').on('shown.bs.modal.hsKeyboard',()=>shown(modal))
      .off('hidden.bs.modal.hsKeyboard').on('hidden.bs.modal.hsKeyboard',()=>hidden(modal))
      .off('click.hsKeyboard').on('click.hsKeyboard','[role="tab"]',()=>syncTabs(modal));
  };
  Desk.prototype.prepare_keyboard_dialog=attach;
  Desk.prototype.focus_form_error=function(dialog,field){
    const modal=dialog.$wrapper?.[0],control=field?.$input?.[0]||field?.$wrapper?.[0]?.querySelector?.('input,select,textarea,[tabindex]');
    if(!modal||!control)return;modal._hsErrorFocus=control;
    const opening=typeof document!=='undefined'&&Array.from(document.querySelectorAll('.modal.show')).some(other=>other!==modal&&!states.has(other)&&visible(other));
    if(!opening&&top()===modal&&focus(control))delete modal._hsErrorFocus;
  };
  const render=Desk.prototype.render;
  Desk.prototype.render=function(...args){
    const root=this.root?.[0],active=typeof document==='undefined'?null:document.activeElement,origin=root?.contains(active)?describe(active,root):null;
    const result=render.apply(this,args);
    prepare(this.root?.[0]);
    if(origin&&!top())focusOrigin(origin);
    return result;
  };
  if(typeof document!=='undefined'){
    // Common forms attach before show. Native messages, account views and row
    // dialogs use Frappe's public shown notification, then direct lifecycle
    // listeners on their own wrapper; no framework prototype is replaced.
    $(document).on('frappe.ui.Dialog:shown.hsKeyboard',()=>{
      const dialog=frappe.ui.open_dialogs?.at(-1),modal=dialog?.$wrapper?.[0];
      if(dialog&&!states.has(modal)){attach(dialog);shown(modal);}
    });
    document.addEventListener('keydown',event=>{if(!top())prepare(scope());keydown(event);},true);
    document.addEventListener('focusin',event=>{const modal=top(),state=states.get(modal),root=scope();prepare(modal||root);if(root?.contains(event.target))rootFocus.set(root,event.target);if(state&&modal.contains(event.target))state.last=event.target;});
  }
})();
