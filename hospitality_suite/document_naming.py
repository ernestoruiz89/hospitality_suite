"""Native Frappe series for new operator-facing documents only.

Metadata controls new inserts; existing names and every Link remain untouched.
Annual counters use the site's calendar year, independently of business_date.
Technical records and child rows retain random internal identifiers.
"""
DOCUMENT_SERIES = {
    'HS Property': 'ESTAB-.#####',
    'HS Category': 'CAT-.#####',
    'HS Room': 'HAB-.#####',
    'HS Rate': 'TAR-.#####',
    'HS Guest': 'HUE-.#####',
    'HS Booking': 'RES-.YYYY.-.#####',
    'HS Stay': 'EST-.YYYY.-.#####',
    'HS Folio': 'CTA-.YYYY.-.#####',
    'HS Charge': 'CAR-.YYYY.-.#####',
    'HS Payment Method': 'MED-.#####',
    'HS Expense Category': 'CATGTO-.#####',
    'HS Supplier': 'PROV-.#####',
    'HS Stock Policy': 'POLSTK-.#####',
    'HS Shift': 'TUR-.YYYY.-.#####',
    'HS Payment': 'PAG-.YYYY.-.#####',
    'HS Cleaning Task': 'LIM-.YYYY.-.#####',
    'HS Equipment': 'EQP-.#####',
    'HS Maintenance Order': 'MAN-.YYYY.-.#####',
    'HS Room Block': 'BLO-.YYYY.-.#####',
    'HS Service Request': 'SER-.YYYY.-.#####',
    'HS Laundry Rate': 'LAVTAR-.#####',
    'HS Laundry Order': 'LAV-.YYYY.-.#####',
    'HS Incident': 'INC-.YYYY.-.#####',
    'HS Daily Close': 'CIE-.YYYY.-.#####',
    'HS Portal Request': 'SOL-.YYYY.-.#####',
    'HS Billing Party': 'PAGADOR-.#####',
    'HS Travel Agent': 'AGV-.#####',
    'HS Experience': 'EXP-.#####',
    'HS Experience Order': 'EXPO-.YYYY.-.#####',
    'HS Retention Run': 'RET-.YYYY.-.#####',
}
