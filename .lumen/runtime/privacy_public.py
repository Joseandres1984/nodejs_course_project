from __future__ import annotations

from fastapi.responses import HTMLResponse

from outbound_web import app

CONTACT_EMAIL = "lumenstock2026@gmail.com"
LAST_UPDATED = "14 de septiembre de 2026"

_BASE_STYLE = """
:root{color-scheme:dark;--bg:#061018;--panel:#0b1822;--line:#1d3c4c;--muted:#94adba;--text:#eef8fb;--lime:#d7ff64;--blue:#83d2ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% -10%,#12314a 0,#061018 38%);color:var(--text);font:16px Inter,system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.62;padding:24px}
main{max-width:860px;margin:0 auto}.brand{letter-spacing:.14em;text-transform:uppercase;color:var(--blue);font-weight:800}.card{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:24px;margin:16px 0}h1{font-size:38px;line-height:1.12;margin:8px 0 10px}h2{font-size:21px;margin:26px 0 8px}p,li{color:#d7e5eb}.muted{color:var(--muted)}a{color:var(--blue)}.tag{display:inline-block;border:1px solid #315363;border-radius:999px;padding:4px 9px;color:var(--muted);font-size:12px}.footer{margin-top:28px;color:var(--muted);font-size:13px}@media(max-width:600px){body{padding:14px}.card{padding:18px}h1{font-size:31px}}
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{title} · LUMEN B2B</title><style>{_BASE_STYLE}</style></head><body><main><div class='brand'>LUMEN B2B</div>{body}<div class='footer'>Última actualización: {LAST_UPDATED} · Contacto: <a href='mailto:{CONTACT_EMAIL}'>{CONTACT_EMAIL}</a></div></main></body></html>"""
    )


@app.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
def privacy_policy():
    return _page(
        "Política de Privacidad",
        f"""
        <h1>Política de Privacidad</h1>
        <p class='muted'>Esta política explica cómo LUMEN B2B trata información cuando una persona interactúa con nuestros canales digitales y, en particular, con nuestra cuenta profesional de Instagram.</p>
        <div class='card'>
          <span class='tag'>Responsable del servicio</span>
          <h2>1. Información que podemos tratar</h2>
          <p>Según la interacción y las funciones habilitadas por la plataforma, podemos recibir datos de perfil disponibles para la integración, identificadores técnicos de cuenta, nombre de usuario, contenido de mensajes directos, comentarios, respuestas, marcas de tiempo y datos necesarios para gestionar la conversación.</p>
          <h2>2. Para qué usamos la información</h2>
          <p>Usamos la información para recibir y responder consultas, organizar conversaciones, detectar solicitudes comerciales, gestionar oportunidades o leads, brindar soporte, prevenir abuso o spam, mantener registros operativos y mejorar la calidad del servicio.</p>
          <h2>3. Integración con Meta e Instagram</h2>
          <p>LUMEN B2B utiliza interfaces y servicios provistos por Meta Platforms para conectar nuestra cuenta profesional de Instagram con nuestras herramientas internas. El tratamiento que Meta realiza por su cuenta se rige por sus propios términos y políticas.</p>
          <h2>4. Compartición de datos</h2>
          <p>No vendemos datos personales. Podemos utilizar proveedores de infraestructura o servicios técnicos únicamente cuando sea necesario para operar LUMEN B2B, sujetos a sus condiciones de seguridad y privacidad. También podremos revelar información cuando exista una obligación legal aplicable.</p>
          <h2>5. Conservación y seguridad</h2>
          <p>Conservamos la información durante el tiempo razonablemente necesario para atender la conversación, mantener la relación comercial, cumplir obligaciones aplicables y proteger la seguridad del servicio. Aplicamos medidas técnicas y organizativas razonables para reducir accesos no autorizados, pérdida o uso indebido.</p>
          <h2>6. Decisiones y automatización</h2>
          <p>Nuestras herramientas pueden clasificar consultas, priorizar mensajes y preparar respuestas sugeridas. Cuando una acción requiere aprobación humana, la respuesta no se envía hasta que una persona autorizada la aprueba.</p>
          <h2>7. Derechos y solicitudes</h2>
          <p>Podés solicitar información, actualización, corrección o eliminación de datos vinculados con tu interacción con LUMEN B2B escribiendo a <a href='mailto:{CONTACT_EMAIL}'>{CONTACT_EMAIL}</a>. Para proteger a los usuarios, podremos pedir datos razonables para verificar la identidad y localizar la información correspondiente.</p>
          <h2>8. Eliminación de datos</h2>
          <p>Las instrucciones para solicitar la eliminación de datos están disponibles en <a href='/data-deletion'>/data-deletion</a>.</p>
          <h2>9. Cambios a esta política</h2>
          <p>Podemos actualizar esta política cuando cambien nuestras funciones, integraciones o requisitos legales. La fecha de la última actualización se muestra al pie de esta página.</p>
        </div>
        """,
    )


@app.get("/data-deletion", response_class=HTMLResponse, include_in_schema=False)
def data_deletion():
    return _page(
        "Eliminación de datos",
        f"""
        <h1>Solicitud de eliminación de datos</h1>
        <div class='card'>
          <p>Si interactuaste con LUMEN B2B a través de Instagram u otro canal conectado y querés solicitar la eliminación de datos asociados a esa interacción, enviá un correo a <a href='mailto:{CONTACT_EMAIL}'>{CONTACT_EMAIL}</a> con el asunto <b>“Solicitud de eliminación de datos”</b>.</p>
          <p>Indicá el nombre de usuario o identificador del canal desde el que interactuaste y una descripción breve que nos permita localizar la información. No envíes contraseñas ni códigos de acceso.</p>
          <p>Podremos solicitar información adicional mínima para verificar que la solicitud corresponde a la persona titular de los datos. Procesaremos las solicitudes de acuerdo con las obligaciones legales aplicables y las necesidades legítimas de seguridad, prevención de fraude y conservación exigida por ley.</p>
          <p><a href='/privacy'>Volver a la Política de Privacidad</a></p>
        </div>
        """,
    )


print({"privacy_public": {"status": "active", "routes": ["/privacy", "/data-deletion"]}}, flush=True)
