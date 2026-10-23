export const OPERATIONS = ["alquilar", "comprar"];
export const PROPERTY_TYPES = ["departamento", "casa", "local", "indistinto"];
export const TIMEFRAMES = ["urgente", "30_dias", "explorando"];
const validText = (s, min, max) => typeof s === "string" && s.trim().length >= min && s.trim().length <= max;

export function validateLead(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return { error: "Datos inválidos." };
  const lead = {
    name: String(payload.name ?? "").trim(),
    email: String(payload.email ?? "").trim().toLowerCase(),
    area: String(payload.area ?? "").trim(),
    budget: Number(payload.budget),
    operation: payload.operation,
    propertyType: payload.propertyType,
    timeframe: payload.timeframe,
    consent: payload.consent,
    website: String(payload.website ?? "").trim()
  };
  if (!validText(lead.name, 2, 80) || !validText(lead.area, 2, 80)) return { error: "Ingresá nombre y zona válidos." };
  if (typeof payload.email !== "string" || lead.email.length > 160 ||
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(lead.email)) return { error: "El correo electrónico no es válido." };
  if (!Number.isSafeInteger(lead.budget) || lead.budget < 1 || lead.budget > 1000000000) return { error: "Presupuesto fuera de rango." };
  if (!OPERATIONS.includes(lead.operation) || !PROPERTY_TYPES.includes(lead.propertyType) ||
      !TIMEFRAMES.includes(lead.timeframe)) return { error: "Seleccioná las opciones de búsqueda." };
  if (lead.consent !== true) return { error: "Se requiere consentimiento para registrar y compartir la consulta." };
  if (lead.website.length > 120) return { error: "Datos inválidos." };
  return { lead };
}

export function qualifyLead(lead) {
  const priority = lead.timeframe === "urgente" ? "alta" : lead.timeframe === "30_dias" ? "media" : "exploratoria";
  return {
    priority,
    summary: (lead.operation === "alquilar" ? "Alquiler" : "Compra") + " · " +
      lead.propertyType + " · " + lead.area + " · ARS " + lead.budget.toLocaleString("es-AR"),
    warning: "Clasificación orientativa por plazo declarado; no confirma disponibilidad ni capacidad de pago."
  };
}
