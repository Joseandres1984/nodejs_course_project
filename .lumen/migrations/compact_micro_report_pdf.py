from pathlib import Path


ARTICLE_OLD = '<body><article class="report"><header class="${tier===\'micro\'?\'cover micro-cover\':\'cover\'}">'
ARTICLE_NEW = '<body><article class="report ${tier===\'micro\'?\'micro-report\':\'full-report\'}"><header class="${tier===\'micro\'?\'cover micro-cover\':\'cover\'}">'

# Semantic markers for the current production compaction. Do not couple the
# migration to one huge minified CSS string: the renderer is intentionally
# allowed to evolve while these guarantees remain true.
CURRENT_MARKERS = [
    ARTICLE_NEW,
    '.micro-report .body{',
    '.micro-report .section{',
    '.micro-report .findings article',
    '.micro-report .evidence article',
    '.micro-report .recommendation{',
    '.micro-report .section{break-inside:auto}',
]

COMPACT_CSS = (
    '.micro-report .micro-cover{padding:22px 38px 18px!important}'
    '.micro-report .micro-cover h1{font-size:30px!important;margin:14px 0 6px!important}'
    '.micro-report .micro-cover .covermeta{margin-top:12px!important;gap:8px!important}'
    '.micro-report .micro-cover .covermeta strong{font-size:10px!important}'
    '.micro-report .body{padding:18px 38px 24px!important;font-size:11.5px!important;line-height:1.32!important}'
    '.micro-report .request{padding:10px 14px!important;margin-bottom:12px!important}'
    '.micro-report .request p{font-size:13px!important}'
    '.micro-report .executive{padding:13px 15px!important;margin-bottom:12px!important}'
    '.micro-report .executive p{font-size:15px!important}'
    '.micro-report .section{padding:11px 0!important;break-inside:auto!important;page-break-inside:auto!important}'
    '.micro-report .section h2{font-size:17px!important;margin:0 0 7px!important}'
    '.micro-report .section li{margin:4px 0!important}'
    '.micro-report .findings{gap:6px!important}'
    '.micro-report .findings article{grid-template-columns:28px 1fr!important;gap:7px!important;padding:8px 9px!important}'
    '.micro-report .findings article>span{font-size:17px!important}'
    '.micro-report .findings p{margin:2px 0!important}'
    '.micro-report .tablewrap{border-radius:8px!important}'
    '.micro-report th,.micro-report td{padding:6px 7px!important;font-size:9px!important;line-height:1.25!important}'
    '.micro-report .riskgrid,.micro-report .evidence{gap:6px!important}'
    '.micro-report .risk{padding:8px 10px!important}'
    '.micro-report .evidence article{grid-template-columns:24px 1fr!important;gap:7px!important;padding:8px!important}'
    '.micro-report .source-index{width:21px!important;height:21px!important;font-size:10px!important}'
    '.micro-report .evidence p{margin:3px 0!important}'
    '.micro-report .recommendation{padding:14px 16px!important;margin-top:12px!important;border-radius:12px!important}'
    '.micro-report .recommendation h2{font-size:20px!important;margin:4px 0 6px!important}'
    '.micro-report .recommendation p{font-size:14px!important}'
    '.micro-report .footer{padding:12px 38px 18px!important;font-size:9px!important}'
)


def already_current(text: str) -> bool:
    return all(marker in text for marker in CURRENT_MARKERS)


def main() -> None:
    path = Path('.lumen/reporting/render_report.mjs')
    text = path.read_text(encoding='utf-8')

    if already_current(text):
        print('micro-report PDF compaction already current')
        return

    changed = False

    if ARTICLE_OLD in text:
        text = text.replace(ARTICLE_OLD, ARTICLE_NEW, 1)
        changed = True
    elif ARTICLE_NEW not in text:
        raise SystemExit('report article anchor not found')

    # Insert compact micro styles immediately before the print media block. This
    # avoids depending on exact prior CSS values and keeps the migration safe
    # across renderer formatting changes.
    if '.micro-report .micro-cover{' not in text:
        anchor = '@media print{'
        if anchor not in text:
            raise SystemExit('print media anchor not found')
        text = text.replace(anchor, COMPACT_CSS + anchor, 1)
        changed = True

    # Ensure micro sections can flow across pages while atomic cards/tables stay
    # together. This is the key page-count control without removing content.
    print_anchor = '.body{padding-top:34px}'
    flow_css = (
        '.micro-report .body{padding-top:20px}'
        '.micro-report .section{break-inside:auto}'
        '.micro-report .findings article,.micro-report .risk,.micro-report .evidence article,.micro-report .tablewrap{break-inside:avoid}'
    )
    if '.micro-report .section{break-inside:auto}' not in text:
        if print_anchor not in text:
            raise SystemExit('print body anchor not found')
        text = text.replace(print_anchor, print_anchor + flow_css, 1)
        changed = True

    if not already_current(text):
        missing = [marker for marker in CURRENT_MARKERS if marker not in text]
        raise SystemExit(f'micro-report compaction incomplete; missing markers: {missing}')

    if changed:
        path.write_text(text, encoding='utf-8')
        print('micro-report PDF compaction applied')
    else:
        print('micro-report PDF compaction already current')


if __name__ == '__main__':
    main()
