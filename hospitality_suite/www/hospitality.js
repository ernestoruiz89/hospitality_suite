frappe.ready(async()=>{
  const menu=document.querySelector?.('button.navbar-toggler');
  if(menu){menu.setAttribute('aria-label',__('Menú de navegación'));menu.classList.add('hs-portal-menu');}
  const el=id=>document.getElementById(id);
  const showResult=message=>{
    const result=el('hp-result');result.textContent=message;result.tabIndex=-1;
    // Disabling the submit button can blur it onto body. Announce the result
    // there, but do not interrupt someone already editing another field.
    if(document.activeElement===document.body||document.activeElement===el('hp-quote')||document.activeElement===el('hp-request'))result.focus();
  };
  // This public form presents its own inline result, including business
  // rejections; avoid a second native popup stealing that result's focus.
  // Website's process_response uses error_msg rather than Desk's silent flag.
  // An empty native jQuery target consumes that duplicate message without
  // inserting server HTML into this public form; showResult uses textContent.
  const call=async(method,args={})=>(await frappe.call({method:"hospitality_suite.portal."+method,args,silent:true,error_msg:$()})).message;
  let catalog;
  try{catalog=await call("catalog");}catch{el("hp-empty").textContent=__("No se pudieron consultar los establecimientos. Recargue la página para reintentar.");return;}
  if(!catalog.length){el("hp-empty").textContent=__("Las reservas en línea todavía no están habilitadas. Consulte directamente con recepción.");return;}
  el("hp-empty").hidden=true;el("hp-form").hidden=false;
  for(const prop of catalog)el("hp-property").add(new Option(prop.property_name,prop.name));
  function categoryInfo(){const prop=catalog.find(p=>p.name===el("hp-property").value),cat=prop?.categories.find(c=>c.name===el("hp-category").value);
    el("hp-category-info").textContent=cat?[
      cat.portal_description||"",__("Capacidad: {0} personas por habitación.",[cat.capacity]),cat.amenities?__("Comodidades: {0}",[cat.amenities]):""].filter(Boolean).join(" "):"";
    const image=el("hp-category-image");image.hidden=!cat?.portal_image;
    if(cat?.portal_image){image.src=cat.portal_image;image.alt=__("Habitación de categoría {0}",[cat.category_name]);}
    else image.removeAttribute("src");
  }
  function modeInfo(){const prop=catalog.find(p=>p.name===el("hp-property").value),requested=el("hp-request-mode").value==="Requested";
    const note=requested?__("Horas locales de {0}. Esta solicitud no reserva cupo; recepción debe volver a comprobar disponibilidad y precio antes de confirmarla.",[prop.time_zone]):
      __("Horas locales de {0}. La solicitud conserva cupo temporal hasta la hora indicada en su confirmación.",[prop.time_zone]);
    el("hp-zone").textContent=note+(el("hp-stay-mode").value==="Day Pass"?" "+__("Day Pass incluye habitación y requiere salida prevista el mismo día."):"");
    el("hp-request").textContent=requested?__("Enviar solicitud sin retención"):__("Solicitar confirmación");
  }
  function update(){const prop=catalog.find(p=>p.name===el("hp-property").value);el("hp-category").replaceChildren();for(const cat of prop.categories)el("hp-category").add(new Option(cat.category_name,cat.name));
    const modes=prop.mode==="Mixed"?["Hotel","Por tiempo","Day Pass"]:prop.mode==="Por tiempo"?["Por tiempo","Day Pass"]:["Hotel"];
    el("hp-stay-mode").replaceChildren();for(const mode of modes)el("hp-stay-mode").add(new Option(({Hotel:__("Por noche"),"Por tiempo":__("Por tiempo"),"Day Pass":__("Day Pass")})[mode],mode));
    const list=el("hp-experience-list");list.replaceChildren();
    el("hp-experiences").hidden=!(prop.experiences||[]).length;
    for(const exp of prop.experiences||[]){
      const row=document.createElement("div"),choice=document.createElement("input"),qty=document.createElement("input"),label=document.createElement("label");
      choice.type="checkbox";choice.value=exp.name;choice.className="hp-experience-choice";
      qty.type="number";qty.min="1";qty.max="20";qty.value="1";qty.className="hp-experience-quantity";qty.setAttribute("aria-label",__("Cantidad de {0}",[exp.experience_name]));
      label.append(choice,document.createTextNode(` ${exp.experience_name} · ${exp.price} ${exp.currency}${exp.duration?` · ${exp.duration}`:""}`));
      row.append(label,qty);list.append(row);
    }
    categoryInfo();modeInfo();}
  update();el("hp-property").addEventListener("change",update);el("hp-category").addEventListener("change",categoryInfo);el("hp-request-mode").addEventListener("change",modeInfo);
  el("hp-stay-mode").addEventListener("change",()=>{
    if(el("hp-stay-mode").value==="Day Pass"&&el("hp-start").value){
      const [date,clock]=el("hp-start").value.split("T"),[hour,minute]=clock.split(":").map(Number),end=Math.min(hour*60+minute+480,1439);
      el("hp-end").value=`${date}T${String(Math.floor(end/60)).padStart(2,"0")}:${String(end%60).padStart(2,"0")}`;
    }
    modeInfo();
  });
  let accepted,values,key,acceptedProperty,revision=0;
  function data(){return {category:el("hp-category").value,mode:el("hp-stay-mode").value,starts_at:el("hp-start").value,ends_at:el("hp-end").value,quantity:+el("hp-quantity").value,people:+el("hp-people").value,full_name:el("hp-name").value,email:el("hp-email").value,phone:el("hp-phone").value,request_mode:el("hp-request-mode").value,
    experiences:[...el("hp-experience-list").children].filter(row=>row.querySelector(".hp-experience-choice").checked).map(row=>({experience:row.querySelector(".hp-experience-choice").value,quantity:+row.querySelector(".hp-experience-quantity").value}))};}
  el("hp-form").addEventListener("input",()=>{revision++;accepted=null;el("hp-request").hidden=true;el("hp-breakdown").textContent="";el("hp-result").textContent=__("Consulte nuevamente el precio después de cambiar los datos.");});
  el("hp-form").addEventListener("submit",async(event)=>{
    event.preventDefault();const current=++revision,requested=data(),property=el("hp-property").value;
    accepted=null;el("hp-request").hidden=true;el("hp-quote").disabled=true;
    try{
      const quote=await call("quote",{property_name:property,data:JSON.stringify(requested)});
      if(current!==revision)return;
      accepted=quote;values=requested;acceptedProperty=property;key=crypto.randomUUID();
      showResult((requested.request_mode==="Requested"?__("Precio consultado: {0} {1}. La solicitud no reserva cupo; recepción confirmará precio, disponibilidad e impuestos.",[accepted.amount,accepted.currency]):
        __("Alojamiento: {0} {1}. Recepción confirmará las condiciones y los impuestos aplicables.",[accepted.amount,accepted.currency])));
      const explanations=Array.isArray(quote.explanation)?quote.explanation.filter(item=>typeof item==="string").slice(0,8):[];
      el("hp-breakdown").textContent=[...explanations,Number(quote.experiences_total)>0?__("Experiencias: {0} {1}.",[quote.experiences_total,quote.currency]):"",quote.estimated_total&&quote.estimated_total!==quote.amount?
        __("Total estimado con cargos de horario: {0} {1}.",[quote.estimated_total,quote.currency]):""].filter(Boolean).join(" · ");
      el("hp-request").hidden=false;
    }catch{if(current===revision){el("hp-breakdown").textContent="";showResult(__("No se encontró disponibilidad o no se pudo consultar. Revise las fechas e intente nuevamente."));}}
    finally{el("hp-quote").disabled=false;}
  });
  el("hp-request").addEventListener("click",async()=>{
    if(!accepted||el("hp-request").disabled)return;
    const controls=[...el("hp-form").elements];controls.forEach(control=>{control.disabled=true;});
    try{const result=await call("request",{property_name:acceptedProperty,data:JSON.stringify({...values,acceptance:accepted.acceptance}),request_key:key});window.location.assign(result.confirmation_url);}
    catch{showResult(__("Sin confirmación del servidor. Reintente con estos mismos datos; la solicitud conserva su referencia. No se ha registrado ningún pago."));}
    finally{controls.forEach(control=>{control.disabled=false;});}
  });
});
