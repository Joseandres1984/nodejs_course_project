import test from 'node:test';
import assert from 'node:assert/strict';
import {margin,salePrice,discount,installments,unitCost} from './calculators.mjs';
function almost(actual,expected,tolerance=1e-8){ assert.ok(Math.abs(actual-expected)<=tolerance, `${actual} ≠ ${expected}`); }
test('margen real y recargo se distinguen',()=>{
  const r=margin({cost:100,sale:150});
  almost(r.primary,50);almost(r.secondary[0].value,100/3);almost(r.secondary[1].value,50);
});
test('margen puede ser negativo y costo cero es manejado',()=>{
  almost(margin({cost:200,sale:100}).secondary[0].value,-100);
  assert.equal(margin({cost:0,sale:10}).secondary[1].value,null);
  assert.throws(()=>margin({cost:100,sale:0}),RangeError);
});
test('precio de venta sobre margen (no markup)',()=>{
  const r=salePrice({cost:100,targetMargin:30});
  almost(r.primary,142.85714285714286);almost(r.secondary[1].value,30);
  almost(salePrice({cost:100,targetMargin:0}).primary,100);
  assert.throws(()=>salePrice({cost:100,targetMargin:100}),RangeError);
});
test('descuento normal, 0 y 100%',()=>{
  almost(discount({price:200,discountPercent:15}).primary,170);
  almost(discount({price:200,discountPercent:0}).primary,200);
  almost(discount({price:200,discountPercent:100}).primary,0);
  assert.throws(()=>discount({price:200,discountPercent:120}),RangeError);
});
test('cuotas sin interés y amortización con interés',()=>{
  almost(installments({principal:1000,monthlyRate:0,payments:10}).primary,100);
  const r=installments({principal:1000,monthlyRate:3,payments:12});
  almost(r.primary,1000*.03/(1-(1.03)**(-12)));
  assert.ok(r.secondary[0].value>1000);
});
test('cuotas numéricas extremas y validaciones',()=>{
  assert.throws(()=>installments({principal:100,monthlyRate:2,payments:0}),RangeError);
  assert.throws(()=>installments({principal:100,monthlyRate:2,payments:2.5}),RangeError);
  almost(installments({principal:0,monthlyRate:3,payments:12}).primary,0);
  const small=installments({principal:1000,monthlyRate:0.0000001,payments:360});
  assert.ok(Number.isFinite(small.primary));
});
test('costo unitario y costo del lote',()=>{
  const r=unitCost({fixedCosts:200,variableCost:25,units:20});
  almost(r.primary,35);almost(r.secondary[1].value,700);
  assert.throws(()=>unitCost({fixedCosts:200,variableCost:25,units:0}),RangeError);
});
test('valores negativos, NaN e Infinity nunca generan resultados ficticios',()=>{
  for(const fn of [()=>margin({cost:NaN,sale:100}),()=>discount({price:-1,discountPercent:5}),()=>unitCost({fixedCosts:Infinity,variableCost:1,units:1}),()=>installments({principal:100,monthlyRate:-2,payments:12}),()=>salePrice({cost:-3,targetMargin:50})]) assert.throws(fn,RangeError);
});
