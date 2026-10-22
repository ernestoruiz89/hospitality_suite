"""Room-scoped operational history: intervals, immutable events and native versions.

Native Version can store Link titles and formatted dates. Those values are never
treated as raw identities or silently parsed as ISO timestamps. New operational
snapshots retain raw room references; older ambiguous relationships are explicit.
"""
from copy import deepcopy
from datetime import datetime

import frappe
from frappe.utils import get_datetime

from hospitality_suite.desk_board import authorize
from hospitality_suite.paging import page, permitted_all
from hospitality_suite.security import property_document
from hospitality_suite.time import local, to_site


TYPES=('HS Room','HS Booking','HS Stay','HS Cleaning Task','HS Maintenance Order','HS Room Block')
FIELDS={
    'HS Room':('room_number','category','floor','zone','beds','parking','active','cleaning_status'),
    'HS Booking':('status','starts_at','ends_at','channel','instructions','reason','rooms'),
    'HS Stay':('room','status','starts_at','ends_at','actual_check_in','actual_check_out','reason'),
    'HS Cleaning Task':('room','kind','priority','status','assigned_to','started_at','completed_at','notes'),
    'HS Maintenance Order':('room','title','equipment','starts_at','ends_at','until_reopened','blocks_room','kind','status','assigned_to','notes'),
    'HS Room Block':('room','reason','starts_at','ends_at','status','note','created_by','released_by','released_on','release_note'),
}
def type_labels():
    return {'HS Room':frappe._('Habitación'),'HS Booking':frappe._('Reserva'),'HS Stay':frappe._('Estancia'),
            'HS Cleaning Task':frappe._('Limpieza'),'HS Maintenance Order':frappe._('Mantenimiento'),
            'HS Room Block':frappe._('Bloqueo operativo')}


def creation_labels():
    return {'HS Room':frappe._('Habitación registrada'),'HS Booking':frappe._('Reserva registrada'),'HS Stay':frappe._('Entrada registrada'),
            'HS Cleaning Task':frappe._('Tarea de limpieza programada'),'HS Maintenance Order':frappe._('Orden de mantenimiento registrada'),
            'HS Room Block':frappe._('Bloqueo de habitación registrado')}


def object_value(value):
    try:result=frappe.parse_json(value or '{}')
    except (ValueError,TypeError):return {}
    return result if isinstance(result,dict) else {}


def version_value(value):
    data=object_value(value);result={}
    array=lambda value:value if isinstance(value,(list,tuple)) else []
    result['changed']=[row for row in array(data.get('changed')) if isinstance(row,(list,tuple)) and len(row)==3 and isinstance(row[0],str)]
    for key in ('added','removed'):
        result[key]=[row for row in array(data.get(key)) if isinstance(row,(list,tuple)) and len(row)==2 and isinstance(row[0],str) and isinstance(row[1],dict)]
    result['row_changed']=[]
    for row in array(data.get('row_changed')):
        if isinstance(row,(list,tuple)) and len(row)==4 and isinstance(row[0],str) and isinstance(row[2],str) and isinstance(row[3],list):
            changes=[entry for entry in row[3] if isinstance(entry,(list,tuple)) and len(entry)==3 and isinstance(entry[0],str)]
            result['row_changed'].append([*row[:3],changes])
    return result


def complete(doctype,filters,fields,order_by='creation desc,name desc'):
    """Narrow privileged projections after room/operator authorization, without a cap.

    Reception is not granted general access to Version or HS Audit Event. Only
    authorized-property operational source documents and allowlisted values leave
    this API; financial/identity/attachment payloads are never returned.
    """
    result=[];offset=0
    while True:
        batch=frappe.get_all(doctype,filters=filters,fields=fields,order_by=order_by,limit=500,start=offset)
        result.extend(batch)
        if len(batch)<500:return result
        offset+=len(batch)


def undo(state,rooms,data,resolve):
    state=deepcopy(state);rooms=dict(rooms)
    for entry in data.get('changed') or []:
        if isinstance(entry,(list,tuple)) and len(entry)==3:
            key,old,_=entry
            if key=='room':state[key]=resolve(old)
            elif key in state:state[key]=old
    for table,key in (('added',False),('removed',True)):
        for entry in data.get(table) or []:
            if not isinstance(entry,(list,tuple)) or len(entry)!=2 or entry[0]!='rooms' or not isinstance(entry[1],dict):continue
            row=entry[1];name=row.get('name')
            if isinstance(name,str) and name:
                if key:rooms[name]=row.get('room') if isinstance(row.get('room'),str) else None
                else:rooms.pop(name,None)
    for entry in data.get('row_changed') or []:
        if not isinstance(entry,(list,tuple)) or len(entry)!=4 or entry[0]!='rooms':continue
        for change in entry[3]:
            if len(change)==3 and change[0]=='room':rooms[entry[2]]=resolve(change[1])
    return state,rooms


