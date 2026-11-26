"""Fix human-readable SQL answers and reject unreconciled retail return-rate values.

Run from retail-operations-copilot root on Windows:
    python fix_retail_correct_outputs.py

This does NOT modify the database, Docker configuration, .env, other projects, or AutoCare.
Backups are created beside each changed Python file.
"""
from pathlib import Path
import ast
import shutil
import sys

ROOT = Path.cwd()
ANALYTICS = ROOT / 'backend' / 'app' / 'analytics.py'
RAG = ROOT / 'backend' / 'app' / 'rag.py'
VERSION = 'mode_sql_verified_v2'

OLD_START = "    if any(x in q for x in ['highest return','return rate','most returned']):"
OLD_END = "    if 'delayed' in q and ('order' in q or 'po' in q):"
NEW_BRANCH = '''    if any(x in q for x in ['highest return','return rate','most returned']):
        # The two sources contain independent synthetic transactions. Do not treat
        # returns > recorded sales as a valid percentage or silently cap at 100%.
        sales_query = select(Sale.product_id, func.sum(Sale.quantity))
        returns_query = select(Return.product_id, func.sum(Return.quantity))
        if 'this month' in q:
            now = datetime.utcnow()
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            next_start = (start.replace(year=start.year + 1, month=1)
                          if start.month == 12 else start.replace(month=start.month + 1))
            sales_query = sales_query.where(Sale.sold_at >= start, Sale.sold_at < next_start)
            returns_query = returns_query.where(Return.returned_at >= start, Return.returned_at < next_start)
        sold_by_product = dict(db.execute(sales_query.group_by(Sale.product_id)).all())
        returned_by_product = dict(db.execute(returns_query.group_by(Return.product_id)).all())
        names = dict(db.execute(select(Product.id, Product.name)).all())
        valid, unreconciled = [], []
        for product_id, raw_returned in returned_by_product.items():
            returned = int(raw_returned or 0)
            sold = int(sold_by_product.get(product_id) or 0)
            record = {
                'product': names.get(product_id, f'Product ID {product_id}'),
                'sold_units': sold,
                'returned_units': returned,
                'return_rate_percent': None,
            }
            if sold <= 0:
                record['data_quality'] = 'No recorded sales for returned product'
                unreconciled.append(record)
            elif returned > sold:
                record['data_quality'] = 'Returned units exceed recorded sold units'
                unreconciled.append(record)
            else:
                record['return_rate_percent'] = round(100 * returned / sold, 2)
                record['data_quality'] = 'ok'
                valid.append(record)
        valid.sort(key=lambda r: (-r['return_rate_percent'], -r['returned_units'], r['product']))
        unreconciled.sort(key=lambda r: (-r['returned_units'], r['product']))
        # Show valid leaders first, plus anomalous rows for auditing.
        return valid[:10] + unreconciled[:5]
'''

RAG_INSERT = '''    # mode_sql_verified_v2: SQL data is presented deterministically, not rewritten by an LLM.
    if sql_result is not None:
        return render_sql_answer(question, sql_result, sources), 'sql-grounded'
'''

