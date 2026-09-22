from pathlib import Path


def main() -> None:
    path = Path('.lumen/x402-worker/worker-v2.js')
    text = path.read_text()
    changed = False

    old_gate = '''  const result = await x402Gate(c, next);\n  const paymentSignature = c.req.header("payment-signature") || c.req.header("x-payment") || "";'''
    hardened_gate = '''  let result;\n  try {\n    result = await x402Gate(c, next);\n  } catch (error) {\n    console.error("x402_gate_error", error);\n    return c.json({\n      ok:false,\n      error:"x402_gate_failed",\n      detail:clean(error?.message || error,300),\n      paymentAttempted:false,\n      outgoingSpendEnabled:false,\n    }, 503);\n  }\n  const paymentSignature = c.req.header("payment-signature") || c.req.header("x-payment") || "";'''

    if old_gate in text:
        text = text.replace(old_gate, hardened_gate, 1)
        changed = True
    elif hardened_gate not in text:
        raise SystemExit('missing x402 gate patch anchor')

    # Hono middleware commonly finalizes c.res and resolves without returning a
    # Response. Returning that undefined value from our wrapper makes Hono emit
    # a generic 500 even though x402 already constructed a valid 402 challenge.
    # Preserve an explicit Response when present; otherwise return c.res.
    old_return = '''  return result;\n});\n\nfunction publicCatalog(origin) {'''
    safe_return = '''  return result instanceof Response ? result : c.res;\n});\n\nfunction publicCatalog(origin) {'''
    if old_return in text:
        text = text.replace(old_return, safe_return, 1)
        changed = True
    elif safe_return not in text:
        raise SystemExit('missing x402 response return anchor')

    if changed:
        path.write_text(text)
        print('x402 gate diagnostics and Hono response preservation applied')
    else:
        print('x402 gate hardening already current')


if __name__ == '__main__':
    main()
