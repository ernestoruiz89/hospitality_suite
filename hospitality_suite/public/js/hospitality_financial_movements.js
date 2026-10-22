/* Caja Chica and financing operations. Server commands own every accounting decision. */
(() => {
  const Desk=window.hospitality_suite.Desk;
  const e=value=>frappe.utils.escape_html(String(value??""));
  const f=(fieldname,label,fieldtype="Data",extra={})=>({fieldname,label:__(label),fieldtype,...extra});
  const amount=(fieldname,label)=>f(fieldname,label,"Currency",{reqd:1});
  const pick=(name,label,rows,labelKey="name",optional=false)=>f(name,label,"Select",{reqd:!optional,_hsDataOptions:true,
    options:[{value:"",label:__("Seleccione…")},...rows.map(row=>({value:row.name,label:row[labelKey]||row.name}))]});
  const opens=desk=>(desk.data.shifts||[]).filter(s=>s.status==="Open");
  const methods=desk=>(desk.data.payment_methods||[]).filter(m=>m.is_cash&&m.currency===desk.data.inventory_currency).map(m=>({...m,label:`${m.mode_of_payment} · ${m.currency}`}));
  const selection=desk=>[pick("shift",__("Turno abierto"),opens(desk)),pick("method",__("Medio de efectivo en moneda base"),methods(desk),"label")];
  const run=(desk,action,values,dialog,key)=>desk.mutate(action,values,key).then(()=>dialog.hide());

  Desk.prototype.render_petty_cash=function(el){
    const p=this.data.petty_cash||{}, expenses=this.data.petty_expenses||[], renditions=this.data.petty_renditions||[], handovers=this.data.petty_handovers||[];
    if(!p.active){el.html(`<section class="hs-section"><h2>${e(__("Caja Chica pendiente de configurar"))}</h2><p>${e(__("Gerencia debe asignar cuenta, responsable y cuentas de diferencias en Configuración."))}</p>${this.allowed("setup")?this.button("petty_config",__("Configurar Caja Chica")):""}</section>`);return;}
    const responsible=p.responsible===frappe.session.user, finance=this.allowed("finance"), manager=this.allowed("approve");
    const initial=(this.data.treasury_movements||[]).some(m=>m.kind==="Initial Fund"&&m.status!=="Cancelled");
    el.html(`<div class="hs-metrics"><article><span>${e(__("Responsable"))}</span><strong>${e(p.responsible)}</strong></article>
      <article><span>${e(__("Saldo contable / efectivo esperado"))}</span><strong>${e(this.amount(p.balance,p.currency))} / ${e(this.amount(p.expected_cash,p.currency))}</strong></article>
      <article><span>${e(__("Gastos por rendir"))}</span><strong>${e(this.amount(p.pending_expenses,p.currency))}</strong></article></div>
      <div class="hs-toolbar"><div><h2>${e(__("Caja Chica"))}</h2><p>${e(__("Cada desembolso y reposición genera su asiento en ERPNext."))}</p></div>
      ${finance&&!initial?this.button("petty_initial",__("Entregar fondo inicial"),"","primary"):""}
      ${responsible?this.button("petty_spend",__("Nuevo desembolso"),"","primary")+this.button("petty_submit",__("Presentar rendición")):""}
      ${manager?this.button("petty_handover",__("Traspasar responsable")):""}</div>
      <section class="hs-section"><h2>${e(__("Desembolsos"))}</h2>${this.table([__("Fecha"),__("Beneficiario y concepto"),__("Comprobante"),__("Importe"),__("Estado"),__("Acción")],expenses.map(x=>[
        e(x.business_date),`${e(x.beneficiary)}<br>${e(x.concept)}`,e(x.receipt_reference),this.amount(x.amount,x.currency),this.badge(x.status),
        `${this.button("petty_open",__("Ver / adjuntar comprobante"),x.name)}${responsible&&x.responsible===frappe.session.user&&x.status==="Posted"&&(!x.rendition||renditions.find(r=>r.name===x.rendition)?.status==="Returned")?this.button("petty_correct",__("Corregir datos"),x.name):""}${manager&&x.status==="Posted"?this.button("finance_reverse",__("Revertir asiento"),`HS Petty Cash Expense|${x.name}`):""}`||"—"]))}</section>
      <section class="hs-section"><h2>${e(__("Rendiciones y reposiciones"))}</h2>${this.table([__("Rendición"),__("Gastos aprobables"),__("Esperado / contado"),__("Diferencia"),__("Estado"),__("Acción")],renditions.map(r=>[
        e(r.name),this.amount(r.expense_total,r.currency),`${this.amount(r.expected_cash,r.currency)} / ${this.amount(r.counted_cash,r.currency)}`,
        this.amount(r.variance,r.currency),this.badge(r.status),
        `${manager&&r.status==="Submitted"?this.button("petty_review",__("Revisar"),r.name):""}${responsible&&r.status==="Returned"?this.button("petty_resubmit",__("Volver a presentar"),r.name):""}${finance&&["Approved","Partially Reimbursed"].includes(r.status)?this.button("petty_replenish",__("Reponer"),r.name):""}${manager&&r.status==="Approved"&&r.variance_journal?this.button("finance_reverse",__("Revertir diferencia"),`HS Petty Cash Rendition|${r.name}`):""}`||"—"]))}</section>
      <section class="hs-section"><h2>${e(__("Traspasos"))}</h2>${this.table([__("Saliente"),__("Entrante"),__("Conteo"),__("Estado"),__("Acción")],handovers.map(h=>[
        e(h.outgoing),e(h.incoming),this.amount(h.counted_cash,p.currency),this.badge(h.status),
        h.status==="Awaiting Acceptance"&&[h.outgoing,h.incoming].includes(frappe.session.user)?this.button("petty_accept",__("Aceptar"),h.name):"—"]))}</section>`);
  };
  Desk.prototype["render_petty-cash"]=Desk.prototype.render_petty_cash;

  Desk.prototype.action_petty_config=async function(){const p=await this.call("configuration",{property_name:this.property}),key=frappe.utils.get_random(24);
    return this.dialog(__("Configuración de Caja Chica"),[
      f("petty_cash_account",__("Cuenta exclusiva de Caja Chica"),"Link",{options:"Account",default:p.petty_cash_account,reqd:1}),
      f("petty_cash_responsible",__("Responsable con acceso al establecimiento"),"Link",{options:"User",default:p.petty_cash_responsible,reqd:1}),
      f("petty_cash_overage_account",__("Cuenta de ingreso por sobrantes"),"Link",{options:"Account",default:p.petty_cash_overage_account,reqd:1}),
      f("petty_cash_shortage_account",__("Cuenta de gasto por faltantes"),"Link",{options:"Account",default:p.petty_cash_shortage_account,reqd:1})
    ],async(v,d)=>{await this.call("save_setup",{property_name:this.property,section:"property",data:JSON.stringify(v),request_key:key,expected_modified:p.modified});d.hide();await this.load();});};
  Desk.prototype.action_petty_initial=async function(){const key=frappe.utils.get_random(24);return this.dialog(__("Entregar fondo inicial"),[
    ...selection(this),amount("amount",__("Importe en moneda base")),f("reason",__("Referencia o motivo"),"Small Text")],
    (v,d)=>run(this,"petty_fund",{...v,kind:"Initial Fund"},d,key),__("Entregar fondo"));};
  Desk.prototype.action_petty_spend=async function(){const key=frappe.utils.get_random(24),categories=(this.data.expense_categories||[]).filter(c=>c.active);
    return this.dialog(__("Desembolso de Caja Chica"),[pick("category",__("Categoría y cuenta de gasto"),categories,"label"),
      f("beneficiary",__("Beneficiario"),"Data",{reqd:1}),f("concept",__("Concepto"),"Small Text",{reqd:1}),
      f("receipt_reference",__("Referencia escrita del comprobante"),"Data",{reqd:1}),amount("amount",__("Importe"))],
      (v,d)=>run(this,"petty_expense",v,d,key),__("Desembolsar y contabilizar"));};
  Desk.prototype.action_petty_correct=async function(id){const x=(this.data.petty_expenses||[]).find(row=>row.name===id),key=frappe.utils.get_random(24);
    return this.dialog(__("Corregir descripción del gasto"),[f("beneficiary",__("Beneficiario"),"Data",{default:x.beneficiary,reqd:1}),
      f("concept",__("Concepto"),"Small Text",{default:x.concept,reqd:1}),
      f("receipt_reference",__("Referencia del comprobante"),"Data",{default:x.receipt_reference,reqd:1}),
      f("reason",__("Motivo de corrección"),"Small Text")],(v,d)=>run(this,"petty_correct",{...v,expense:id},d,key));};
  Desk.prototype.action_petty_open=function(id){frappe.set_route("Form","HS Petty Cash Expense",id);};
  Desk.prototype.action_petty_submit=async function(){const key=frappe.utils.get_random(24);return this.dialog(__("Rendición y arqueo físico"),[
    amount("counted_cash",__("Efectivo contado")),f("explanation",__("Explicación de diferencia"),"Small Text")],
    (v,d)=>run(this,"petty_rendition",v,d,key),__("Presentar a Gerencia"));};
  Desk.prototype.action_petty_resubmit=async function(id){const key=frappe.utils.get_random(24);return this.dialog(__("Volver a presentar rendición"),[
    amount("counted_cash",__("Efectivo contado")),f("explanation",__("Explicación de diferencia"),"Small Text")],
    (v,d)=>run(this,"petty_rendition",{...v,rendition:id},d,key));};
  Desk.prototype.action_petty_review=async function(id){const key=frappe.utils.get_random(24);return this.dialog(__("Revisar rendición"),[
    f("approve",__("Aprobar (sin marcar: devolver)"),"Check"),f("note",__("Nota de revisión o corrección"),"Small Text")],
    (v,d)=>run(this,"petty_review",{...v,rendition:id},d,key),__("Registrar decisión"));};
  Desk.prototype.action_petty_replenish=async function(id){const key=frappe.utils.get_random(24),r=(this.data.petty_renditions||[]).find(row=>row.name===id);
    const paid=(this.data.treasury_movements||[]).filter(m=>m.rendition===id&&m.kind==="Replenishment"&&m.status==="Posted").reduce((s,m)=>s+(+m.amount),0);
    return this.dialog(__("Reponer gastos aprobados"),[f("remaining",__("Gastos pendientes de reposición"),"HTML",{options:`<strong>${e(this.amount((+r.expense_total)-paid,r.currency))}</strong>`}),
      ...selection(this),amount("amount",__("Entrega parcial o total")),f("reason",__("Referencia de entrega"),"Small Text")],
      (v,d)=>run(this,"petty_fund",{...v,kind:"Replenishment",rendition:id},d,key),__("Registrar reposición"));};
  Desk.prototype.action_petty_handover=async function(){const key=frappe.utils.get_random(24);return this.dialog(__("Solicitar traspaso de responsable"),[
    f("incoming",__("Nuevo responsable"),"Link",{options:"User",reqd:1}),amount("counted_cash",__("Efectivo contado")),
    f("reason",__("Motivo"),"Small Text")],(v,d)=>run(this,"petty_handover",v,d,key));};
  Desk.prototype.action_petty_accept=async function(id){const key=frappe.utils.get_random(24);return this.dialog(__("Aceptar arqueo y traspaso"),[
    f("confirmation",__("Confirmo el conteo y la custodia"),"Check",{reqd:1})],
    (_,d)=>run(this,"petty_accept",{handover:id},d,key),__("Aceptar traspaso"));};

  Desk.prototype.render_treasury=function(el){const concepts=this.data.treasury_concepts||[],moves=this.data.treasury_movements||[];
    el.html(`<div class="hs-toolbar"><div><h2>${e(__("Otros ingresos y financiación"))}</h2><p>${e(__("Movimientos sin factura; préstamos y capital requieren aprobación distinta del solicitante."))}</p></div>
      ${this.allowed("finance")?this.button("finance_other",__("Otro ingreso"),"","primary")+this.button("finance_request",__("Solicitar préstamo o aporte/retiro")):""}
      ${this.allowed("setup")?this.button("treasury_concept",__("Nuevo concepto")):""}</div>
      <section class="hs-section"><h2>${e(__("Conceptos financieros"))}</h2>${this.table([__("Concepto"),__("Naturaleza"),__("Cuenta"),__("Estado"),__("Acción")],concepts.map(c=>[e(c.label),e(this.data.report_values?.[c.nature]||c.nature),e(c.account),c.active?e(__("Activo")):e(__("Inactivo")),this.allowed("setup")?this.button("treasury_concept",__("Editar"),c.name):"—"]))}</section>
      <section class="hs-section"><h2>${e(__("Movimientos y saldos originales"))}</h2>${this.table([__("Fecha"),__("Movimiento"),__("Concepto / cuenta"),__("Importe"),__("Estado"),__("Acción")],moves.map(m=>[
        e(m.business_date),e(this.data.report_values?.[m.kind]||m.kind),`${e(m.concept_label||m.concept||"")}<br>${e(m.counter_account)}`,
        this.amount(m.amount,m.currency),this.badge(m.status),
        m.status==="Pending Approval"&&this.allowed("approve")?this.button("finance_approve",__("Aprobar"),m.name)+this.button("finance_reverse",__("Cancelar solicitud"),`HS Treasury Movement|${m.name}`):
        m.status==="Approved"&&this.allowed("finance")?this.button("finance_execute",__("Contabilizar"),m.name)+(this.allowed("approve")?this.button("finance_reverse",__("Cancelar solicitud"),`HS Treasury Movement|${m.name}`):""):
        m.status==="Posted"&&this.allowed("approve")?this.button("finance_reverse",__("Revertir asiento"),`HS Treasury Movement|${m.name}`):"—"]))}</section>`);
  };
  Desk.prototype.action_treasury_concept=async function(id){const key=frappe.utils.get_random(24),original=(this.data.treasury_concepts||[]).find(c=>c.name===id);
    return this.dialog(original?__("Editar concepto financiero"):__("Nuevo concepto financiero"),[
    f("label",__("Nombre"),"Data",{reqd:1,default:original?.label}),f("nature",__("Naturaleza"),"Select",{reqd:1,options:[{value:"Other Income",label:__("Otro ingreso")},{value:"Loan",label:__("Préstamo")},{value:"Capital",label:__("Capital")}],default:original?.nature}),
    f("account",__("Cuenta de ingreso, pasivo o patrimonio"),"Link",{options:"Account",reqd:1,default:original?.account}),f("active",__("Activo"),"Check",{default:original?original.active:1})],
    async(v,d)=>{if(original)await this.mutate("finance_concept",{...v,concept:id,modified:original.modified},key);
      else {await this.call("save_setup",{property_name:this.property,section:"treasury_concept",data:JSON.stringify(v),request_key:key});await this.load();}
      d.hide();});};
  Desk.prototype.finance_fields=function(){return [f("channel",__("Canal"),"Select",{reqd:1,options:[{value:"Cash",label:__("Caja")},{value:"Bank",label:__("Banco")}] }),
    pick("shift",__("Turno abierto (si es efectivo)"),opens(this),"name",true),
    pick("method",__("Medio de efectivo (si es efectivo)"),methods(this),"label",true),
    f("bank_account",__("Cuenta bancaria en moneda base (si es banco)"),"Link",{options:"Account"}),
    f("reference",__("Referencia bancaria"),"Data"),f("reason",__("Motivo"),"Small Text")];};
  Desk.prototype.finance_confirm=async function(data,dialog,key){const quote=await this.call("preview",{property_name:this.property,action:"finance_post",data:JSON.stringify(data)});
    return this.dialog(__("Revisar asiento antes de contabilizar"),[f("lines",__("Asiento"),"HTML",{options:`<p>${e(__("Débito"))}: <strong>${e(quote.debit)}</strong> · ${e(this.amount(quote.amount,quote.currency))}</p><p>${e(__("Crédito"))}: <strong>${e(quote.credit)}</strong> · ${e(this.amount(quote.amount,quote.currency))}</p>`})],
      async(_,review)=>{await this.mutate("finance_post",data,key);review.hide();dialog.hide();},__("Contabilizar"));};
  Desk.prototype.action_finance_other=async function(){const key=frappe.utils.get_random(24),concepts=(this.data.treasury_concepts||[]).filter(c=>c.active&&c.nature==="Other Income");
    return this.dialog(__("Otro ingreso sin factura"),[pick("concept",__("Concepto"),concepts,"label"),amount("amount",__("Importe en moneda base")),...this.finance_fields()],
      (v,d)=>this.finance_confirm({...v,kind:"Other Income"},d,key),__("Revisar asiento"));};
  Desk.prototype.action_finance_request=async function(){const key=frappe.utils.get_random(24),concepts=(this.data.treasury_concepts||[]).filter(c=>c.active&&["Loan","Capital"].includes(c.nature));
    const sources=(this.data.treasury_movements||[]).filter(m=>m.status==="Posted"&&["Loan Received","Capital Contribution"].includes(m.kind)).map(m=>({...m,label:`${m.kind} · ${m.name} · ${this.amount(m.amount,m.currency)}`}));
    return this.dialog(__("Solicitar préstamo, aporte o devolución"),[
      f("kind",__("Movimiento"),"Select",{reqd:1,options:[{value:"Loan Received",label:__("Préstamo recibido")},{value:"Loan Repayment",label:__("Devolución de préstamo")},{value:"Capital Contribution",label:__("Aporte de capital")},{value:"Capital Withdrawal",label:__("Retiro de capital")}] }),
      pick("concept",__("Concepto de entrada"),concepts,"label",true),pick("source_movement",__("Entrada original para devolución"),sources,"label",true),
      amount("amount",__("Principal en moneda base")),f("reason",__("Justificación"),"Small Text")],
      (v,d)=>run(this,"finance_request",v,d,key),__("Solicitar aprobación"));};
  Desk.prototype.action_finance_approve=async function(id){const key=frappe.utils.get_random(24);return this.dialog(__("Aprobar financiación"),[
    f("reason",__("Observación"),"Small Text")],(v,d)=>run(this,"finance_approve",{...v,movement:id},d,key),__("Aprobar"));};
  Desk.prototype.action_finance_execute=async function(id){const key=frappe.utils.get_random(24),m=(this.data.treasury_movements||[]).find(row=>row.name===id);
    return this.dialog(__("Registrar movimiento aprobado"),[
      f("summary",__("Principal aprobado"),"HTML",{options:`<p>${e(m.kind)} · ${e(this.amount(m.amount,m.currency))}</p>`}),
      ...this.finance_fields()],(v,d)=>this.finance_confirm({...v,movement:id,kind:m.kind,amount:m.amount,concept:m.concept,source_movement:m.source_movement},d,key),__("Revisar asiento"));};
  Desk.prototype.action_finance_reverse=async function(id){const [doctype,name]=id.split("|"),key=frappe.utils.get_random(24);
    return this.dialog(__("Revertir asiento autorizado"),[f("reason",__("Motivo de corrección contable"),"Small Text",{reqd:1})],
      (v,d)=>run(this,"finance_reverse",{doctype,name,reason:v.reason},d,key),__("Revertir"));};
  const setup=Desk.prototype.render_setup;
  Desk.prototype.render_setup=function(el){setup.call(this,el);el.find(".hs-shortcuts").append(this.button("petty_config",__("14. Configurar Caja Chica"))+this.button("treasury_concept",__("15. Concepto financiero")));};
})();
