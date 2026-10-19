"""Build a clean committed-source export plus the exact test-only CI correction."""
import hashlib,json,os,subprocess,tarfile,tempfile,time
from pathlib import Path
root=Path.cwd();d=root/'.tmp/ash03-clean-ci-candidate-225';d.mkdir()
base='96354c9ceba0ca46d49f667554a3498ffb286d20'
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==base
packet=root/'.tmp/ash03-invalidation-ci-candidate-221';m=json.loads((packet/'manifest.json').read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(packet/'manifest.json')=='27cd78b8f26be3fe022d2228ef36dc81e29c9c451fea3a379feb8a3446a8d478'
assert sha(root/m['source_path'])==m['preimage_sha256']
assert sha(root/m['candidate_path'])==m['candidate_sha256']
export=Path(tempfile.mkdtemp(prefix='ash03-ci-96354-')).resolve()
archive=d/'source.tar'
with archive.open('xb') as out:subprocess.run(['git','archive','--format=tar',base],stdout=out,check=True)
with tarfile.open(archive) as tar:tar.extractall(export,filter='data')
(export/m['source_path']).write_bytes((root/m['candidate_path']).read_bytes())
record={'base_head':base,'archive_sha256':sha(archive),'export_root':str(export),'overlay':[{'path':m['source_path'],'preimage_sha256':m['preimage_sha256'],'postimage_sha256':m['candidate_sha256']}],'scope':'Pure Git export plus one frozen test-only candidate; no foreign WIP, no new branch/worktree, no production source mutation.'}
(d/'export.json').write_text(json.dumps(record,indent=2)+'\n')
py=[str(root/'agomtradepro/Scripts/python.exe'),'-X','utf8'];env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTEST_ADDOPTS='',DJANGO_SETTINGS_MODULE='core.settings.development_sqlite')
for tag,c in [
 ('architecture_projection',py+['scripts/data_center_architecture_inventory.py','--write']),
 ('entrypoint_projection',py+['scripts/data_center_entrypoint_inventory.py','--write']),
 ('projection_check',py+['scripts/check_data_center_governance_projections.py']),
 ('test_black',py+['-m','black','--check',m['source_path']]),
 ('test_isort',py+['-m','isort','--check-only',m['source_path']]),
 ('test_ruff',py+['-m','ruff','check',m['source_path']]),
 ('fast_suite',py+['scripts/run_fast_tests.py','--','--basetemp='+str(export.parent/(export.name+'-pytest')),'--junitxml='+str(d/'fast.xml')]),
]:
 (d/(tag+'.command.json')).write_text(json.dumps(c)+'\n');t=time.monotonic()
 with (d/(tag+'.log')).open('xb') as out:r=subprocess.run(c,cwd=export,env=env,stdout=out,stderr=subprocess.STDOUT)
 result={'command':c,'cwd':str(export),'exit_code':r.returncode,'seconds':round(time.monotonic()-t,3),'log_sha256':sha(d/(tag+'.log')),'base_head':base,'overlay_test_sha256':sha(export/m['source_path'])}
 (d/(tag+'.result.json')).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'tag':tag,'exit_code':r.returncode,'seconds':result['seconds']}),flush=True)
 assert r.returncode==0,tag
for path in ['governance/data_center_architecture_inventory.json','governance/data_center_entrypoints.json']:
 p=d/'candidate'/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((export/path).read_bytes())
(d/'ready.json').write_text(json.dumps({'base':base,'export_root':str(export),'test_path':m['source_path'],'test_sha256':sha(export/m['source_path']),'projections':[{'path':p,'sha256':sha(export/p)} for p in ['governance/data_center_architecture_inventory.json','governance/data_center_entrypoints.json']],'all_declared_checks_passed':True},indent=2)+'\n')
