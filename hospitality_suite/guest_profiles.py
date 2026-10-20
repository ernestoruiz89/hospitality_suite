"""Scoped guest corrections with optimistic versions and delegated native CRM.

Guest identity and payer never change. Only exclusively owned Contact/Address
records are updated in place; shared/legacy records are preserved on correction.
"""
import frappe

from hospitality_suite.security import document, require
from hospitality_suite.service import assert_version, audit, current_all, insert

FIELDS=('full_name','email','phone','identity_type','identity_number','nationality')
ADDRESS=('address_line1','city','country')


def values(data, prop, creating=False):
    allowed=set(FIELDS+ADDRESS)|({'customer'} if creating else set())
    if set(data)-allowed:
        frappe.throw(frappe._('La solicitud contiene campos que no se pueden cambiar en la ficha del huésped'))
    if any(value is not None and not isinstance(value,str) for value in data.values()):
        frappe.throw(frappe._('Los datos del huésped deben ser texto'))
    result={field:(data.get(field) or '').strip() for field in FIELDS+ADDRESS}
    if not result['full_name']:
        frappe.throw(frappe._('Escriba el nombre del huésped'))
    if prop.guest_id_required and not result['identity_number']:
        frappe.throw(frappe._('Este establecimiento requiere el número de identificación del huésped'))
    if result['address_line1'] and not all(result[field] for field in ADDRESS):
        frappe.throw(frappe._('Para guardar la dirección indique ciudad y país'))
    if not result['address_line1']:
        result['city']=result['country']=''
    return result


def related(guest, dt, field):
    name=guest.get(field)
    if not name:
        return None
    record=frappe.get_doc(dt,name,for_update=bool(getattr(frappe.local,'hs_operation',False)))
    links={(row.link_doctype,row.link_name) for row in record.links}
    compatible=(('Customer',guest.customer) in links) if guest.customer else (('HS Guest',guest.name) in links and not any(dt in ('Customer','Supplier') for dt,_ in links))
    if not compatible:
        frappe.throw(frappe._('El contacto o la dirección vinculados no corresponden al pagador del huésped; revise la ficha con administración'),frappe.PermissionError)
    guest_links={name for doctype,name in links if doctype=='HS Guest'}
    if guest_links and guest.name not in guest_links:
        frappe.throw(frappe._('El contacto o la dirección pertenecen a otra ficha de huésped'),frappe.PermissionError)
    return record


def owned(guest, record, field):
    if not record:
        return False
    links={(row.link_doctype,row.link_name) for row in record.links}
    expected={('HS Guest',guest.name)}|({('Customer',guest.customer)} if guest.customer else set())
    others=current_all('HS Guest',filters={field:record.name,'name':['!=',guest.name]},fields=['name'])
    return links==expected and not others


def versions(contact, address):
    return {key:str(record.modified) if record else None for key,record in [('contact',contact),('address',address)]}


def result(guest, contact=None, address=None):
    return dict(guest=guest.name,customer=guest.customer,modified=str(guest.modified),related_versions=versions(contact,address))


def detail(name):
    guest=document('HS Guest',name,'guest')
    prop=require(guest.property,'guest')
    contact,address=related(guest,'Contact','contact'),related(guest,'Address','address')
    data={field:guest.get(field) or '' for field in FIELDS}
    data.update({field:address.get(field) or '' if address else '' for field in ADDRESS})
    return dict(**result(guest,contact,address),property=prop.name,values=data,
                customer_label=frappe.db.get_value('Customer',guest.customer,'customer_name') if guest.customer else frappe._('Sin cliente vinculado'),
                guest_id_required=bool(prop.guest_id_required),
                shared_contact=bool(contact and not owned(guest,contact,'contact')),
                shared_address=bool(address and not owned(guest,address,'address')))


def links(guest):
    return ([dict(link_doctype='Customer',link_name=guest.customer)] if guest.customer else [])+[dict(link_doctype='HS Guest',link_name=guest.name)]


def contact_values(record, data, previous=None):
    record.first_name=data['full_name'];record.middle_name='';record.last_name=''
    # Replace the profile's previous value, preserving other native addresses,
    # including one that Frappe promoted after the profile value was cleared.
    if previous is None or data['email']!=previous['email']:
        old=(previous or {}).get('email')
        record.set('email_ids',[row for row in record.email_ids if not old or row.email_id!=old])
        if data['email']:
            for row in record.email_ids:row.is_primary=0
            found=next((row for row in record.email_ids if row.email_id==data['email']),None)
            if found:found.is_primary=1
            else:record.append('email_ids',dict(email_id=data['email'],is_primary=1))
    if previous is None or data['phone']!=previous['phone']:
        old=(previous or {}).get('phone');phones=[]
        for row in record.phone_nos:
            if old and row.phone==old:
                if not row.is_primary_mobile_no:continue
                row.is_primary_phone=0
            phones.append(row)
        record.set('phone_nos',phones)
        if data['phone']:
            for row in record.phone_nos:row.is_primary_phone=0
            found=next((row for row in record.phone_nos if row.phone==data['phone']),None)
            if found:found.is_primary_phone=1
            else:record.append('phone_nos',dict(phone=data['phone'],is_primary_phone=1))


