"""Translate display text when a site is active; keep pure kernels independent."""
import sys


def text(message,values=None):
    framework=sys.modules.get("frappe")
    translated=framework._(message) if framework and getattr(framework.local,"site",None) else message
    return translated.format(*values) if values is not None else translated
