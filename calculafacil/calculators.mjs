/** Pure, side-effect-free financial calculations; no network or user tracking. */
export function finiteNonnegative(value, name) {
  if (!Number.isFinite(value) || value < 0) throw new RangeError(`${name}: ingresá un número mayor o igual a cero.`);
  return value;
}
export function percent(value, name, maximum = 100) {
  if (!Number.isFinite(value) || value < 0 || value > maximum) throw new RangeError(`${name}: ingresá un porcentaje entre 0 y ${maximum}.`);
  return value;
}
export function margin({cost, sale}) {
  finiteNonnegative(cost, 'Costo');
  if (!Number.isFinite(sale) || sale <= 0) throw new RangeError('Venta: ingresá un precio mayor a cero.');
  const profit = sale - cost;
  return { primary: profit, primaryLabel: 'Ganancia por unidad', secondary: [{label: 'Margen sobre venta', value: profit / sale * 100, unit: '%'}, {label:'Recargo sobre costo',value:cost > 0 ? profit / cost * 100 : null,unit:'%'}], note: 'Margen = (precio de venta − costo) / precio de venta. No incluye impuestos ni otros gastos.' };
}
export function salePrice({cost, targetMargin}) {
  finiteNonnegative(cost, 'Costo');
  percent(targetMargin, 'Margen', 100);
  if (targetMargin === 100) throw new RangeError('El margen debe ser menor a 100%.');
  const sale = cost / (1 - targetMargin / 100);
  return {primary:sale,primaryLabel:'Precio sugerido de venta',secondary:[{label:'Ganancia por unidad',value:sale-cost},{label:'Margen objetivo',value:targetMargin,unit:'%'}],note:'El margen se calcula sobre el precio de venta, no sobre el costo. No incluye impuestos.'};
}
export function discount({price, discountPercent}) {
  finiteNonnegative(price,'Precio');
  percent(discountPercent,'Descuento');
  const saved = price * discountPercent / 100;
  return {primary:price-saved,primaryLabel:'Precio final',secondary:[{label:'Ahorrás',value:saved},{label:'Descuento aplicado',value:discountPercent,unit:'%'}],note:'Se aplica un único descuento directo. No contempla promociones acumulables.'};
}
export function installments({principal, monthlyRate, payments}) {
  finiteNonnegative(principal,'Capital');
  percent(monthlyRate,'Interés mensual');
  if (!Number.isSafeInteger(payments) || payments < 1 || payments > 600) throw new RangeError('Cuotas: ingresá una cantidad entera entre 1 y 600.');
  const r = monthlyRate / 100;
  const payment = r === 0 ? principal / payments : principal * r / (-Math.expm1(-payments * Math.log1p(r)));
  const total = payment * payments;
  return {primary:payment,primaryLabel:'Cuota mensual estimada',secondary:[{label:'Total a pagar',value:total},{label:'Intereses totales',value:Math.max(0,total-principal)}],note:'Sistema francés, con tasa mensual fija. No incluye seguros, impuestos, comisiones ni CFT.'};
}
export function unitCost({fixedCosts, variableCost, units}) {
  finiteNonnegative(fixedCosts,'Costos fijos');
  finiteNonnegative(variableCost,'Costo variable');
  if (!Number.isSafeInteger(units) || units < 1) throw new RangeError('Unidades: ingresá un entero mayor a cero.');
  const fixedPerUnit=fixedCosts/units;
  return {primary:fixedPerUnit+variableCost,primaryLabel:'Costo total por unidad',secondary:[{label:'Costo fijo por unidad',value:fixedPerUnit},{label:'Costo total del lote',value:fixedCosts+variableCost*units}],note:'El costo fijo se distribuye entre las unidades indicadas; no incluye impuestos no declarados.'};
}
export const TOOLS = Object.freeze({margin,salePrice,discount,installments,unitCost});
