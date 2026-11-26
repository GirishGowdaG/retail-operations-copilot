"""RetailOps: answer stockout WHY questions with cited causes, not only stock tables.

Run from the RetailOps project directory:
    python fix_retail_stockout_explanations.py
    docker compose up -d --build --no-deps backend frontend

This modifies only backend/app/rag.py and frontend/src/main.jsx, making backups.
It does not edit data, credentials, Docker Compose, ports, or AutoCare.
"""
from pathlib import Path
import ast
import shutil
import sys

ROOT = Path.cwd()
RAG = ROOT / 'backend' / 'app' / 'rag.py'
JSX = ROOT / 'frontend' / 'src' / 'main.jsx'
BACKEND_MARKER = '# RETAILOPS_STOCKOUT_CAUSE_V1'
FRONTEND_MARKER = '/* RETAILOPS_STOCKOUT_CAUSE_UI_V1 */'

BACKEND_HELPER = '''# RETAILOPS_STOCKOUT_CAUSE_V1

def explain_stockout_from_evidence(question, sql_result, sources):
    """For WHY-stockout questions, combine measured stock with documented causes.

    The policy describes a *synthetic scenario*. Never treat narrative causes as
    a measured finding without sales-velocity and purchase-order reconciliation.
    """
    import re
    q = question.lower()
    sku_match = re.search(r'\\bP\\d{3}\\b', question, flags=re.I)
    asks_why = bool(re.search(r'\\b(why|cause|causes|reason|reasons)\\b', q))
    asks_stock = any(term in q for term in ('stock', 'shortage', 'replenish', 'inventory'))
    if not (sku_match and asks_why and asks_stock and isinstance(sql_result, list)):
        return None
    sku = sku_match.group().upper()
    inventories = [row for row in sql_result if isinstance(row, dict)
                   and str(row.get('sku', '')).upper() == sku
                   and 'quantity' in row and 'reorder_point' in row]
    if not inventories:
        return None
    low = sum(1 for row in inventories if row['quantity'] < row['reorder_point'])
    empty = sum(1 for row in inventories if row['quantity'] == 0)
    product = str(inventories[0].get('product', sku))

    # Only attribute a cause to sources that explicitly mention this SKU and cause.
    cause = None
    cause_source = None
    for source in sources or []:
        for field in ('context', 'excerpt'):
            source_text = str(source.get(field) or '')
            for sentence in re.split(r'(?<=[.!?])\\s+|\\n', source_text):
                if not re.search(r'\\b' + re.escape(sku) + r'\\b', sentence, flags=re.I):
                    continue
                match = re.search(r'\\b(?:caused by|due to|driven by)\\s+([^.!?;]{4,180})',
                                  sentence, flags=re.I)
                if match:
                    cause = match.group(1).strip(' .,:;')
                    cause_source = source
                    break
            if cause:
                break
        if cause:
            break

    lines = ['**Quick answer**']
    if cause:
        lines.append(
            f'For {product} ({sku}), the synthetic replenishment policy describes '
            f'**{cause}** as the causes of the simulated recurring stockouts. '
            'This is the documented scenario, not a confirmed numerical root-cause analysis.'
        )
    else:
        lines.append(
            f'{product} ({sku}) is running low, but the retrieved documents do not '
            'establish a cause. High sales or supply delays must not be asserted '
            'without supporting evidence.'
        )
    lines.extend([
        '', '**What the inventory data shows**',
        f'- **{low} of {len(inventories)} locations** have stock below their reorder thresholds.',
        f'- **{empty} locations** have zero units recorded.',
        '', '**What to check next**',
        '- Compare recent sales velocity with the demand forecast.',
        '- Check outstanding or delayed replenishment purchase orders and supplier lead times.',
        '- Review warehouse stock and possible transfers between locations.',
        '', '**Evidence and limitation**',
        'Inventory records confirm low availability, not its cause. '
        'Sales trends and delayed purchase orders have not been quantitatively joined '
        'to this stock snapshot.',
        '- Inventory source: RetailOps PostgreSQL (synthetic demonstration data).',
    ])
    if cause_source:
        page = cause_source.get('page_number') or 'not available'
        lines.append(
            f'- Document source: {cause_source.get("document_name", "Unknown document")}, '
            f'section {cause_source.get("section") or "not available"}, page {page}.'
        )
    return '\\n'.join(lines)

'''

