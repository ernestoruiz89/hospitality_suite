"""Resolve only this bench's two named development sites inside WSL."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import socket

HOSTS = Path('/etc/hosts')
SITES = ('hospitality.localhost', 'hospitality-acceptance.localhost')


def missing_aliases(text):
    found = set()
    for line in text.splitlines():
        parts = line.partition('#')[0].split()
        aliases = set(word.casefold() for word in parts[1:]).intersection(SITES)
        if not aliases:
            continue
        address = ipaddress.ip_address(parts[0])
        if str(address) not in ('127.0.0.1', '::1'):
            raise ValueError('Existe otra dirección para un sitio de pruebas; revísela antes de cambiar hosts')
        if str(address) == '127.0.0.1':
            found.update(aliases)
    return [site for site in SITES if site not in found]


def check_local_hosts():
    missing = missing_aliases(HOSTS.read_text())
    if missing:
        raise ValueError('Faltan alias locales en WSL: '+', '.join(missing)+'. Ejecute tools/configure_local_hosts.py como root de WSL y repita el arranque.')
    for site in SITES:
        addresses = {row[4][0] for row in socket.getaddrinfo(site, None, socket.AF_INET)}
        if addresses != {'127.0.0.1'}:
            raise ValueError('La resolución de un sitio de pruebas no coincide con 127.0.0.1')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if os.name != 'posix' or not Path('/proc/sys/kernel/osrelease').is_file() or 'microsoft' not in Path('/proc/sys/kernel/osrelease').read_text().casefold():
        raise SystemExit('Este helper solo configura el entorno WSL de desarrollo')
    changed = False
    if not args.check:
        if os.geteuid() != 0:
            raise SystemExit('Ejecute como root de WSL; --check permite verificar sin modificar')
        import fcntl
        with HOSTS.open('r+', newline='') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            original = stream.read()
            missing = missing_aliases(original)
            if missing:
                stream.seek(0, 2)
                stream.write(('\n' if original and not original.endswith('\n') else '')+
                             '127.0.0.1\t'+' '.join(missing)+'\t# Hospitality Suite development sites\n')
                stream.flush()
                os.fsync(stream.fileno())
                changed = True
    check_local_hosts()
    print(json.dumps(dict(sites=list(SITES), address='127.0.0.1', changed=changed, check_only=args.check)))


if __name__ == '__main__':
    main()
