/* Complete server queries, bounded visible pages, and complete exports. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const e=x=>frappe.utils.escape_html(String(x??""));
  const field=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),fieldtype:["Date","Datetime"].includes(fieldtype)?"Data":fieldtype,_hsDateTime:fieldtype==="Datetime",_hsDate:fieldtype==="Date",...extra});
  const choice=(name,label,rows,labelKey)=>field(name,label,"Select",{_hsDataOptions:true,options:[{value:"",label:__("Todos")},...rows.map(row=>({value:row.name,label:row[labelKey]||row.name}))]});

  Desk.prototype.show_paged=async function(title,method,args,reportName){
    const allowedExport=reportName&&(frappe.session.user==="Administrator"||["System Manager","HS Administrator","HS Manager","HS Accountant"].some(role=>frappe.user.has_role(role)));
    let result=await this.call(method,{...args,offset:0,page_length:50});
    const value=(key,v,row)=>{
      if(Object.hasOwn(row._display||{},key))return e(row._display[key]);
      if(key==="selected_room_available"&&v!==null&&v!==undefined)return e(v?__("Sí"):__("No"));
      if(["amount","grand_total","outstanding_amount","base_amount","expected_amount","counted_amount","difference","cost","expected","actual","pending","outstanding","fee_amount","withholding_amount","net_amount","revenue_net","pending_amount","penalty_amount","expense_total","expected_cash","counted_cash","variance"].includes(key)&&v!==null&&v!==undefined&&v!=="")return e(this.amount(v,key==="base_amount"?row.base_currency:row.currency));
      if(key==="room"&&v)return e(this.roomName(v));
      if(["starts_at","ends_at","actual_check_in","actual_check_out"].includes(key))return e(this.date(v));
      return e(["status","kind","type","cleaning_status","settlement_direction","purpose","classification","relationship","adjustment_type"].includes(key)?this.data.report_values?.[v]||v:v);
    };
    const audit=reportName==='Auditoría';
    const html=()=>`<p role="status">${result.total?`${result.offset+1}–${Math.min(result.offset+result.rows.length,result.total)}`:"0"} ${frappe.utils.escape_html(__("de"))} ${result.total} ${frappe.utils.escape_html(__("registros"))}</p>${result.rows.length?this.table([...result.columns.map(key=>this.data.report_labels?.[key]||key),...(audit?[__('Detalle')]:[])],result.rows.map(row=>[...result.columns.map(key=>value(key,row[key],row)),...(audit?[`<button type="button" class="btn btn-secondary" data-hs-audit="${e(row.name)}">${e(__('Ver cambio'))}</button>`]:[])])):this.empty(__("No hay registros para estos filtros."))}<div class="hs-dialog-actions"><button type="button" class="btn btn-secondary" data-hs-page="previous" ${result.offset===0?"disabled":""}>${frappe.utils.escape_html(__("Anterior"))}</button><button type="button" class="btn btn-secondary" data-hs-page="next" ${!result.has_more?"disabled":""}>${frappe.utils.escape_html(__("Siguiente"))}</button>${allowedExport?`<button type="button" class="btn btn-secondary" data-hs-export="xlsx">${frappe.utils.escape_html(__("Exportar XLSX completo"))}</button><button type="button" class="btn btn-secondary" data-hs-export="pdf">${frappe.utils.escape_html(__("Exportar PDF completo"))}</button>`:""}</div>`;
    const dialog=await this.dialog(title,[field("records",__("Registros"),"HTML",{options:html()})],async(_,d)=>d.hide(),__("Cerrar"),"extra-large");
    if(audit)dialog.$wrapper.on('click','[data-hs-audit]',event=>this.action_view_audit(event.currentTarget.dataset.hsAudit));
    dialog.$wrapper.on("click","[data-hs-page]",async event=>{
      const direction=event.currentTarget.dataset.hsPage;
      dialog.$wrapper.find("[data-hs-page]").prop("disabled",true);
      try{
        result=await this.call(method,{...args,offset:direction==="next"?result.offset+result.page_length:Math.max(0,result.offset-result.page_length),page_length:50});
      }catch{frappe.msgprint(__("No se pudo consultar esa página. Intente nuevamente."));}
      finally{
        dialog.set_df_property("records","options",html());
        dialog.$wrapper.scrollTop(0).find(".modal-body").scrollTop(0);
        dialog.$wrapper.find('p[role="status"]').attr("tabindex","-1").trigger("focus");
      }
    });
    dialog.$wrapper.on("click","[data-hs-export]",event=>{
      const params=new URLSearchParams({...args,file_format:event.currentTarget.dataset.hsExport});
      window.open("/api/method/hospitality_suite.api.export_report?"+params.toString(),"_blank","noopener");
    });
    return dialog;
  };

  Desk.prototype.action_guest_history=function(name){return this.show_paged(__("Historial de estancias"),"guest_history",{name});};
  Desk.prototype.action_report=async function(report){
    let options=await this.call("report_options",{property_name:this.property,report_name:report}),dialog,revision=0,pending=false,valid=true,ready=false;
    const translate=v=>this.data.report_values?.[v]||v;
    const emptyLabel=key=>key==="detail_level"?__("Vista operativa"):key==="group_by"?__("Detalle por documento"):__("Todos");
    const select=(key,label,values)=>field(key,label,"Select",{_hsDataOptions:true,options:[{value:"",label:emptyLabel(key)},...values]});
    const labels={category:__("Categoría"),room:__("Habitación"),stay:__("Estancia"),channel:__("Canal"),user:__("Registrado por"),assigned_to:__("Responsable"),shift:__("Turno"),method:__("Medio de pago"),status:__("Estado"),kind:__("Concepto"),item:__("Artículo"),warehouse:__("Almacén"),purpose:__("Uso operativo"),adjustment_type:__("Tipo de ajuste"),group_by:__("Agrupar producción"),detail_level:__("Presentación")};
    const values=key=>{
      if(key==="group_by")return [{value:"room",label:__("Por habitación")},{value:"category",label:__("Por categoría")},{value:"item",label:__("Por servicio o artículo")},{value:"channel",label:__("Por canal")},{value:"property",label:__("Por establecimiento")}];
      if(key==="detail_level")return [{value:"technical",label:__("Documentos y referencias técnicas")}];
      const mapping={category:["categories","category_name"],room:["rooms","room_number"],stay:["stays","label"],user:["users","full_name"],assigned_to:["users","full_name"],shift:["shifts","label"],method:["methods","mode_of_payment"],warehouse:["warehouses","warehouse_name"]};
      if(mapping[key]){const [source,label]=mapping[key];return options[source].filter(row=>key!=="room"||!dialog?.get_value("category")||row.category===dialog.get_value("category")).map(row=>({value:row.name,label:`${row[label]||row.name}${["user","assigned_to"].includes(key)&&row[label]!==row.name?` · ${row.name}`:""}${row.currency?` · ${row.currency}`:""}${!dialog?.get_value("property_name")&&row.property_label?` · ${row.property_label}`:""}`}));}
      const list=key==="channel"?options.channels:key==="status"?options.statuses:key==="kind"?options.kinds:key==="adjustment_type"?["Discount","Courtesy","Surcharge"]:["Purchase","Transfer","Cleaning","Waste","Linen Replacement","Maintenance","Laundry","Sale","Adjustment","Stock"];
      return list.map(v=>({value:v,label:key==="channel"?v:translate(v)}));
    };
    const properties=company=>[{value:"",label:__("Todos los autorizados de la compañía")},...options.properties.filter(p=>p.company===company).map(p=>({value:p.name,label:p.property_name}))];
    const refresh=async()=>{
      if(!dialog||!ready)return;
      const version=++revision;
      pending=true;valid=false;dialog.get_primary_btn().prop("disabled",true);
      try{
        const fresh=await this.call("report_options",{property_name:dialog.get_value("property_name")||"",company:dialog.get_value("company"),report_name:report});
        if(version!==revision)return;
        options=fresh;valid=true;
        for(const key of options.filters){
          if(key==="item")continue;
          dialog.set_df_property(key,"options",[{value:"",label:emptyLabel(key)},...values(key)]);
          await dialog.set_value(key,"");
        }
      }finally{if(version===revision){pending=false;dialog.get_primary_btn().prop("disabled",!valid);}}
    };
    const company=options.properties.find(p=>p.name===this.property)?.company;
    let selectedCompany=company;
    const filters=options.filters.map(key=>key==="item"?this.item_field(labels[key],"any",{reqd:0}):select(key,labels[key],values(key)));
    const dates=options.base==="Disponibilidad"?[
      field("starts_at",__("Inicio (hora local de cada establecimiento)"),"Datetime",{default:this.data.property_now?.slice(0,19),reqd:1}),
      field("ends_at",__("Fin (hora local de cada establecimiento)"),"Datetime",{reqd:1})
    ]:[field("date_field",__("Consultar por"),"Select",{options:options.date_fields,default:options.date_field,reqd:1}),
      field("date_range_section","","Section Break"),field("from_date",__("Desde"),"Date"),field("date_range_columns","","Column Break"),field("to_date",__("Hasta"),"Date")];
    dialog=await this.dialog(__("Filtros · {0}",[__(report)]),[
      field("company",__("Compañía"),"Select",{_hsDataOptions:true,options:options.companies,default:company,reqd:1,onchange:async()=>{
        if(!dialog||!ready||dialog.get_value("company")===selectedCompany)return;
        selectedCompany=dialog.get_value("company");
        dialog.set_df_property("property_name","options",properties(dialog.get_value("company")));
        const previous=dialog.get_value("property_name");
        await dialog.set_value("property_name","");
        if(!previous)await refresh();
      }}),
      field("scope_columns","","Column Break"),field("property_name",__("Establecimiento"),"Select",{_hsDataOptions:true,options:properties(company),default:this.property,onchange:refresh}),
      field("period_section",__("Período"),"Section Break"),...dates,
      field("filter_section",__("Filtros opcionales"),"Section Break"),...filters.slice(0,Math.ceil(filters.length/2)),field("filter_columns","","Column Break"),...filters.slice(Math.ceil(filters.length/2)),
      field("criterion_section","","Section Break"),field("explanation",__("Criterio del reporte"),"HTML",{options:`<p class="text-muted">${e(options.note)}</p>`})
    ],async(form,d)=>{
      if(pending||!valid){frappe.msgprint(__("Espere a que se actualicen los filtros; si fallaron, vuelva a seleccionar el establecimiento."));return;}
      const selected={company:form.company};
      for(const key of [...options.filters,"date_field","from_date","to_date","starts_at","ends_at"]){if(form[key]!==undefined&&form[key]!=="")selected[key]=form[key];}
      await this.show_paged(report,"report_page",{property_name:form.property_name||"",report_name:report,filters:JSON.stringify(selected)},report);d.hide();
    },__("Consultar"));
    await dialog.set_value("company",company);
    await dialog.set_value("property_name",this.property);
    for(const key of ["from_date","to_date"])dialog.fields_dict[key]?.$input?.attr({type:"date"});
    ready=true;
    if(dialog.fields_dict.category)dialog.fields_dict.category.df.onchange=()=>{
      dialog.set_df_property("room","options",[{value:"",label:__("Todos")},...values("room")]);dialog.set_value("room","");
    };
    return dialog;
  };
})();
