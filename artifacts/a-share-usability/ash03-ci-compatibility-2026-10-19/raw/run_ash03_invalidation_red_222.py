import hashlib,json,os,subprocess,sys,time
from pathlib import Path
d=Path('.tmp/ash03-invalidation-red-222');d.mkdir()
p=Path('tests/unit/test_position_invalidation_tasks.py');before=hashlib.sha256(p.read_bytes()).hexdigest()
c=[sys.executable,'-X','utf8','-m','pytest',p.as_posix(),'-q','-p','tests.support.fast_suite_guard','--basetemp=.tmp/pytest-ash03-222','--junitxml=.tmp/ash03-invalidation-red-222/red.xml']
(d/'command.json').write_text(json.dumps(c)+'\n');(d/'test-before.py.source').write_bytes(p.read_bytes());t=time.monotonic()
with (d/'red.log').open('xb') as out:r=subprocess.run(c,env=dict(os.environ,PYTHONUTF8='1',PYTEST_ADDOPTS='',DJANGO_SETTINGS_MODULE='core.settings.development_sqlite'),stdout=out,stderr=subprocess.STDOUT)
assert hashlib.sha256(p.read_bytes()).hexdigest()==before
record={'command':c,'exit_code':r.returncode,'seconds':round(time.monotonic()-t,3),'base':'96354c9ceba0ca46d49f667554a3498ffb286d20','test_preimage_sha256':before,'log_sha256':hashlib.sha256((d/'red.log').read_bytes()).hexdigest(),'scope':'Original three no-side-effect tests with hard no-database guard'}
(d/'red.result.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record));raise SystemExit(r.returncode)
