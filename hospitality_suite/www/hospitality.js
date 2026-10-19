frappe.ready(async()=>{
  const el=id=>document.getElementById(id);
  const call=async(method,args={})=>(await frappe.call({method:"hospitality_suite.portal."+method,args})).message;
  let catalog;
  try{catalog=await call("catalog");}catch{el("hp-empty").textContent="No se pudieron consultar los establecimientos. Recargue la página para reintentar.";return;}
  if(!catalog.length){el("hp-empty").textContent="Las reservas en línea todavía no están habilitadas. Consulte directamente con recepción.";return;}
  el("hp-empty").hidden=true;el("hp-form").hidden=false;
  for(const prop of catalog)el("hp-property").add(new Option(prop.property_name,prop.name));
  function update(){const prop=catalog.find(p=>p.name===el("hp-property").value);el("hp-category").replaceChildren();for(const cat of prop.categories)el("hp-category").add(new Option(cat.category_name,cat.name));el("hp-zone").textContent="Horas locales de "+prop.time_zone+". La solicitud conserva cupo temporal hasta la hora indicada en su confirmación.";}
  update();el("hp-property").addEventListener("change",update);
  let accepted,values,key,acceptedProperty,revision=0;
  function data(){return {category:el("hp-category").value,starts_at:el("hp-start").value,ends_at:el("hp-end").value,quantity:+el("hp-quantity").value,people:+el("hp-people").value,full_name:el("hp-name").value,email:el("hp-email").value,phone:el("hp-phone").value};}
  el("hp-form").addEventListener("input",()=>{revision++;accepted=null;el("hp-request").hidden=true;el("hp-result").textContent="Consulte nuevamente el precio después de cambiar los datos.";});
  el("hp-form").addEventListener("submit",async(event)=>{
    event.preventDefault();const current=++revision,requested=data(),property=el("hp-property").value;
    accepted=null;el("hp-request").hidden=true;el("hp-quote").disabled=true;
    try{
      const quote=await call("quote",{property_name:property,data:JSON.stringify(requested)});
      if(current!==revision)return;
      accepted=quote;values=requested;acceptedProperty=property;key=crypto.randomUUID();
      el("hp-result").textContent="Alojamiento: "+accepted.amount+" "+accepted.currency+". Recepción confirmará las condiciones y los impuestos aplicables.";
      el("hp-request").hidden=false;
    }catch{if(current===revision)el("hp-result").textContent="No se encontró disponibilidad o no se pudo consultar. Revise las fechas e intente nuevamente.";}
    finally{el("hp-quote").disabled=false;}
  });
  el("hp-request").addEventListener("click",async()=>{
    if(!accepted||el("hp-request").disabled)return;
    const controls=[...el("hp-form").elements];controls.forEach(control=>{control.disabled=true;});
    try{const result=await call("request",{property_name:acceptedProperty,data:JSON.stringify({...values,acceptance:accepted.acceptance}),request_key:key});window.location.assign(result.confirmation_url);}
    catch{el("hp-result").textContent="Sin confirmación del servidor. Reintente con estos mismos datos; la solicitud conserva su referencia. No se ha registrado ningún pago.";}
    finally{controls.forEach(control=>{control.disabled=false;});}
  });
});
