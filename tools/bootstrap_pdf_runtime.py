"""Extract official patched-Qt wkhtmltopdf only inside this development bench.

No apt install, post-install scripts, system binary or other bench is changed.
The official Jammy amd64 package is validated at runtime on this WSL Ubuntu.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

bench=Path('/home/frappe/benches/hospitality-bench')
assert os.name=='posix' and bench.is_dir()
assert json.loads((bench/'sites/hospitality.localhost/site_config.json').read_text())['db_name']=='hospitality_dev'
base=bench/'.runtime'
base.mkdir(exist_ok=True)
target=base/'wkhtmltox'
assert target.resolve().is_relative_to(base.resolve())
downloads=base/'downloads'
downloads.mkdir(exist_ok=True)
name='wkhtmltox_0.12.6.1-3.jammy_amd64.deb'
url='https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/'+name
package=downloads/name
if not package.exists():
    with urllib.request.urlopen(url,timeout=60) as response:
        payload=response.read(17326783)
    assert len(payload)==17326782 and payload.startswith(b'!<arch>\n'),'Unexpected upstream package'
    package.write_bytes(payload)
    package.chmod(0o600)
digest=hashlib.sha256(package.read_bytes()).hexdigest()
assert digest=='4f723b2691ad8638a9df960e0421d346d7315083e3583a334f33362280ddba15','Pinned official package hash differs'
manifest=base/'pdf-runtime.json'
if manifest.exists():
    assert json.loads(manifest.read_text())['package_sha256']==digest,'Package changed since previous extraction'
subprocess.run(['dpkg-deb','-x',str(package),str(target)],check=True)
binary=target/'usr/local/bin/wkhtmltopdf'
libraries=subprocess.check_output(['ldd',str(binary)],text=True)
assert 'not found' not in libraries,'A runtime library is missing'
version=subprocess.check_output([str(binary),'--version'],text=True).strip()
assert '0.12.6.1' in version and 'with patched qt' in version.lower()
os.environ['PATH']=str(binary.parent)+os.pathsep+os.environ.get('PATH','')
import frappe
os.chdir(bench/'sites')
for site in ('hospitality.localhost','hospitality-clean.localhost','hospitality-restore.localhost'):
    site_config=bench/'sites'/site/'site_config.json'
    if not site_config.exists():
        continue
    settings=json.loads(site_config.read_text())
    assert settings.get('allow_tests') and settings['db_name'].startswith('hospitality_')
    frappe.init(site=site,sites_path=str(bench/'sites'))
    try:
        from frappe.utils.pdf import is_wkhtmltopdf_valid
        is_wkhtmltopdf_valid.clear_cache()
        assert is_wkhtmltopdf_valid()
        frappe.cache.delete_value('wkhtmltopdf_version')
    finally:
        frappe.destroy()
result=dict(version=version,source=url,package_sha256=digest,bytes=package.stat().st_size,
            isolated=True,system_binary_unchanged=True,binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
manifest.write_text(json.dumps(result,indent=2)+'\n')
(Path('/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel/docs/evidence/pdf-runtime.json')).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
