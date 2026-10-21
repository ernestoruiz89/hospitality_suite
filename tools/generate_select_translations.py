"""Keep English Select values while localizing native HS controls by DocType."""
import csv
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from hospitality_suite.schema import SCHEMA
from hospitality_suite.schema_labels import OPTION_LABELS,OPTION_CONTEXT

target=ROOT/'hospitality_suite/translations/es.csv'
with target.open(encoding='utf-8',newline='') as stream:
    existing=[row for row in csv.reader(stream) if len(row)<3 or not (row[2].startswith('HS ') or row[2]=='Stock Entry')]
rows=[]
for dt,spec in SCHEMA.items():
    values={v for df in spec['fields'] if df['fieldtype']=='Select' for v in df.get('options','').splitlines() if v}
    for code in sorted(values):
        assert code in OPTION_LABELS,(dt,code)
        rows.append([code,OPTION_CONTEXT.get(dt,{}).get(code,OPTION_LABELS[code]),dt])
for code in ('Sale','Cleaning','Waste','Linen Replacement','Maintenance','Transfer','Adjustment','Laundry'):
    rows.append([code,OPTION_LABELS[code],'Stock Entry'])
with target.open('w',encoding='utf-8',newline='') as stream:csv.writer(stream,lineterminator='\n').writerows(existing+rows)
print('Native contextual option translations:',len(rows))
