from pathlib import Path


def main() -> None:
    path = Path('.lumen/x402-worker/worker-v2.js')
    text = path.read_text()

    old = '''  const result = await x402Gate(c, next);\n  const paymentSignature = c.req.header("payment-signature") || c.req.header("x-payment") || "";'''
    new = '''  let result;\n  try {\n    result = await x402Gate(c, next);\n  } catch (error) {\n    console.error("x402_gate_error", error);\n    return c.json({\n      ok:false,\n      error:"x402_gate_failed",\n      detail:clean(error?.message || error,300),\n      paymentAttempted:false,\n      outgoingSpendEnabled:false,\n    }, 503);\n  }\n  const paymentSignature = c.req.header("payment-signature") || c.req.header("x-payment") || "";'''

    if new in text:
        print('x402 gate diagnostics already current')
        return
    if old not in text:
        raise SystemExit('missing x402 gate patch anchor')

    text = text.replace(old, new, 1)
    path.write_text(text)
    print('x402 gate diagnostics applied')


if __name__ == '__main__':
    main()
