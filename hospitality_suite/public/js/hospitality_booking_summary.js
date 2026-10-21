/* Human-readable booking details also remain visible after check-in. */
(() => {
  const Desk=window.hospitality_suite.Desk,e=value=>frappe.utils.escape_html(String(value??""));
  Desk.prototype.booking_summary=function(info){
    const b=info.booking,s=info.summary||{},pair=(label,value)=>`<div><dt>${e(__(label))}</dt><dd>${value}</dd></div>`;
    const reference=/^RES-\d{4}-\d{5,}$/.test(b.name||"")?pair(__("Número de reserva"),e(b.name)):"";
    const rooms=(s.rooms||[]).map(row=>`<article class="hs-booking-room"><h4>${e(__("Habitación solicitada {0}",[row.number]))} · ${e(row.room_label)}</h4><p>${e(row.category_label)} · ${e(__("Personas: {0} · Camas adicionales: {1}",[row.people,row.extra_beds]))}</p>${(row.stays||[]).map(stay=>`<p>${e(__("Estancia en habitación {0}",[stay.room_label]))} · ${this.badge(stay.status)} · ${e(stay.guest_label)}</p>${this.allowed("stay")||this.allowed("finance")?this.button("detail",__("Ver estancia y cuenta"),stay.name):""}`).join("")}</article>`).join("");
    return `<section class="hs-booking-summary"><div class="hs-booking-heading"><h3>${e(__("Resumen de la reserva"))}</h3>${this.badge(b.status)}</div><dl>${reference}${pair(__("Huésped principal"),e(s.guest_label||__("Por registrar")))}${pair(__("Cliente que paga"),e(s.customer_label||__("Por definir")))}${pair(__("Entrada reservada"),e(this.date(b.starts_at)))}${pair(__("Salida reservada"),e(this.date(b.ends_at)))}${pair(__("Modalidad"),e(s.mode_label||__("Por definir")))}${pair(__("Canal"),e(b.channel||__("Sin especificar")))}${pair(__("Importe de la reserva"),e(this.amount(b.amount,b.currency)))}</dl><p class="text-muted">${e(__("Este importe corresponde al alojamiento reservado. Consulte la cuenta para ver consumos, ajustes, impuestos, pagos y saldo actual."))}</p>${b.status==="Hold"&&b.hold_until?`<p>${e(__("Retención hasta"))}: ${e(this.date(b.hold_until))}</p>`:""}${rooms}${b.instructions?`<h4>${e(__("Solicitudes especiales"))}</h4><p class="hs-booking-note">${e(b.instructions)}</p>`:""}${b.reason?`<h4>${e(__("Motivo registrado"))}</h4><p class="hs-booking-note">${e(b.reason)}</p>`:""}</section>`;
  };
  Desk.prototype.bind_booking_summary=function(dialog,property){
    dialog.$wrapper.on("click.hsBookingSummary","[data-act='detail']",event=>{
      if(this.property!==property)return;
      const id=event.currentTarget.dataset.id;
      if(!id||!(this.allowed("stay")||this.allowed("finance")))return;
      dialog.hide();return this.action_detail(id);
    });
    return dialog;
  };
})();
