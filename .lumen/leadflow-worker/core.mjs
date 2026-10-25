export class InputError extends Error {}
export function qualify(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new InputError("Datos inválidos.");
  const zona = typeof data.zona === "string" ? data.zona.trim().replace(/\s+/g, " ").slice(0,80) : "";
  const presupuesto = Number(data.presupuesto);
  const ambientes = Number(data.ambientes);
  const urgencia = data.urgencia;
  if (zona.length < 2) throw new InputError("Ingresá una zona válida.");
  if (!Number.isSafeInteger(presupuesto) || presupuesto < 100000 || presupuesto > 100000000) throw new InputError("Presupuesto fuera del rango de la demo.");
  if (!Number.isInteger(ambientes) || ambientes < 1 || ambientes > 8) throw new InputError("Elegí entre 1 y 8 ambientes.");
  if (!["esta_semana","este_mes","flexible"].includes(urgencia)) throw new InputError("Seleccioná un plazo válido.");
  const prioridad = urgencia === "esta_semana" ? "alta" : urgencia === "este_mes" ? "media" : "exploratoria";
  const proximo_paso = prioridad === "alta" ? "Ofrecer contacto temprano con un asesor." :
    prioridad === "media" ? "Proponer una conversación con un asesor." :
    "Seguimiento solo si la persona acepta recibir novedades.";
  return {
    zona, presupuesto, ambientes, urgencia, prioridad, proximo_paso,
    resumen: "Búsqueda de alquiler en " + zona + ", " + ambientes + " ambientes, hasta ARS " + presupuesto.toLocaleString("es-AR") + ".",
    criterio: "La prioridad depende solamente del plazo declarado; no mide intención de compra ni disponibilidad."
  };
}
