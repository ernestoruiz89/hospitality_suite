"""Read-only PDF checks; visual QA remains required after this structural check."""
import argparse
import json
from pathlib import Path

from pypdf import PdfReader

parser=argparse.ArgumentParser()
parser.add_argument("directory")
parser.add_argument("--expected-files",type=int,default=10)
args=parser.parse_args()
result=[]
paths=sorted(Path(args.directory).glob("*.pdf"))
if len(paths)!=args.expected_files:
    raise SystemExit(f"Se esperaban {args.expected_files} PDF reales de la app")
for path in paths:
    reader=PdfReader(path)
    pages=[page.extract_text() or "" for page in reader.pages]
    if not pages or any(len(text.strip())<80 for text in pages):
        raise SystemExit("Página vacía o ilegible: "+str(path))
    if path.stem=="invoice" and ("Cargos que componen" in " ".join(pages) or "hs_charge_sources" in " ".join(pages)):
        raise SystemExit("La factura expone referencias internas")
    result.append(dict(file=path.name,pages=len(pages),characters=sum(len(p) for p in pages)))
print(json.dumps(result,ensure_ascii=False,indent=2))