class History:
    def __init__(self,prop,room,start,end):
        self.prop,self.room,self.start,self.end=prop,room,start,end
        self.records=[];self.actors={};self.sources={};self.aliases={}
        self.room_labels={r.name:r.room_number for r in permitted_all('HS Room',filters={'property':prop.name,'company':prop.company},fields=['name','room_number'])}
        for name,label in self.room_labels.items():self.aliases.setdefault(label,set()).add(name)
        self.categories={r.name:r.category_name for r in permitted_all('HS Category',filters={'property':prop.name,'company':prop.company},fields=['name','category_name'])}
        self.allocations=permitted_all('HS Allocation',filters={'property':prop.name,'company':prop.company,'room':room.name},fields=['name','room','booking','stay','maintenance','room_block','starts_at','ends_at','kind','status'])
        self.related={dt:{row.get(key) for row in self.allocations if row.get(key)} for dt,key in (('HS Booking','booking'),('HS Stay','stay'),('HS Maintenance Order','maintenance'),('HS Room Block','room_block'))}
        self.events=complete('HS Audit Event',{'property':prop.name,'company':prop.company,'source_doctype':['in',list(TYPES)]},
                             ['name','action','actor','occurred_at','source_doctype','source_name','reason','details'],'occurred_at desc,name desc')
        self.boundaries={}
        for event in self.events:
            data=object_value(event.details)
            if data.get('_scope_boundary'):
                self.boundaries.setdefault((event.source_doctype,event.source_name),get_datetime(event.occurred_at))

    def stamp(self,value):return local(value,self.prop).isoformat() if value else None
    def inside(self,value):return bool(value and self.start<=get_datetime(value)<self.end)
    def actor(self,user):
        if not isinstance(user,str):return frappe._('Usuario registrado')
        if user not in self.actors:self.actors[user]=frappe.db.get_value('User',user,'full_name') or user
        return self.actors[user]
    def resolve(self,value,*,formatted=False):
        if not isinstance(value,str) or not value:return None
        if value in self.room_labels and not formatted:return value
        choices=set(self.aliases.get(value,set()))
        if value in self.room_labels:choices.add(value)
        return next(iter(choices)) if len(choices)==1 else None
    def membership(self,dt,state,rooms):
        if dt=='HS Room':return {state['name']}
        if dt=='HS Booking':return {value for value in rooms.values() if value}
        return {state.get('room')} if state.get('room') else set()

    def load_sources(self):
        for dt in TYPES:
            meta=frappe.get_meta(dt)
            fields=['name','company','property','creation','owner',*[key for key in FIELDS[dt] if key!='rooms' and meta.has_field(key)]]
            filters={'property':self.prop.name,'company':self.prop.company}
            if dt=='HS Room':filters['name']=self.room.name
            parents=permitted_all(dt,filters=filters,fields=fields)
            # Room aliases include former numbers; ambiguous titles are never IDs.
            if dt=='HS Room':
                versions=complete('Version',{'ref_doctype':dt,'docname':['in',list(self.room_labels)]},['name','docname','creation','owner','data']) if self.room_labels else []
                crossed=set()
                for version in versions:
                    boundary_at=self.boundaries.get((dt,version.docname))
                    if boundary_at and get_datetime(version.creation)<boundary_at:continue
                    changes=version_value(version.data)['changed']
                    if any(row[0] in ('property','company') for row in changes):crossed.add(version.docname);continue
                    if version.docname in crossed:continue
                    for change in changes:
                        if len(change)==3 and change[0]=='room_number':
                            for value in change[1:]:
                                if value:self.aliases.setdefault(str(value),set()).add(version.docname)
            else:versions=complete('Version',{'ref_doctype':dt,'docname':['in',[row.name for row in parents]]},['name','docname','creation','owner','data']) if parents else []
            children={}
            if dt=='HS Booking' and parents:
                for child in complete('HS Booking Room',{'parenttype':dt,'parentfield':'rooms','parent':['in',[r.name for r in parents]]},['name','parent','room']):children.setdefault(child.parent,{})[child.name]=child.room
            grouped={}
            for version in versions:grouped.setdefault(version.docname,[]).append(version)
            for parent in parents:
                state=dict(parent);rooms=children.get(parent.name,{});steps=[];scoped=True
                boundary_at=self.boundaries.get((dt,parent.name))
                for version in grouped.get(parent.name,[]):
                    if boundary_at and get_datetime(version.creation)<boundary_at:scoped=False
                    data=version_value(version.data);old,old_rooms=undo(state,rooms,data,lambda value:self.resolve(value,formatted=True))
                    boundary=any(change[0] in ('property','company') for change in data.get('changed') or [])
                    steps.append(dict(version=version,data=data,after=deepcopy(state),before=old,rooms_after=dict(rooms),rooms_before=old_rooms,scoped=scoped,boundary=boundary))
                    if boundary:scoped=False
                    state,rooms=old,old_rooms
                self.sources[(dt,parent.name)]=dict(parent=parent,steps=steps,initial=state,initial_rooms=rooms,initial_scoped=scoped and not boundary_at,current_rooms=children.get(parent.name,{}))

    def value(self,dt,key,value,*,formatted=False):
        from hospitality_suite.printing import hs_label
        if value is None or value=='':return frappe._('Sin dato')
        if key=='room':
            name=self.resolve(value,formatted=formatted);return self.room_labels.get(name,frappe._('Habitación anterior (referencia conservada)'))
        if key=='category':
            if not isinstance(value,str):return frappe._('Categoría anterior (referencia conservada)')
            return self.categories.get(value,str(value) if value in self.categories.values() else frappe._('Categoría anterior (referencia conservada)'))
        if key=='rooms':
            if not isinstance(value,list):return frappe._('Habitaciones registradas sin desglose recuperable')
            return '; '.join((row.get('room_number') if isinstance(row.get('room_number'),str) and row['room_number'] else self.room_labels[row['room']]) if isinstance(row.get('room'),str) and row['room'] in self.room_labels else frappe._('Habitación anterior (referencia conservada)') if row.get('room') else frappe._('Por asignar') for row in value if isinstance(row,dict)) or frappe._('Sin habitaciones asignadas')
        if isinstance(value,(dict,list,tuple)):return frappe._('Valor conservado sin formato recuperable')
        if key=='equipment':
            return frappe.db.get_value('HS Equipment',{'name':value,'property':self.prop.name,'company':self.prop.company},'label') or frappe._('Equipo registrado')
        if key=='assigned_to':return str(value) if formatted and isinstance(value,str) else self.actor(value)
        if key in ('active','blocks_room','until_reopened'):return frappe._('No') if str(value).lower() in ('0','false','no','') else frappe._('Sí')
        if key in ('starts_at','ends_at','started_at','completed_at','actual_check_in','actual_check_out') and not formatted:
            try:return local(value,self.prop).strftime('%d/%m/%Y %H:%M:%S')
            except (ValueError,TypeError):return frappe._('Fecha registrada sin formato reconocido')
        if key=='cleaning_status':
            from hospitality_suite.display_labels import cleaning_label
            return cleaning_label(value)
        if key in ('status','kind','priority') or dt=='HS Room Block' and key=='reason':return hs_label(value)
        return str(value)

    def fields(self,dt,before,after,*,formatted=False):
        from hospitality_suite.audit_trail import LABELS
        meta=frappe.get_meta(dt);rows=[]
        for key in FIELDS[dt]:
            if key not in before and key not in after or before.get(key)==after.get(key):continue
            df=meta.get_field(key)
            label=frappe._(LABELS.get(key) or (df.label if df else key))
            if dt=='HS Maintenance Order':
                label={'title':frappe._('Trabajo registrado'),'starts_at':frappe._('Inicio del bloqueo'),'ends_at':frappe._('Fin previsto del bloqueo')}.get(key,label)
            rows.append(dict(label=label,before=self.value(dt,key,before.get(key),formatted=formatted),after=self.value(dt,key,after.get(key),formatted=formatted)))
        return rows

    def add(self,*,identity,kind,title,at=None,starts_at=None,ends_at=None,actor=None,details=None,note='',relation='exact'):
        self.records.append(dict(id=identity,kind=kind,title=title,occurred_at=self.stamp(at),starts_at=self.stamp(starts_at),ends_at=self.stamp(ends_at),
                                 actor=self.actor(actor) if actor else '',fields=details or [],note=note,relation=relation,_sort=get_datetime(at or starts_at)))

    def changes(self):
        for (dt,name),source in self.sources.items():
            if source['initial_scoped'] and self.room.name in self.membership(dt,source['initial'],source['initial_rooms']) and self.inside(source['parent'].creation):
                self.add(identity='created:'+dt+':'+name,kind='change',title=creation_labels()[dt],at=source['parent'].creation,actor=source['parent'].owner)
            for step in source['steps']:
                version,data=step['version'],step['data']
                if not step['scoped'] or not self.inside(version.creation):continue
                members=self.membership(dt,step['after'],step['rooms_after'])|self.membership(dt,step['before'],step['rooms_before'])
                related=name in self.related.get(dt,set()) and (not members or not any(data.values()))
                if self.room.name not in members and not related:continue
                if step['boundary']:
                    self.add(identity='version:'+version.name,kind='change',title=frappe._('Ficha incorporada al establecimiento'),at=version.creation,actor=version.owner);continue
                before={};after={}
                for change in data.get('changed') or []:
                    if len(change)==3 and change[0] in FIELDS[dt]:before[change[0]],after[change[0]]=change[1:]
                if dt=='HS Booking' and any((data.get(key) for key in ('added','removed','row_changed'))):
                    before['rooms']=[dict(room=value) for value in step['rooms_before'].values()];after['rooms']=[dict(room=value) for value in step['rooms_after'].values()]
                self.add(identity='version:'+version.name,kind='change',title=frappe._('Cambios de datos · {0}').format(type_labels()[dt]),at=version.creation,actor=version.owner,
                         details=self.fields(dt,before,after,formatted=True),relation='related' if related else 'exact',
                         note=frappe._('Documento relacionado: esta versión no permite reconstruir con certeza la habitación de ese momento.') if related else frappe._('Las fechas y los nombres antiguos de esta versión se muestran tal como quedaron registrados.'))

    def operations(self):
        from hospitality_suite.report_presentation import action_label
        for event in self.events:
            if not self.inside(event.occurred_at):continue
            dt=event.source_doctype;source=self.sources.get((dt,event.source_name))
            if not source:continue
            data=object_value(event.details);stored=data.get('_values');stored=stored if isinstance(stored,dict) else {};before=stored.get('before') or {};after=stored.get('after') or {}
            if not isinstance(before,dict) or not isinstance(after,dict):before,after={},{}
            if stored.get('version')!=1 or stored.get('doctype')!=dt or stored.get('name')!=event.source_name:before,after={},{}
            if after.get('property') and (after.get('property'),after.get('company'))!=(self.prop.name,self.prop.company):before,after={},{}
            known=dt=='HS Room' or 'room' in before or 'room' in after or 'rooms' in before or 'rooms' in after
            if dt=='HS Room':members={event.source_name}
            elif dt=='HS Booking':members={r.get('room') for state in (before,after) for r in (state.get('rooms') if isinstance(state.get('rooms'),list) else []) if isinstance(r,dict) and isinstance(r.get('room'),str)}
            else:members={value for value in (before.get('room'),after.get('room')) if isinstance(value,str) and value}
            if event.action=='Change room':members.update(value for value in (data.get('from'),data.get('to')) if isinstance(value,str) and value);known=True
            if not known:
                state=dict(source['parent']);rooms=source['current_rooms']
                for step in source['steps']:
                    if get_datetime(step['version'].creation)>get_datetime(event.occurred_at):state,rooms=step['before'],step['rooms_before']
                members=self.membership(dt,state,rooms)
                if event.action=='Modify reservation':
                    previous=next((step for step in source['steps'] if get_datetime(step['version'].creation)<=get_datetime(event.occurred_at)),None)
                    if previous:members|=self.membership(dt,previous['before'],previous['rooms_before'])
            related=not members and event.source_name in self.related.get(dt,set())
            if self.room.name not in members and not related:continue
            # Before values from another property are never exposed after a move.
            if before.get('property') and (before.get('property'),before.get('company'))!=(self.prop.name,self.prop.company):before={}
            title=frappe._('Datos de habitación actualizados') if event.action=='Room changed' else action_label(event.action)
            if data.get('_scope_boundary'):title=frappe._('Ficha incorporada al establecimiento');before={}
            self.add(identity='event:'+event.name,kind='operation',title=title,at=event.occurred_at,actor=event.actor,details=self.fields(dt,before,after),note=event.reason or '',relation='related' if related else 'exact')

    def periods(self):
        from hospitality_suite.housekeeping import maintenance_finished_at
        labels={'Reservation':(frappe._('Reserva registrada'),frappe._('Reserva liberada')),
                'Stay':(frappe._('Estancia registrada'),frappe._('Asignación de estancia liberada')),
                'Maintenance':(frappe._('Bloqueo de mantenimiento'),frappe._('Bloqueo finalizado')),
                'Room Block':(frappe._('Bloqueo operativo'),frappe._('Bloqueo liberado'))}
        latest={}
        stay_names=list(self.sources[key]['parent'].name for key in self.sources if key[0]=='HS Stay')
        if stay_names:
            for segment in permitted_all('HS Allocation',filters={'property':self.prop.name,'company':self.prop.company,'kind':'Stay','stay':['in',stay_names]},
                                         fields=['name','stay'],order_by='starts_at desc,creation desc,name desc'):
                latest.setdefault(segment.stay,segment.name)
        for row in self.allocations:
            start=get_datetime(row.starts_at);end=get_datetime(row.ends_at) if row.ends_at else None;note=''
            if row.kind=='Stay' and row.stay and ('HS Stay',row.stay) in self.sources:
                stay=self.sources[('HS Stay',row.stay)]['parent']
                if stay.actual_check_in:start=max(start,get_datetime(stay.actual_check_in))
                if latest.get(stay.name)==row.name:
                    if stay.actual_check_out:end=get_datetime(stay.actual_check_out)
                    elif stay.status=='Active':
                        end=None;note=frappe._('La estancia no tiene salida registrada. Su salida prevista es {0}.').format(self.value('HS Stay','ends_at',stay.ends_at))
                elif stay.actual_check_out:end=min(end,get_datetime(stay.actual_check_out)) if end else get_datetime(stay.actual_check_out)
            if row.kind=='Maintenance' and row.status=='Released' and row.maintenance:
                source=self.sources.get(('HS Maintenance Order',row.maintenance))
                order=frappe.get_doc('HS Maintenance Order',row.maintenance) if source else None
                if order and order.status=='Completed':
                    finished=maintenance_finished_at(order);end=min(end,finished) if end else finished
            if row.kind=='Room Block' and row.status=='Released' and row.room_block:
                source=self.sources.get(('HS Room Block',row.room_block))
                block=source['parent'] if source else None
                if block and block.status=='Released' and block.released_on:
                    end=min(end,get_datetime(block.released_on)) if end else get_datetime(block.released_on)
            if end and end<=start:continue
            if start>=self.end or end and end<=self.start:continue
            titles=labels.get(row.kind)
            if not titles:continue
            if row.kind=='Reservation':note=frappe._('Fechas reservadas. Una asignación liberada no representa ocupación actual.')
            self.add(identity='allocation:'+row.name,kind='period',title=titles[row.status=='Released'],starts_at=start,ends_at=end,note=note)


