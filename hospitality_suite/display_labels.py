"""User terminology for current records and immutable historical snapshots."""
import frappe
from hospitality_suite.mode import LEGACY_TIME_MODE

MODE_LABELS={'Hotel':'Hotel','Por tiempo':'Por tiempo',LEGACY_TIME_MODE:'Por tiempo','Mixed':'Hotel y por tiempo','Day Pass':'Day Pass'}
GENERATED_LABELS={'Horas adicionales de motel':'Horas adicionales por tiempo',
                  'Hora adicional de motel':'Hora adicional por tiempo'}


def generated_label(value):
    return frappe._(GENERATED_LABELS[value]) if value in GENERATED_LABELS else value


def cleaning_label(value):
    """Cleaning is a room state here, distinct from an inventory purpose."""
    labels={'Clean':frappe._('Limpia'),'Dirty':frappe._('Sucia'),
            'Cleaning':frappe._('En limpieza'),'Inspection':frappe._('Pendiente de inspección')}
    return labels.get(value,frappe._(value or '—'))
