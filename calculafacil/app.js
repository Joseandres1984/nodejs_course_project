import {TOOLS} from './calculators.mjs';
const config = {
  margin:{title:'Margen de ganancia',fields:[['cost','Costo por unidad',100,'money'],['sale','Precio de venta',150,'money']]},
  salePrice:{title:'Precio de venta',fields:[['cost','Costo por unidad',100,'money'],['targetMargin','Margen que buscás',30,'percent']]},
  discount:{title:'Descuentos',fields:[['price','Precio original',200,'money'],['discountPercent','Descuento',15,'percent']]},
  installments:{title:'Cuotas e intereses',fields:[['principal','Monto a financiar',1000,'money'],['monthlyRate','Interés mensual',3,'percent'],['payments','Cantidad de cuotas',12,'count']]},
  unitCost:{title:'Costo unitario',fields:[['fixedCosts','Costos fijos totales',200,'money'],['variableCost','Costo variable por unidad',25,'money'],['units','Cantidad de unidades',20,'count']]}
};
const $=id=>document.getElementById(id);
const workspace=$('workspace');
const fields=$('fields');
const form=$('calculator-form');
const currency=$('currency');
const primary=$('result-primary');
const error=$('result-error');
const stats=$('result-stats');
const resultLabel=$('result-label');
const footnote=$('result-footnote');
const copyButton=$('copy-button');
let active=null, lastCopy='';
function money(v){
  if(v==null||!Number.isFinite(v))return '—';
  return new Intl.NumberFormat('es-AR',{style:'currency',currency:currency.value,minimumFractionDigits:2,maximumFractionDigits:2}).format(v);
}
function fmt(v,unit){
  if(v===null||!Number.isFinite(v))return 'No aplica';
  if(unit==='%') return new Intl.NumberFormat('es-AR',{maximumFractionDigits:2}).format(v)+' %';
  return money(v);
}
function readNumbers(){
  const data={};
  for(const [id] of config[active].fields){
    const field=$(id);
    if(!field||field.value.trim()==='')throw new RangeError('Completá todos los campos para calcular.');
    const value=Number(field.value);
    if(!Number.isFinite(value))throw new RangeError('Revisá los valores ingresados.');
    data[id]=value;
  }
  return data;
}
function recalc(){
  if(!active)return;
  try{
    const output=TOOLS[active](readNumbers());
    const formatted=money(output.primary);
    if(!Number.isFinite(output.primary))throw new RangeError('El resultado supera el rango admitido.');
    primary.textContent=formatted;
    resultLabel.textContent=output.primaryLabel.toLocaleUpperCase('es-AR');
    error.hidden=true;
    stats.replaceChildren();
    for(const item of output.secondary){
      const panel=document.createElement('div'); panel.className='result-stat';
      const label=document.createElement('span'); label.textContent=item.label;
      const number=document.createElement('strong'); number.textContent=fmt(item.value,item.unit);
      panel.append(label,number); stats.append(panel);
    }
    footnote.textContent=output.note;
    lastCopy=`${config[active].title}: ${output.primaryLabel}: ${formatted}. ${output.secondary.map(x=>x.label+': '+fmt(x.value,x.unit)).join('; ')}`;
    copyButton.disabled=false;
  } catch(e){
    primary.textContent='—';resultLabel.textContent='REVISÁ LOS DATOS';
    error.textContent=e instanceof RangeError?e.message:'No se pudo calcular el resultado.';error.hidden=false;
    stats.replaceChildren();footnote.textContent='Corregí los campos para continuar.';
    lastCopy='';copyButton.disabled=true;
  }
}
function openTool(key){
  if(!config[key])return;
  active=key;
  workspace.hidden=false;
  $('workspace-title').textContent=config[key].title;
  for(const card of document.querySelectorAll('[data-tool]'))card.setAttribute('aria-expanded',String(card.dataset.tool===key));
  fields.replaceChildren();
  for(const [id,title,initial,kind] of config[key].fields){
    const wrapper=document.createElement('div');
    const label=document.createElement('label');label.className='field-label';label.htmlFor=id;label.textContent=title;
    const holder=document.createElement('div');holder.className='field-input';
    const input=document.createElement('input'); input.type='number';input.id=id;input.name=id;input.required=true;
    input.step=kind==='count'?'1':'any';input.min='0';input.value=initial;
    input.inputMode=kind==='count'?'numeric':'decimal';
    const prefix=document.createElement('span');prefix.className='field-affix';prefix.textContent=kind==='money'?(currency.value==='ARS'?'$':'US$'):kind==='percent'?'%':'UNID.';
    if(kind==='money'){holder.append(prefix,input);}else{holder.append(input,prefix);}
    wrapper.append(label,holder);fields.append(wrapper);
    input.addEventListener('input',recalc);
  }
  recalc();
  workspace.scrollIntoView({block:'start',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  $('workspace-title').focus({preventScroll:true});
}
for(const button of document.querySelectorAll('[data-tool]'))button.addEventListener('click',()=>openTool(button.dataset.tool));
$('close-tool').addEventListener('click',()=>{
  const previous=active;
  workspace.hidden=true;active=null;
  document.querySelectorAll('[data-tool]').forEach(c=>c.setAttribute('aria-expanded','false'));
  document.querySelector(`[data-tool="${previous}"]`)?.focus();
});
form.addEventListener('submit',e=>e.preventDefault());
form.addEventListener('reset',e=>{e.preventDefault();if(active)openTool(active);});
currency.addEventListener('change',()=>{
  for(const [id,,,kind] of config[active]?.fields??[]){
    if(kind==='money'){
      const input=$(id); if(input)input.previousElementSibling.textContent=currency.value==='ARS'?'$':'US$';
    }
  }
  recalc();
});
copyButton.addEventListener('click',async()=>{
  if(!lastCopy)return;
  try{
    await navigator.clipboard.writeText(lastCopy);
    const old=copyButton.textContent;copyButton.textContent='Resultado copiado ✓';
    window.setTimeout(()=>copyButton.textContent=old,1800);
  }catch{
    copyButton.textContent='Seleccioná el resultado para copiar';
  }
});
const slug=location.hash.slice(1);
if(config[slug])openTool(slug);
