"""Read-only health check inside the WSL test site's own resolver context."""
import json
import time
import urllib.error
import urllib.request

for attempt in range(3):
    try:
        with urllib.request.urlopen('http://hospitality.localhost:8086/api/method/ping',timeout=2) as response:
            assert response.status==200 and json.load(response).get('message')=='pong'
        print('Sitio de pruebas verificado: HTTP 200 y respuesta pong')
        break
    except (OSError,urllib.error.URLError,AssertionError):
        if attempt==2:raise SystemExit('El sitio no respondió dentro de WSL; revise los registros del bench.') from None
        time.sleep(.5)
