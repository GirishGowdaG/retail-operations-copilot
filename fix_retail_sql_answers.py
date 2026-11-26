"""One-time safe patch: give database-grounded answers precedence over local LLM refusals.
Run in retail-operations-copilot project root: python fix_retail_sql_answers.py
A backup of backend/app/rag.py is saved before editing. Does not change Docker/AutoCare.
"""
from pathlib import Path
import ast
import shutil

path = Path('backend/app/rag.py')
if not path.is_file():
    raise SystemExit('Cannot find backend/app/rag.py. Run this from the retail-operations-copilot directory.')

original = path.read_text(encoding='utf-8')
marker = "    if settings.openai_api_key:\n        from openai import OpenAI\n"
if "mode_sql_grounded_v1" in original:
    print('Patch already installed. No changes made.')
    raise SystemExit(0)
if original.count(marker) != 1:
    raise SystemExit('Expected compose_answer section not found exactly once; no changes made.')

replacement = '''    # mode_sql_grounded_v1: SQL evidence must not be discarded by a small local LLM.
    # The database remains the authority for structured results; document QA still uses the LLM.
    if sql_result is not None:
        warning = ''
        if isinstance(sql_result, list) and any(
            isinstance(item, dict)
            and isinstance(item.get('return_rate_percent'), (int, float))
            and item['return_rate_percent'] > 100
            for item in sql_result
        ):
            warning = ('\\n\\n**Data quality warning:** Some calculated return rates exceed 100%. '
                       'The synthetic returns and sales counts may not be comparable. '
                       'Do not treat those percentages as validated business return rates.')
        citations = ('\\n\\n**Related documents**\\n' + '\\n'.join(
            f'- {s["document_name"]} / {s["section"]} '
            f'(page {s["page_number"] if s["page_number"] else "N/A"})'
            for s in sources[:3]
        )) if sources else ''
        return (f'**Retail database results**\\n\\n{format_sql(sql_result)}'
                f'{warning}{citations}\\n\\n_Source: RetailOps PostgreSQL database._',
                'sql-grounded')
    if settings.openai_api_key:
        from openai import OpenAI
'''
updated = original.replace(marker, replacement, 1)
ast.parse(updated)
backup = path.with_name('rag.py.before_sql_fix.bak')
if not backup.exists():
    shutil.copy2(path, backup)
path.write_text(updated, encoding='utf-8')
print('Patched backend/app/rag.py successfully.')
print('Backup:', backup)
print('Next: docker compose up -d --build --no-deps backend')
