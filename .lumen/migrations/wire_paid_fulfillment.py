from pathlib import Path


def main() -> None:
    path = Path('.lumen/runtime/zero_entry.py')
    text = path.read_text(encoding='utf-8')
    marker = 'paid_fulfillment_runtime.run_once()'
    if marker in text:
        print('paid fulfillment wiring already current')
        return

    anchor = '''import zero_discovery_quality_runtime  # noqa: F401,E402\n\n# First-cash demand priority:'''
    insert = '''import zero_discovery_quality_runtime  # noqa: F401,E402\n\n# A settled customer order outranks new prospecting. This dedicated lane consumes only\n# x402 orders already proven settled/queued in D1, claims at most one job atomically,\n# gathers zero-cost public evidence and produces structured report JSON. It cannot send\n# mail, create a charge, move funds or mark a report delivered. Any failure stays closed\n# inside the fulfillment lane so the paid job remains auditable for retry/review.\ntry:\n    import paid_fulfillment_runtime  # noqa: E402\n    _paid_fulfillment = paid_fulfillment_runtime.run_once()\n    print({"paid_fulfillment_runtime": _paid_fulfillment}, flush=True)\nexcept Exception as exc:\n    print({"paid_fulfillment_runtime": {"status": "degraded_fail_closed", "error": f"{type(exc).__name__}: {str(exc)[:300]}", "outgoing_spend": False, "delivery_attempted": False}}, flush=True)\n\n# First-cash demand priority:'''
    if anchor not in text:
        raise SystemExit('zero_entry paid fulfillment anchor not found')
    path.write_text(text.replace(anchor, insert, 1), encoding='utf-8')
    print('paid fulfillment runtime wired before prospecting search')


if __name__ == '__main__':
    main()