FORMATTER = '''

def render_sql_answer(question, sql_result, sources):
    """Readable, evidence-first output that is safe for the frontend's plain-text bubble."""
    if isinstance(sql_result, list) and any(
        isinstance(row, dict) and 'return_rate_percent' in row for row in sql_result
    ):
        period = 'this calendar month' if 'this month' in question.lower() else 'all available records'
        lines = [f'Products with the highest recorded return ratios ({period})', '']
        valid = [r for r in sql_result if isinstance(r, dict)
                 and r.get('return_rate_percent') is not None and r.get('data_quality', 'ok') == 'ok']
        bad = [r for r in sql_result if isinstance(r, dict)
               and (r.get('return_rate_percent') is None or r.get('data_quality', 'ok') != 'ok')]
        if valid:
            for number, row in enumerate(valid, 1):
                lines.append(
                    f'{number}. {row["product"]}: {float(row["return_rate_percent"]):.2f}% '
                    f'({int(row["returned_units"])} returned / {int(row["sold_units"])} sold)'
                )
        else:
            lines.append('No return rates could be validated from recorded sales.')
        if bad:
            lines.extend(['', 'Excluded from ranking (inconsistent source records):'])
            for row in bad:
                lines.append(
                    f'- {row["product"]}: {int(row["returned_units"])} returned / '
                    f'{int(row["sold_units"])} sold — {row.get("data_quality", "unreconciled")}'
                )
        lines.extend([
            '',
            'Formula: returned units / sold units × 100, when sold units > 0 and returns <= sales.',
            'Data note: These are ratios from independent synthetic transaction totals, '
            'not audited customer-level return rates. Sales and returns are not linked to individual orders.',
            'Source: RetailOps PostgreSQL sales and returns tables.',
        ])
    elif isinstance(sql_result, list):
        lines = ['Retail database results', '']
        if not sql_result:
            lines.append('No matching records were found.')
        for i, row in enumerate(sql_result[:20], 1):
            if isinstance(row, dict):
                fields = ' | '.join(f'{str(k).replace("_", " ").capitalize()}: {v}' for k, v in row.items())
                lines.append(f'{i}. {fields}')
            else:
                lines.append(f'{i}. {row}')
        lines.extend(['', 'Source: RetailOps PostgreSQL database.'])
    elif isinstance(sql_result, dict):
        lines = ['Retail database results', '']
        lines.extend(f'{str(k).replace("_", " ").capitalize()}: {v}' for k, v in sql_result.items())
        lines.extend(['', 'Source: RetailOps PostgreSQL database.'])
    else:
        lines = [str(sql_result), '', 'Source: RetailOps PostgreSQL database.']
    if sources:
        lines.extend(['', 'Related source documents:'])
        for s in sources[:3]:
            lines.append(
                f'- {s.get("document_name", "Unknown source")} | '
                f'section: {s.get("section") or "N/A"} | '
                f'page: {s.get("page_number") or "N/A"}'
            )
    return '\\n'.join(lines)
'''


def main():
    if not ANALYTICS.is_file() or not RAG.is_file():
        sys.exit('ERROR: Run this script from the RetailOps project root (next to docker-compose.yml).')
    analytics = ANALYTICS.read_text(encoding='utf-8')
    rag = RAG.read_text(encoding='utf-8')
    if VERSION in analytics and VERSION in rag:
        print('The correct-output fix is already installed. No changes made.')
        return
    # Validate both files BEFORE touching either one.
    if VERSION not in analytics:
        if analytics.count(OLD_START) != 1 or analytics.count(OLD_END) != 1:
            sys.exit('ERROR: Unrecognized analytics.py version; no files changed.')
        candidate_analytics = analytics[:analytics.index(OLD_START)] + \
            NEW_BRANCH.replace('        # The two sources', '        # mode_sql_verified_v2: The two sources', 1) + \
            analytics[analytics.index(OLD_END):]
    else:
        candidate_analytics = analytics
    if VERSION not in rag:
        func = 'def compose_answer(question,sources,sql_result=None,history=None):\n'
        if rag.count(func) != 1 or 'def format_sql(obj):' not in rag:
            sys.exit('ERROR: Unrecognized rag.py version; no files changed.')
        candidate_rag = rag.replace(func, func + RAG_INSERT, 1) + FORMATTER
    else:
        candidate_rag = rag
    try:
        ast.parse(candidate_analytics, filename=str(ANALYTICS))
        ast.parse(candidate_rag, filename=str(RAG))
    except SyntaxError as exc:
        sys.exit(f'ERROR: Generated syntax is invalid; no files changed: {exc}')
    for path, before, after in ((ANALYTICS, analytics, candidate_analytics), (RAG, rag, candidate_rag)):
        if before == after:
            continue
        backup = path.with_name(path.name + '.before_correct_output.bak')
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(after, encoding='utf-8')
        print(f'Updated {path.relative_to(ROOT)}; backup: {backup.name}')
    print('Done. No database, port, Docker, or AutoCare configuration changed.')
    print('Next: docker compose up -d --build --no-deps backend')


if __name__ == '__main__':
    main()
