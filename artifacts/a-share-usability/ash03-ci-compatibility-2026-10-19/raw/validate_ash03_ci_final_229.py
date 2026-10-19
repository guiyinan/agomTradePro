from ash_delivery_common_229 import *
d=ROOT/'.tmp/ash03-ci-final-229';d.mkdir();guard();production_guard();assert git('rev-parse','HEAD')==BASE
ready=json.loads((ROOT/'.tmp/ash03-clean-ci-candidate-225/ready.json').read_text());export=Path(ready['export_root'])
packet=ROOT/'.tmp/ash03-sdk-ci-candidate-228';assert sha(packet/'manifest.json')=='36f669cb04028b6da1086c5ddf00ba40ee5728aa5fdafe8e3fb1e9cb5ec6ec65'
row=json.loads((packet/'manifest.json').read_text())['files'][0];p=row['source_path'];candidate=packet/row['candidate_path']
assert sha(ROOT/p)==row['preimage_sha256'];assert sha(candidate)==row['candidate_sha256'];(export/p).write_bytes(candidate.read_bytes())
run(d,'sdk_black_format',PY+['-m','black',p],export)
for tag,c in [('black',PY+['-m','black','--check',p]),('isort',PY+['-m','isort','--check-only',p]),('ruff',PY+['-m','ruff','check',p]),('mcp_regression',PY+['-m','pytest',p,'sdk/tests/test_mcp/test_auto_trading_business_key.py','sdk/tests/test_mcp/test_core_registry_owner_simulated_auto_trading_scope.py','-q','-p','tests.support.fast_suite_guard','--basetemp='+str(export.parent/(export.name+'-mcp229')),'--junitxml='+str(d/'mcp.xml')]),('projections',PY+['scripts/check_data_center_governance_projections.py'])]:run(d,tag,c,export)
assert production_guard()==23
out=d/'candidate'/p;out.parent.mkdir(parents=True);out.write_bytes((export/p).read_bytes())
for r in ready['projections']:assert sha(export/r['path'])==r['sha256']
(d/'ready.json').write_text(json.dumps({'base':BASE,'source_path':p,'preimage_sha256':row['preimage_sha256'],'postimage_sha256':sha(out),'candidate':str(out),'production_files_unchanged':23,'protected_unchanged':True,'projection_outputs_unchanged_from_225':True},indent=2)+'\n')
