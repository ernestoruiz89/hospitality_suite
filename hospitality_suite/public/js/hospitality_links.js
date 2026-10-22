/* Human labels on operational Links; native search, validation and keys remain. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  Desk.prototype.prepare_operational_links=function(fields){
    const data=this.data||{},prop=this.prop||{},escape=value=>frappe.utils.escape_html(String(value??""));
    const maps={
      "HS Category":new Map((data.categories||[]).map(row=>[row.name,row])),
      "HS Room":new Map((data.rooms||[]).map(row=>[row.name,row])),
      "HS Rate":new Map((data.rates||[]).map(row=>[row.name,row]))};
    const captions={"HS Category":__("Categoría del establecimiento"),"HS Room":__("Habitación del establecimiento"),"HS Rate":__("Tarifa del establecimiento")};
    const display=(doctype,item)=>{
      const record=maps[doctype].get(item.value),labelKey={"HS Category":"category_name","HS Room":"room_number","HS Rate":"title"}[doctype];
      const label=item.label&&item.label!==item.value?item.label:record?.[labelKey]||captions[doctype];
      let description="";
      if(doctype==="HS Category"&&record?.capacity)description=__("Capacidad: {0} personas",[record.capacity]);
      if(doctype==="HS Room"&&record){
        const category=maps["HS Category"].get(record.category)?.category_name;
        description=[category?__("Categoría: {0}",[category]):"",record.active===0?__("Habitación no habilitada"):""].filter(Boolean).join(" · ");
      }
      if(doctype==="HS Rate"&&record){
        const mode={Hotel:__("Hotel"),"Por tiempo":__("Por tiempo"),Mixed:__("Hotel y por tiempo")}[record.mode]||"";
        description=[mode,__("Precio base: {0}",[this.amount(record.amount,record.currency)])].filter(Boolean).join(" · ");
      }
      // Frappe 16 decodes descriptions once before inserting their HTML.
      // Encode our data text first; native label rendering escapes labels itself.
      const result={...item,label,description:escape(description)};delete result.html;return result;
    };
    const visit=(definitions,child=false)=>{for(const df of definitions||[]){
      if(df.fieldtype==="Table")visit(df.fields,true);
      const operational=df.fieldtype==="Link"&&Object.hasOwn(maps,df.options);
      if((!operational&&!child)||df._hsOperationalControl)continue;
      const doctype=df.options,previous=df.on_make;
      df._hsOperationalControl=true;
      if(operational){
        df.only_select=1;
        df.filter_description=escape(__("Opciones de {0}",[prop.brand_name||prop.property_name||__("este establecimiento")]));
      }
      df.on_make=function(control){
        previous?.call(this,control);
        const input=control.$input?.[0];
        if(input&&!input.getAttribute("aria-label")&&!input.getAttribute("aria-labelledby")&&!input.labels?.length)input.setAttribute("aria-label",__(control.df?.label||df.label||df.fieldname));
        if(!operational||control._hsOperationalLink||typeof control.merge_duplicates!=="function")return;
        const merge=control.merge_duplicates;
        control._hsOperationalLink=true;
        control.merge_duplicates=function(results){return merge.call(this,(results||[]).map(row=>({...row}))).map(item=>display(doctype,item));};
      };
    }};
    visit(fields);
  };
})();
