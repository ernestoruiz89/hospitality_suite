/* Complete server queries, bounded visible pages, and complete exports. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const e=x=>frappe.utils.escape_html(String(x??""));
  const field=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),fieldtype,...extra});
  const choice=(name,label,rows,labelKey)=>field(name,label,"Select",{options:[{value:"",label:"Todos"},...rows.map(row=>({value:row.name,label:row[labelKey]||row.name}))]});

  Desk.prototype.show_paged=async function(title,method,args,reportName){
    const allowedExport=reportName&&(frappe.session.user==="Administrator"||["System Manager","HS Administrator","HS Manager","HS Accountant"].some(role=>frappe.user.has_role(role)));
    let result=await this.call(method,{...args,offset:0,page_length:50});
    const value=(key,v)=>{
      if(key==="room"&&v)return e(this.roomName(v));
      if(["starts_at","ends_at","actual_check_in","actual_check_out"].includes(key))return e(this.date(v));
      return e(["status","kind","type","cleaning_status","settlement_direction","purpose","classification","relationship"].includes(key)?this.data.report_values?.[v]||v:v);
    };
    const html=()=>`<p role="status">${result.total?`${result.offset+1}–${Math.min(result.offset+result.rows.length,result.total)}`:"0"} de ${result.total} registros</p>${result.rows.length?this.table(result.columns.map(key=>this.data.report_labels?.[key]||key),result.rows.map(row=>result.columns.map(key=>value(key,row[key])))):this.empty("No hay registros para estos filtros.")}<div class="hs-dialog-actions"><button type="button" class="btn btn-secondary" data-hs-page="previous" ${result.offset===0?"disabled":""}>Anterior</button><button type="button" class="btn btn-secondary" data-hs-page="next" ${!result.has_more?"disabled":""}>Siguiente</button>${allowedExport?'<button type="button" class="btn btn-secondary" data-hs-export="xlsx">Exportar XLSX completo</button><button type="button" class="btn btn-secondary" data-hs-export="pdf">Exportar PDF completo</button>':""}</div>`;
    const dialog=await this.dialog(title,[field("records","Registros","HTML",{options:html()})],async(_,d)=>d.hide(),"Cerrar","extra-large");
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

  Desk.prototype.action_guest_history=function(name){return this.show_paged("Historial de estancias","guest_history",{name});};
  Desk.prototype.action_report=function(report){
    const extra=report==="Movimientos de inventario"?[
      choice("warehouse","Almacén",this.data.warehouses||[],"warehouse_name"),field("item","Artículo","Link",{options:"Item"}),
      field("purpose","Uso operativo","Select",{options:[{value:"",label:"Todos"},...["Purchase","Transfer","Cleaning","Waste","Linen Replacement","Maintenance","Laundry","Sale","Adjustment","Stock"].map(v=>({value:v,label:this.data.report_values?.[v]||v}))]})
    ]:[field("status","Estado (opcional)"),choice("room","Habitación",this.data.rooms,"room_number")];
    return this.dialog(`Filtros · ${report}`,[field("from_date","Desde","Date"),field("to_date","Hasta","Date"),...extra],async(filters,d)=>{
      await this.show_paged(report,"report_page",{property_name:this.property,report_name:report,filters:JSON.stringify(filters)},report);d.hide();
    },"Consultar");
  };
})();
