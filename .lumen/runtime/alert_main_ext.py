from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response

from alert_main import app
from market_concierge import router as market_concierge_router

app.include_router(market_concierge_router)


@app.middleware("http")
async def market_concierge_primary_ui(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/market" or "text/html" not in str(response.headers.get("content-type") or ""):
        return response

    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    text = body.decode("utf-8", errors="replace")
    text = text.replace("/market/inquiry?listing_id=", "/market/concierge?listing_id=")
    text = text.replace("Solicitar alternativa", "Hablar con LUMEN")
    text = text.replace(
        "Cada consulta entra directamente al circuito autónomo de compradores y proveedores.",
        "El comprador puede hablar con LUMEN en lenguaje normal; LUMEN ordena el requerimiento y pregunta solo lo imprescindible antes de incorporarlo al circuito autónomo de compradores y proveedores.",
    )
    headers = dict(response.headers)
    headers.pop("content-length", None)
    return Response(content=text, status_code=response.status_code, headers=headers, media_type="text/html")
