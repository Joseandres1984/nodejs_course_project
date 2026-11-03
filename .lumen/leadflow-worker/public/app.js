"use strict";
const form=document.getElementById("lead-form");
const output=document.getElementById("output");
const status=document.getElementById("status");
const button=document.getElementById("submit");
function item(label,value){
  const box=document.createElement("div");box.className="result-item";
  const key=document.createElement("small");key.textContent=label;
  const text=document.createElement("strong");text.textContent=value;
  box.append(key,text);return box;
}
form.addEventListener("submit",async(event)=>{
  event.preventDefault();button.disabled=true;status.textContent="ANALIZANDO";
  try{
    const data=Object.fromEntries(new FormData(form).entries());
    data.presupuesto=Number(data.presupuesto);data.ambientes=Number(data.ambientes);
    const response=await fetch("/api/demo",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(data)});
    const body=await response.json();
    if(!response.ok||!body.ok)throw new Error(body.error||"No se pudo clasificar.");
    const x=body.resultado;
    output.replaceChildren(item("PRIORIDAD DE SEGUIMIENTO",x.prioridad.toUpperCase()),item("CONSULTA",x.resumen),item("SIGUIENTE ACCIÓN",x.proximo_paso),item("CRITERIO",x.criterio));
    status.textContent="DEMO COMPLETA";
  }catch(error){
    const p=document.createElement("p");p.textContent=error.message||"Error inesperado.";
    output.replaceChildren(p);status.textContent="ERROR";
  }finally{button.disabled=false;}
});
