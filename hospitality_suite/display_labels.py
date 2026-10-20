"""User terminology without changing persisted values or historical source text."""
import frappe

MODE_LABELS={'Hotel':'Hotel','Motel':'Por tiempo','Mixed':'Hotel y por tiempo'}
GENERATED_LABELS={'Horas adicionales de motel':'Horas adicionales por tiempo',
                  'Hora adicional de motel':'Hora adicional por tiempo'}


def generated_label(value):
    return frappe._(GENERATED_LABELS[value]) if value in GENERATED_LABELS else value
