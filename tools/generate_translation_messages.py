"""Mark metadata labels used dynamically by Frappe's standard extractors."""
import ast
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'hospitality_suite/translation_messages.py'
messages=set()
for path in sorted((ROOT/'hospitality_suite').glob('*.py')):
    if path.name in {'demo.py','translation_messages.py'}:continue
    tree=ast.parse(path.read_text(encoding='utf-8'))
    docstrings={id(node.value) for parent in ast.walk(tree) if isinstance(parent,(ast.Module,ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))
                for node in parent.body[:1] if isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant)}
    for node in ast.walk(tree):
        if not isinstance(node,ast.Constant) or not isinstance(node.value,str) or id(node) in docstrings:continue
        text=node.value.strip()
        if not text or len(text)>2200 or not re.search(r'[A-Za-zÀ-ÿ]',text):continue
        if text.startswith(('HS ','SELECT ','UPDATE ','INSERT ','DELETE ','CREATE ','http','/')):continue
        if not (re.search(r'[À-ÿ]',text) or (re.match(r'[A-Z]',text) and re.search(r'[a-z]',text))):continue
        if re.fullmatch(r'[\w.-]+\.[\w.-]+',text) or '\n' in text:continue
        messages.add(text)
lines=['"""Generated metadata message markers. Never called on a request path."""','import frappe','','','def metadata_messages():','    return (']
lines.extend('        frappe._('+json.dumps(text,ensure_ascii=False)+'),' for text in sorted(messages))
lines.extend(['    )',''])
TARGET.write_text('\n'.join(lines),encoding='utf-8',newline='\n')
print('Metadata messages:',len(messages))
