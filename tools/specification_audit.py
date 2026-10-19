"""Render a reviewable requirement inventory without inferring completion."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'docs/specification-audit.json'
OUTPUT=ROOT/'docs/AUDITORIA_ESPECIFICACION.md'
CLAUSES=("Tu tarea es ","La aplicación debe permitir ","Valida la configuración ","Incluye filtros ","Roles mínimos:",
         "Usa datos ficticios reproducibles:","Aceptación funcional:","Si no puedes ejecutar pruebas ","En cada fase implementa ","Si el entorno impide terminar ")


def inventory(path):
    section=0
    title='Objetivo general'
    counts=Counter()
    items=[]
    for line,text in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
        heading=re.match(r'^(\d+)\. (.+)$',text)
        if heading:
            section,title=int(heading[1]),heading[2]
        enumerated=section<=18 and bool(re.match(r'^(?:- |\d+\) |[A-K]\. )',text))
        clause=text.startswith(CLAUSES)
        phase=bool(re.match(r'^Fase [1-7]:',text))
        if not (enumerated or clause or phase):
            continue
        counts[section]+=1
        items.append(dict(id=f'S{section:02}-{counts[section]:02}',section=section,title=title,line=line,
                          kind='enumerated' if enumerated else 'phase' if phase else 'clause',requirement=text,
                          status='R',implementation=[],evidence=[],remaining='Contraste individual con código y evidencia pendiente.'))
    return items


def reference(value):
    path,separator,anchor=value.partition('::')
    if not (ROOT/path).is_file():
        raise ValueError('Missing audit reference: '+path)
    suffix=' — '+anchor if separator else ''
    return f'[{path}]({path.removeprefix("docs/") if path.startswith("docs/") else "../"+path}){suffix}'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--initialize',type=Path)
    parser.add_argument('--verify-source',type=Path)
    args=parser.parse_args()
    if args.initialize:
        if DATA.exists():
            raise SystemExit('Audit already exists; update records without replacing review decisions')
        data=dict(source=args.initialize.name,sha256=hashlib.sha256(args.initialize.read_bytes()).hexdigest(),
                  items=inventory(args.initialize))
        DATA.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    data=json.loads(DATA.read_text(encoding='utf-8'))
    if args.verify_source:
        assert hashlib.sha256(args.verify_source.read_bytes()).hexdigest()==data['sha256'],'Source changed; reconcile the specification'
        expected=[(r['id'],r['line'],r['requirement']) for r in inventory(args.verify_source)]
        assert expected==[(r['id'],r['line'],r['requirement']) for r in data['items']],'Missing or changed requirement'
    items=data['items']
    assert len({r['id'] for r in items})==len(items)
    assert all(r['status'] in {'R','I','P','V'} for r in items)
    assert all(r['implementation'] and r['evidence'] and not r['remaining'] for r in items if r['status']=='V'),'Verified requirements need evidence and no remaining work'
    states=Counter(r['status'] for r in items)
    types=Counter(r['kind'] for r in items)
    lines=['# Auditoría punto por punto de la especificación','',
           f"Fuente: `{data['source']}`. SHA-256: `{data['sha256']}`.",'',
           f"Inventario: {types['enumerated']} elementos enumerados (incluidas las once Pages), {types['clause']} cláusulas expresas adicionales y {types['phase']} fases. Total: **{len(items)} entradas**.",'',
           'R = contraste individual pendiente; I = implementación localizada con verificación pendiente; P = diferencia material pendiente; V = evidencia individual revisada. La matriz resumida REQUISITOS.md conserva la evidencia anterior. R no afirma que la función falte; V exige probar todo el texto de la entrada. Ningún recuento ni generador acredita por sí mismo el alcance.','',
           'Estado: '+', '.join(f'{key}: {states[key]}' for key in ('V','I','P','R'))+'. Objetivo activo.','']
    previous=None
    for row in items:
        if row['section']!=previous:
            lines.extend([f"## {row['section']}. {row['title']}",'','| ID / línea original | Requisito | Estado | Implementación | Evidencia | Pendiente |','|---|---|---|---|---|---|'])
            previous=row['section']
        values=[f"{row['id']} / L{row['line']}",row['requirement'],row['status'],
                '<br>'.join(reference(r) for r in row['implementation']) or '—',
                '<br>'.join(reference(r) for r in row['evidence']) or '—',row['remaining'] or '—']
        lines.append('| '+' | '.join(str(v).replace('|','\\|').replace('\n',' ') for v in values)+' |')
        next_index=items.index(row)+1
        if next_index==len(items) or items[next_index]['section']!=row['section']:
            lines.append('')
    OUTPUT.write_text('\n'.join(lines).rstrip()+'\n',encoding='utf-8',newline='\n')
    print(f'Audit: {len(items)} items; '+', '.join(f'{key}={states[key]}' for key in ('V','I','P','R')))


if __name__=='__main__':
    main()
