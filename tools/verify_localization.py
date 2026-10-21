"""Read-only check of the app's sources through Frappe's native extractor."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import frappe
from jinja2 import Environment

bench=Path('/home/frappe/benches/hospitality-bench')
repo=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--output',default='docs/evidence/localization-extraction.json')
parser.add_argument('--language-review',action='store_true')
args=parser.parse_args()
os.chdir(bench/'sites')
frappe.init(site='hospitality.localhost',sites_path=str(bench/'sites'))
frappe.connect()
try:
    assert frappe.conf.allow_tests
    from frappe.translate import get_server_messages
    messages=get_server_messages('hospitality_suite')
    texts={row[1] for row in messages}
    required=['Importe','Cliente pagador','CONFIRMACIÓN DE RESERVA','Incluido: {0} × {1}',
              'Incluido en extensión: {0} × {1}','Sin conexión · operación pausada',
              'No existe una tarifa aplicable a la fecha y al pagador',
              'Tiempo restante: {0} h {1} min','Presentación','Entrada prevista',
              'Buscar artículo por nombre o código','Vista operativa','Referencias técnicas']
    if args.language_review:
        required += ['Baño revisado','Cama y ropa revisadas','Superficies y equipo revisados',
                     'Administrador de Hospitality','Devolver {0}','Extracto bancario','Factura','Vuelto',
                     'Hora adicional por tiempo','Confirmación de alojamiento','Solicitar una reserva',
                     'Reapertura autorizada por','Disponibilidad','Sin precio','Con precio']
    missing=sorted(set(required)-texts)
    assert not missing,missing
    templates=[*sorted((repo/'hospitality_suite/templates/print').glob('*.html')),*sorted((repo/'hospitality_suite/www').glob('*.html'))]
    for template in templates:
        Environment().parse(template.read_text(encoding='utf-8'))
    proof=dict(native_extractor='frappe.translate.get_server_messages',source_occurrences=len(messages),unique_messages=len(texts),
               representative_messages=required,templates_parsed=len(templates),
               messages_sha256=hashlib.sha256('\n'.join(sorted(texts)).encode()).hexdigest(),
               full_language_pack=False,translation_fixtures='Native Translation records in rolled-back integration transactions')
    (repo/args.output).write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(proof,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
