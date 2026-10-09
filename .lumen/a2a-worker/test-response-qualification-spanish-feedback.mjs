import assert from "node:assert/strict";
import { classifyCommercialResponse } from "./response-qualification.js";

// Generic synthetic commercial replies. Do not embed real prospect email content.
const original = "LUMEN can research public opportunities and provide evidence-backed summaries.";
const cases = [
  ["Gracias por la propuesta. Por el momento preferimos no avanzar con la evaluacion.", "DECLINED", "LOST"],
  ["Agradecemos la informacion, pero preferimos no continuar por ahora.", "DECLINED", "LOST"],
  ["Nos resulta interesante, pero no vamos a avanzar con el alta de nuestro perfil.", "DECLINED", "LOST"],
  ["We prefer not to move forward at this time.", "DECLINED", "LOST"],
  ["La propuesta nos resulta interesante. ¿Que precios manejan y cuales son las condiciones?", "COMMERCIAL_QUESTION", "NEGOTIATING"],
  ["¿Podrian compartirnos oportunidades reales con fuente publica?", "COMMERCIAL_QUESTION", "NEGOTIATING"],
  ["Estamos interesados en conocer mas detalles.", "COMMERCIAL_INTEREST", "NEGOTIATING"],
  ["Gracias por la informacion.", "GENERIC_RESPONSE", "RESPONDED"],
  ["Please send the checkout link.", "PURCHASE_INTENT", "NEGOTIATING"]
];
for (const [text, expectedClass, expectedStage] of cases) {
  const got = classifyCommercialResponse(text, original);
  assert.equal(got.responseClass, expectedClass, text);
  assert.equal(got.stage, expectedStage, text);
  if (expectedClass === "DECLINED") {
    assert.equal(got.qualified, false, text);
    assert.equal(got.buyingIntent, false, text);
    assert.equal(got.nextAction, "close_and_move_on", text);
  }
}
console.log("LUMEN_SPANISH_COMMERCIAL_FEEDBACK_CLASSIFICATION_OK");
