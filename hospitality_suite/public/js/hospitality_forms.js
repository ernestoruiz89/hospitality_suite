/* Native tabs/columns keep each task readable without replacing its commands. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  let sequence=0;
  const refund=doc=>["Refund","Guarantee Refund"].includes(doc.kind);
  const group=(label,left,right=[],extra={})=>({label,columns:[left,right],...extra});
  Desk.prototype.form_layout=function(fields){
    if(fields.some(df=>["Tab Break","Section Break","Column Break"].includes(df.fieldtype)))return null;
    const names=new Set(fields.map(df=>df.fieldname)),has=(...keys)=>keys.every(key=>names.has(key));
    if(names.size!==fields.length)return null;
    if(has("opening_amount","currency")&&fields.length<=3)return{kind:"open_shift",fields,action:__("Abrir turno")};
    let kind,title,action,groups;
    if(has("cleaning_minutes","receivable_account","financial_enabled")){
      kind="property";title=__("Políticas y contabilidad");action=__("Guardar configuración");
      groups=[group(__("Operación"),["brand_name","mode","time_zone","cleaning_minutes"],["inspection_required","discreet_mode","guest_id_required","allow_credit"]),
        group(__("Cargos de alojamiento"),["lodging_charge_policy"]),
        group(__("Cuentas y almacenes"),["cost_center","receivable_account","guarantee_account"],["warehouse","laundry_warehouse","cash_transfer_account"]),
        group(__("Artículos e impuestos"),["lodging_item","extra_hour_item","timing_item","price_list"],["tax_template","tax_policy_confirmed","financial_enabled"])];
    }else if(has("block_hours","amount","included_services")){
      kind="rate";title=__("Configurar tarifa");action=__("Guardar tarifa");
      for(const df of fields.filter(df=>["block_hours","extra_hour_rate","grace_minutes","rounding_minutes","night_start","night_end"].includes(df.fieldname)))df.depends_on??=doc=>doc.mode==="Motel";
      groups=[group(__("Precio"),["title","category","amount"],["mode","currency","priority","active"]),
        group(__("Tiempo y personas"),["included_people","additional_person_rate","extra_bed_rate"],["block_hours","extra_hour_rate","grace_minutes","rounding_minutes"]),
        group(__("Vigencia"),["valid_from","valid_to","weekdays"],["customer","night_start","night_end"]),
        group(__("Servicios incluidos"),["included_services"])];
    }else if(has("mode_of_payment","fee_percent","refund_fee_percent")){
      kind="payment_method";title=__("Configurar medio de pago");action=__("Guardar medio de pago");
      groups=[group(__("Medio y cuenta"),["mode_of_payment","account","currency"],["is_cash","reference_required"]),
        group(__("Comisión y liquidación"),["fee_percent","fee_fixed","fee_account"],["withholding_percent","withholding_account","settlement_account"]),
        group(__("Devoluciones"),["refund_fee_percent","refund_fee_fixed"])];
    }else if(has("close_time","cancellation_fee_mode","checkout_quote_minutes")){
      kind="policies";action=__("Guardar horarios y políticas");
      groups=[group(__("Horarios"),["close_time","check_in_time","check_out_time"],["checkout_inspection_required","checkout_quote_minutes"]),
        group(__("Cargos por horario"),["early_hour_rate","late_hour_rate","timing_item"],["schedule_grace_minutes","schedule_rounding_minutes"]),
        group(__("Cancelaciones"),["cancellation_fee_mode","cancellation_fee_value"],["no_show_fee_mode","no_show_fee_value","penalty_item"])];
    }else if(has("rooms","starts_at","ends_at")&&(names.has("guest")||names.has("reason"))){
      kind="reservation";action=__("Revisar precio");
      groups=names.has("draft_help")?
        [group(__("Fechas y pagador"),["draft_help","starts_at","mode"],["customer","ends_at"]),group(__("Habitaciones"),["rooms"]),group(__("Opciones"),["guest","channel"],["hold","instructions"])]:
        [group(names.has("guest")?__("Huésped y fechas"):__("Fechas y pagador"),["guest","starts_at","mode"],["customer","ends_at"]),group(__("Habitaciones"),["rooms"]),group(__("Opciones"),["channel","hold","instructions","reason"])];
    }else if(has("source_payment","kind","tendered","shift","method")){
      kind="payment";
      const method=doc=>(this.data.payment_methods||[]).find(row=>row.name===doc.method);
      const source=fields.find(df=>df.fieldname==="source_payment");source.depends_on??=refund;
      const credit=fields.find(df=>df.fieldname==="credit_note");if(credit)credit.depends_on??=doc=>doc.kind==="Refund";
      const reason=fields.find(df=>df.fieldname==="reason");if(reason)reason.depends_on??=refund;
      const cash=fields.find(df=>df.fieldname==="tendered");cash.depends_on??=doc=>Boolean(method(doc)?.is_cash);
      const reference=fields.find(df=>df.fieldname==="reference");
      if(reference){reference.depends_on??=doc=>Boolean(method(doc)&&(!method(doc).is_cash||method(doc).reference_required));reference.mandatory_depends_on??=doc=>Boolean(method(doc)?.reference_required);}
      groups=[group(__("Cuenta y concepto"),["kind","stay","booking"],["folio","shift"]),
        group(__("Importe"),["method","amount"],["tendered","reference"]),
        group(__("Devolución"),["source_payment","credit_note","reason","refund_help"],[],{depends_on:refund})];
    }else if(has("full_name","identity_number","address_line1")){
      kind="guest";action=names.has("reason")?__("Guardar cambios"):__("Registrar huésped");
      const identity=fields.find(df=>df.fieldname==="identity_number"),required=identity?.reqd!==undefined?Boolean(identity.reqd):Boolean(this.prop?.guest_id_required);
      groups=[group(__("Datos principales"),["guest_policy","full_name","phone","email"],["payer_summary",...(required?["identity_type","identity_number"]:[])]),
        group(__("Datos adicionales"),["address_line1","city","country","shared_notice"],[...(required?[]:["identity_type","identity_number"]),"nationality","reason"])];
    }else if(has("property_name","company","business_date")){
      kind="new_property";action=__("Crear establecimiento");
      groups=[group(__("Establecimiento"),["property_name","company"],["mode","currency"]),
        group(__("Fecha y horario"),["time_zone","close_time","business_date"])];
    }else return null;
    const id=++sequence,parent="hs-form-"+id,used=new Set(),result=[];
    const take=keys=>keys.flatMap(key=>{const field=fields.find(df=>df.fieldname===key);if(!field||used.has(field))return [];used.add(field);return [field];});
    const render=entry=>{
      const columns=entry.columns.map(take).filter(column=>column.length);
      if(!columns.length)return;
      const defaults=Object.fromEntries(fields.map(df=>[df.fieldname,df.default]));
      result.push({fieldtype:"Tab Break",fieldname:`_hs_tab_${id}_${result.length}`,label:entry.label,parent,hidden:entry.depends_on?!entry.depends_on(defaults):0,depends_on:entry.depends_on});
      columns.forEach((column,index)=>{if(index)result.push({fieldtype:"Column Break",fieldname:`_hs_column_${id}_${result.length}`});result.push(...column);});
    };
    groups.forEach(render);
    // New extensions remain visible, even when this layout has not named them.
    const remaining=fields.filter(df=>!used.has(df));
    if(remaining.length)render(group(__("Otros ajustes"),remaining.map(df=>df.fieldname)));
    return {kind,title,action,fields:result};
  };
  Desk.prototype.reveal_form_error=function(dialog){
    const field=Object.values(dialog.fields_dict).find(control=>{
      if(!control.get_value||control.df.hidden||control.df.hidden_due_to_dependency)return false;
      const value=control.get_value();
      return control.df.invalid||(control.df.reqd&&(value==null||value===""||(Array.isArray(value)&&!value.length)));
    });
    field?.tab?.tab_link.find(".nav-link").trigger("click");
    dialog._hsSyncFormTabs?.();
    field?.$wrapper?.[0]?.scrollIntoView({block:"nearest"});
  };
  Desk.prototype.configure_form_dialog=function(dialog,layout){
    const parent=(frappe.ui.open_dialogs||[]).filter(open=>open!==dialog).at(-1);
    if(parent?.display&&parent.$wrapper.hasClass("hs-form-dialog")){
      parent.$wrapper.addClass("hs-form-suspended").attr({inert:"","aria-hidden":"true"});
      dialog.$wrapper.one("hide.bs.modal.hsFormParent",()=>{
        parent.$wrapper.removeClass("hs-form-suspended").removeAttr("inert");
        if(parent.display)parent.$wrapper.removeAttr("aria-hidden");
      });
    }
    if(dialog.fields_dict?.allocation&&dialog.fields_dict.status){
      const update=()=>{const action=dialog.get_value("status"),labels={"Check In":__("Registrar entrada"),Modify:__("Modificar reserva"),Confirmed:__("Confirmar reserva"),Cancelled:__("Revisar cancelación"),"No Show":__("Revisar no presentación")};dialog.get_primary_btn().text(labels[action]||__("Continuar"));};
      dialog.fields_dict.status.$input.on("change.hsBookingAction",update);update();
    }
    if(!layout)return;
    dialog.$wrapper.attr("data-hs-form",layout.kind);
    dialog._hsSyncFormTabs=()=>{for(const tab of dialog.tabs||[])tab.tab_link.find(".nav-link").attr("aria-selected",String(tab.is_active()&&!tab.hidden));};
    for(const tab of dialog.tabs||[])tab.tab_link.find(".nav-link").on("click.hsFormSelection",dialog._hsSyncFormTabs);
    dialog._hsSyncFormTabs();
    if(layout.kind==="rate"){
      const update=()=>{const label=dialog.get_value("mode")==="Motel"?__("Precio por bloque"):__("Precio por noche");dialog.set_df_property("amount","label",label);dialog.fields_dict.amount.$input?.attr("aria-label",label);};
      dialog.fields_dict.mode.$input.on("change.hsFormRate",update);update();
    }
    if(layout.kind!=="payment")return;
    const update=()=>{
      const kind=dialog.get_value("kind"),labels={Payment:[__("Registrar cobro"),__("Revisar cobro")],Advance:[__("Registrar anticipo"),__("Revisar anticipo")],Guarantee:[__("Registrar garantía"),__("Revisar garantía")],Refund:[__("Devolver un pago"),__("Revisar devolución")],"Guarantee Refund":[__("Devolver garantía"),__("Revisar devolución")]};
      const [title,action]=labels[kind]||labels.Payment;
      dialog.set_title(title);dialog.get_primary_btn().text(action);
      for(const tab of dialog.tabs||[]){
        if(tab.df.depends_on!==refund)continue;
        tab.df.hidden=!refund({kind});tab.refresh();
        if(tab.hidden&&tab.is_active())dialog.tabs[0]?.set_active();
      }
      dialog._hsSyncFormTabs();
      const label=refund({kind})?__("Efectivo entregado (vacío = importe)"):__("Efectivo recibido (vacío = importe)");
      dialog.set_df_property("tendered","label",label);dialog.fields_dict.tendered.$input?.attr("aria-label",label);
    };
    dialog.fields_dict.kind.$input.on("change.hsFormIntent",update);update();
  };
})();