FRONTEND_CHANGE_OLD = ''' return <div className="retail-answer"><div className="retail-answer-eyebrow">Quick summary</div><h3>{heading}</h3><p className="retail-answer-summary">{summary}</p>'''
FRONTEND_CHANGE_NEW = ''' /* RETAILOPS_STOCKOUT_CAUSE_UI_V1 */
 if((/\\b(why|cause|causes|reason|reasons)\\b/i.test(q)) && /stock|shortage|inventory|replenish/i.test(q) &&
    String(message.text||'').startsWith('**Quick answer**') && rows.some(r=>r&&'reorder_point' in r)){
  return <div className="retail-answer"><div className="retail-answer-eyebrow">Evidence-based explanation</div>
    <RetailReadableText value={message.text}/>
    {rows.length>0&&<details className="retail-answer-more"><summary>View {rows.length} inventory records</summary>
      <RetailResultTable rows={rows} cols={cols}/></details>}
    <div className="retail-answer-source">Sources: RetailOps PostgreSQL and cited documents · synthetic data</div>
  </div>;
 }
 return <div className="retail-answer"><div className="retail-answer-eyebrow">Quick summary</div><h3>{heading}</h3><p className="retail-answer-summary">{summary}</p>'''


def main():
    if not all(p.is_file() for p in (RAG, JSX)) or not (ROOT / 'docker-compose.yml').is_file():
        print('ERROR: Run this in the RetailOps project root (next to docker-compose.yml).')
        return 1
    rag = RAG.read_text(encoding='utf-8')
    jsx = JSX.read_text(encoding='utf-8')
    if BACKEND_MARKER in rag and FRONTEND_MARKER in jsx:
        print('Already installed. No changes required.')
        return 0
    if BACKEND_MARKER in rag or FRONTEND_MARKER in jsx:
        print('ERROR: Partial installation detected. No files changed.')
        return 1
    # Previous fixes must be present. Refuse rather than overwriting unknown code.
    start = "    # mode_sql_verified_v2: SQL data is presented deterministically, not rewritten by an LLM.\n    if sql_result is not None:\n        return render_sql_answer(question, sql_result, sources), 'sql-grounded'"
    if start not in rag or rag.count('def compose_answer(') != 1 or jsx.count(FRONTEND_CHANGE_OLD) != 1 or 'function RetailSqlAnswer({message})' not in jsx:
        print('ERROR: Your project does not match the supported RetailOps version with the earlier fixes.')
        print('No files changed. Send this message and the output to ChatGPT for a tailored patch.')
        return 1
    replacement = "    explanation = explain_stockout_from_evidence(question, sql_result, sources)\n    if explanation is not None:\n        return explanation, 'sql-grounded'\n" + start
    candidate_rag = rag.replace(start, replacement, 1).replace('def compose_answer(', BACKEND_HELPER + 'def compose_answer(', 1)
    candidate_jsx = jsx.replace(FRONTEND_CHANGE_OLD, FRONTEND_CHANGE_NEW, 1)
    try:
        ast.parse(candidate_rag)
    except SyntaxError as e:
        print('ERROR: Python syntax validation failed:', e)
        return 1
    for path, modified in ((RAG, candidate_rag), (JSX, candidate_jsx)):
        backup = path.with_name(path.name + '.before_stockout_explanation.bak')
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(modified, encoding='utf-8')
        print('Updated:', path.relative_to(ROOT), '(backup:', backup.name + ')')
    print('SUCCESS: RetailOps WHY-stockout answers now start with a source-grounded explanation.')
    print('No database, ports, API keys, Docker settings, or AutoCare project files changed.')
    print('NEXT: docker compose up -d --build --no-deps backend frontend')
    return 0


if __name__ == '__main__':
    sys.exit(main())
