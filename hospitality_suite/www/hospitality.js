frappe.ready(async()=>{
  const el=id=>document.getElementById(id);
  const call=async(method,args={})=>(await frappe.call({method:"hospitality_suite.portal."+method,args})).message;
  const catalog=await call("catalog");
  if(!catalog.length){el("hp-empty").textContent="Las reservas en línea todavía no están habilitadas. Consulte directamente con recepción.";return;}
  el("hp-empty").hidden=true;el("hp-form").hidden=false;
  for(const prop of catalog)el("hp-property").add(new Option(prop.property_name,prop.name));
  function update(){const prop=catalog.find(p=>p.name===el("hp-property").value);el("hp-category").replaceChildren();for(const cat of prop.categories)el("hp-category").add(new Option(cat.category_name,cat.name));el("hp-zone").textContent="Horas locales de "+prop.time_zone+". La solicitud conserva cupo temporal hasta la hora indicada en su confirmación.";}
  update();el("hp-property").addEventListener("change",update);
  let accepted,values,key;
  function data(){return {category:el("hp-category").value,starts_at:el("hp-start").value,ends_at:el("hp-end").value,quantity:+el("hp-quantity").value,people:+el("hp-people").value,full_name:el("hp-name").value,email:el("hp-email").value,phone:el("hp-phone").value};}
  el("hp-form").addEventListener("input",()=>{accepted=null;el("hp-request").hidden=true;});
  el("hp-form").addEventListener("submit",async(event)=>{event.preventDefault();el("hp-quote").disabled=true;try{values=data();accepted=await call("quote",{property_name:el("hp-property").value,data:JSON.stringify(values)});el("hp-result").textContent="Alojamiento: "+accepted.amount+" "+accepted.currency+". Recepción confirmará las condiciones y los impuestos aplicables.";el("hp-request").hidden=false;key=crypto.randomUUID();}catch(error){el("hp-result").textContent="No se encontró disponibilidad o no se pudo consultar. Revise las fechas e intente nuevamente.";}finally{el("hp-quote").disabled=false;}});
  el("hp-request").addEventListener("click",async()=>{if(!accepted)return;el("hp-request").disabled=true;try{const result=await call("request",{property_name:el("hp-property").value,data:JSON.stringify({...values,acceptance:accepted.acceptance}),request_key:key});window.location.assign(result.confirmation_url);}finally{el("hp-request").disabled=false;}});
});
