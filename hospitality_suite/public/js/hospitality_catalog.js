/* Search the shared catalogue without tying selection to bootstrap's first page. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const allowed=(row,purpose)=>!row.disabled&&(purpose==="sale"?row.is_sales_item&&!row.is_fixed_asset:purpose==="stock"?row.is_stock_item&&!row.is_fixed_asset:purpose==="purchase"?row.is_purchase_item&&!row.is_fixed_asset:true);
  const choices=(rows,required)=>{
    const names=new Map();for(const r of rows)names.set(r.item_name,(names.get(r.item_name)||0)+1);
    return [{value:"",label:__(required?"Seleccione…":"Todos")},...rows.map(r=>({value:r.name,label:r.item_name+(names.get(r.item_name)>1?" · "+r.name:"")}))];
  };
  Desk.prototype.item_field=function(label="Artículo",purpose="any",extra={}){
    return {fieldname:"item",label:__(label),fieldtype:"Select",reqd:1,_hsItemPurpose:purpose,...extra};
  };
  const dialog=Desk.prototype.dialog;
  Desk.prototype.dialog=async function(title,fields,submit,...args){
    const item=fields.find(df=>df._hsItemPurpose);
    if(!item)return dialog.call(this,title,fields,submit,...args);
    const searchName="_hs_item_search",initial=(this.data.items||[]).filter(r=>allowed(r,item._hsItemPurpose));
    let rows=initial.slice(0,50),pending=false,valid=true,revision=0,timer;
    item.options=choices(rows,item.reqd);
    item.description=__("Se muestran hasta 50 coincidencias. Busque por nombre o código para consultar todo el catálogo.");
    fields.splice(fields.indexOf(item),0,{fieldname:searchName,label:__("Buscar artículo por nombre o código"),fieldtype:"Data"});
    const d=await dialog.call(this,title,fields,async(values,active)=>{
      if(pending||!valid){frappe.msgprint(__("Espere a que termine la búsqueda. Si falló, vuelva a buscar."));return;}
      const clean={...values};delete clean[searchName];
      return submit(clean,active);
    },...args);
    const refresh=async()=>{
      const version=++revision;
      clearTimeout(timer);pending=true;valid=false;d._hsCatalogBlocked=true;d.get_primary_btn().prop("disabled",true);
      timer=setTimeout(async()=>{
        try{
          const result=await this.call("catalog_search",{property_name:this.property,txt:d.get_value(searchName)||"",purpose:item._hsItemPurpose});
          if(version!==revision||!d.$wrapper.is(":visible"))return;
          const selected=d.get_value(item.fieldname),previous=rows.find(r=>r.name===selected);
          rows=result.items;
          const retained=previous&&!rows.some(r=>r.name===previous.name);
          if(retained)rows=[previous,...rows];
          d.set_df_property(item.fieldname,"options",choices(rows,item.reqd));
          if(selected)await d.set_value(item.fieldname,selected);
          d.set_df_property(item.fieldname,"description",__(result.has_more?"Hay más de 50 coincidencias. Escriba más para afinar la búsqueda.":result.items.length?"Elija un artículo de los resultados.":"No hay artículos que coincidan con la búsqueda.")+(retained?" "+__("Se conserva el artículo seleccionado."):""));
          valid=true;d._hsCatalogBlocked=false;
        }catch(error){if(version===revision)d.set_df_property(item.fieldname,"description",__("No se pudo consultar el catálogo. Vuelva a buscar."));}
        finally{if(version===revision){pending=false;d.get_primary_btn().prop("disabled",!valid||Boolean(d._hsBusy));}}
      },250);
    };
    d.fields_dict[searchName].$input.on("input.hsCatalog",refresh);
    d.$wrapper.on("hidden.bs.modal.hsCatalog",()=>{revision++;clearTimeout(timer);});
    return d;
  };
})();
