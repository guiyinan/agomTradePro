import hashlib,json,os,subprocess,sys,time
from pathlib import Path
d=Path('.tmp/ash03-sdk-red-228');d.mkdir()
p=Path('sdk/tests/test_mcp/test_confirmation_commit_argument_bindings.py')
c=[sys.executable,'-X','utf8','-m','pytest',p.as_posix()+'::test_complete_large_source_freezes_only_resolved_ids',p.as_posix()+'::test_real_owner_manifest_freezes_default_scope_against_later_account','-q','-p','tests.support.fast_suite_guard','--basetemp=.tmp/pytest-ash03-sdk-red-228','--junitxml='+str(d/'red.xml')]
(d/'test-before.py.source').write_bytes(p.read_bytes());before=hashlib.sha256(p.read_bytes()).hexdigest();t=time.monotonic()
with (d/'red.log').open('xb') as out:r=subprocess.run(c,env=dict(os.environ,PYTHONUTF8='1',PYTEST_ADDOPTS='',DJANGO_SETTINGS_MODULE='core.settings.development_sqlite'),stdout=out,stderr=subprocess.STDOUT)
assert hashlib.sha256(p.read_bytes()).hexdigest()==before
record={'command':c,'exit_code':r.returncode,'seconds':round(time.monotonic()-t,3),'base':'96354c9ceba0ca46d49f667554a3498ffb286d20','preimage_sha256':before,'log_sha256':hashlib.sha256((d/'red.log').read_bytes()).hexdigest()}
(d/'red.result.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record));raise SystemExit(r.returncode)