def create(prop, data):
    cleaned=values(data,prop,creating=True)
    customer=data.get('customer')
    if customer:
        if not (frappe.db.exists('HS Guest',{'property':prop.name,'customer':customer}) or
                frappe.db.exists('HS Billing Party',{'property':prop.name,'customer':customer})):
            frappe.throw(frappe._('El pagador debe estar registrado en este establecimiento'),frappe.PermissionError)
    else:
        group=frappe.db.get_single_value('Selling Settings','customer_group') or frappe.db.get_value('Customer Group',{'is_group':0},'name')
        territory=frappe.db.get_single_value('Selling Settings','territory') or frappe.db.get_value('Territory',{'is_group':0},'name')
        customer=frappe.get_doc(dict(doctype='Customer',customer_name=cleaned['full_name'],customer_type='Individual',
                                     customer_group=group,territory=territory)).insert(ignore_permissions=True).name
    guest=insert('HS Guest',prop,**{field:cleaned[field] for field in FIELDS},customer=customer)
    contact=address=None
    if cleaned['email'] or cleaned['phone']:
        contact=frappe.get_doc(dict(doctype='Contact',links=links(guest)))
        contact_values(contact,cleaned);contact.insert(ignore_permissions=True);guest.contact=contact.name
    if cleaned['address_line1']:
        address=frappe.get_doc(dict(doctype='Address',address_title=cleaned['full_name'],address_type='Personal',
                                    **{field:cleaned[field] for field in ADDRESS},links=links(guest))).insert(ignore_permissions=True)
        guest.address=address.name
    if contact or address:guest.save()
    audit(prop,'Register guest',guest)
    return result(guest,contact,address)


def update(prop, name, modified, data, reason, related_versions):
    guest=document('HS Guest',name,'guest')
    if guest.property!=prop.name:
        frappe.throw(frappe._('La ficha pertenece a otro establecimiento'),frappe.PermissionError)
    assert_version(guest,modified)
    if not isinstance(reason,str) or not reason.strip():
        frappe.throw(frappe._('Indique el motivo de la corrección del huésped'))
    contact,address=related(guest,'Contact','contact'),related(guest,'Address','address')
    previous={field:guest.get(field) or '' for field in FIELDS}
    previous.update({field:address.get(field) or '' if address else '' for field in ADDRESS})
    cleaned=values({**previous,**data},prop)
    changed=[field for field in FIELDS if (guest.get(field) or '')!=cleaned[field]]
    old_address={field:address.get(field) or '' if address else '' for field in ADDRESS}
    address_changed=any(old_address[field]!=cleaned[field] for field in ADDRESS)
    if address_changed:changed.extend(field for field in ADDRESS if old_address[field]!=cleaned[field])
    if any(field in changed for field in ('full_name','email','phone')) or (not contact and (cleaned['email'] or cleaned['phone'])):
        if contact:assert_version(contact,related_versions.get('contact'))
        if owned(guest,contact,'contact'):
            contact_values(contact,cleaned,previous);contact.save(ignore_permissions=True)
        elif cleaned['email'] or cleaned['phone']:
            contact=frappe.get_doc(dict(doctype='Contact',links=links(guest)))
            contact_values(contact,cleaned);contact.insert(ignore_permissions=True)
        else:contact=None
        guest.contact=contact.name if contact else None
    if address_changed or ('full_name' in changed and owned(guest,address,'address')):
        if address:assert_version(address,related_versions.get('address'))
        if not cleaned['address_line1']:
            address=None  # Unlink the profile; preserve historical native references.
        elif owned(guest,address,'address'):
            address.update({field:cleaned[field] for field in ADDRESS})
            address.address_title=cleaned['full_name'];address.save(ignore_permissions=True)
        else:
            address=frappe.get_doc(dict(doctype='Address',address_title=cleaned['full_name'],address_type='Personal',
                                        **{field:cleaned[field] for field in ADDRESS},links=links(guest))).insert(ignore_permissions=True)
        guest.address=address.name if address else None
    guest.update({field:cleaned[field] for field in FIELDS});guest.save()
    audit(prop,'Update guest',guest,reason=reason.strip(),details=dict(fields=changed))
    return result(guest,contact,address)