def history(property_name,room,starts_at,ends_at,view='activity',offset=0,page_length=25):
    prop=authorize(property_name)
    if not isinstance(room,str) or not room.strip() or len(room)>140:frappe.throw(frappe._('Seleccione una habitación válida'))
    doc=property_document(prop,'HS Room',room)
    if view not in ('activity','all','operations','changes','periods'):frappe.throw(frappe._('Seleccione una vista de historial válida'))
    if any(not isinstance(value,(str,datetime)) or not str(value).strip() or len(str(value))>128 for value in (starts_at,ends_at)):
        frappe.throw(frappe._('Indique fechas y horas válidas para el historial'))
    try:start,end=to_site(starts_at,prop),to_site(ends_at,prop)
    except (ValueError,TypeError,OverflowError):frappe.throw(frappe._('Indique fechas y horas válidas para el historial'))
    if end<=start:frappe.throw(frappe._('La fecha final debe ser posterior a la inicial'))
    # Validate pagination before any potentially long historical projection.
    page([],offset,page_length)
    timeline=History(prop,doc,start,end);timeline.load_sources();timeline.periods();timeline.operations();timeline.changes()
    selected={'activity':{'operation','period'},'all':{'operation','period','change'},'operations':{'operation'},'changes':{'change'},'periods':{'period'}}[view]
    counts={kind:sum(row['kind']==kind for row in timeline.records) for kind in ('operation','period','change')}
    rows=sorted((row for row in timeline.records if row['kind'] in selected),key=lambda row:(row['_sort'],row['id']),reverse=True)
    for row in rows:row.pop('_sort')
    result=page(rows,offset,page_length)
    return {**result,'property':prop.name,'room':doc.name,'room_label':doc.room_number,'time_zone':prop.time_zone,'starts_at':timeline.stamp(start),'ends_at':timeline.stamp(end),'view':view,'counts':counts}
