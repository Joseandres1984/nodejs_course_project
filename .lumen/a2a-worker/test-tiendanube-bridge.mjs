import assert from 'node:assert/strict';
import { normalizeTiendanubeProduct } from './tiendanube-bridge.js';

const payload = normalizeTiendanubeProduct({
  name: { es: 'Producto prueba' },
  description: { es: 'Descripción propia de LUMEN' },
  variants: [{ price: '19999.90', sku: 'SKU-123', stock: 4 }]
});

assert.equal(payload.visibility, 'hidden');
assert.equal(payload.requires_shipping, true);
assert.equal(payload.variants[0].price, '19999.90');
assert.equal(payload.variants[0].sku, 'SKU-123');
assert.equal(payload.variants[0].stock, 4);
assert.equal(payload.name.es, 'Producto prueba');

const fallback = normalizeTiendanubeProduct({ name: 'Simple', description: 'Texto', price: 10, stock: -2 });
assert.equal(fallback.name.es, 'Simple');
assert.equal(fallback.variants[0].price, '10');
assert.equal(fallback.variants[0].stock, 0);
assert.equal(fallback.visibility, 'hidden');

console.log('TIENDANUBE_BRIDGE_TESTS ok');
