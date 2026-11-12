// Estrategia de recuperación de Gemini para AURA; no registra claves ni mensajes.
const cooldown = new Map();
const TRANSIENT = new Set([408, 500, 502, 503, 504]);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const modelName = s => /^gemini-[\w.-]{4,90}$/.test(s || '') ? s : null;
function isCooling(model) { return (cooldown.get(model) || 0) > Date.now(); }
function coolDown(model) { cooldown.set(model, Date.now() + 45000); }
function readAnswer(data) {
  return (data?.candidates?.[0]?.content?.parts || [])
    .filter(p => !p.thought).map(p => p.text || '').join('').trim();
}
// transport y pause son inyectables para probar errores sin llamar a Google.
export async function generateWithFallback({
  key, model, fallbackModel = 'gemini-3.5-flash-lite', content,
  transport = fetch, pause = sleep, timeoutMs = 16000
}) {
  const primary = modelName(model) || 'gemini-3.5-flash';
  const fallback = modelName(fallbackModel) || 'gemini-3.5-flash-lite';
  const candidates = [primary, ...(fallback !== primary ? [fallback] : [])];
  let lastStatus = 503, lastModel = primary;
  for (let index = 0; index < candidates.length; index++) {
    const chosen = candidates[index];
    if (isCooling(chosen)) continue;
    const attempts = index === 0 ? 2 : 1;
    for (let tryNumber = 0; tryNumber < attempts; tryNumber++) {
      if (tryNumber > 0) await pause(600 + Math.floor(Math.random() * 450));
      lastModel = chosen;
      let response;
      try {
        response = await transport(
          'https://generativelanguage.googleapis.com/v1beta/models/' + encodeURIComponent(chosen) + ':generateContent',
          {method:'POST',headers:{'Content-Type':'application/json','x-goog-api-key':key},
          body:JSON.stringify(content), signal:AbortSignal.timeout(timeoutMs)}
        );
      } catch (e) {
        lastStatus = 504;
        if (tryNumber + 1 === attempts) { coolDown(chosen); break; }
        continue;
      }
      if (response.ok) {
        const data = await response.json();
        const answer = readAnswer(data);
        if (!answer) return {ok:false,status:502,reason:'empty',model:chosen};
        cooldown.delete(chosen);
        return {ok:true,status:200,answer,model:chosen,fallback:index>0};
      }
      lastStatus = response.status;
      if (response.status === 429) return {ok:false,status:429,reason:'quota',model:chosen};
      if (response.status === 401 || response.status === 403) return {ok:false,status:502,reason:'credentials',model:chosen};
      if (response.status === 400) return {ok:false,status:502,reason:'request',model:chosen};
      if (response.status === 404) break;
      if (!TRANSIENT.has(response.status)) return {ok:false,status:502,reason:'provider',model:chosen};
      if (tryNumber + 1 === attempts) { coolDown(chosen); break; }
    }
  }
  return {ok:false,status:503,reason:'unavailable',providerStatus:lastStatus,model:lastModel};
}
export function resetCooldownForTests(){cooldown.clear();}
