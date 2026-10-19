import hashlib,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
BASE='96354c9ceba0ca46d49f667554a3498ffb286d20'
ENV=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTEST_ADDOPTS='',DJANGO_SETTINGS_MODULE='core.settings.development_sqlite')
PY=[str(ROOT/'agomtradepro/Scripts/python.exe'),'-X','utf8']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
PROTECTED=json.loads((ROOT/'.tmp/ash03-candidate-gates-203/inputs.json').read_text())['protected_raw_sha256']
def guard():
    assert git('branch','--show-current')=='dev/next-development'
    assert len(PROTECTED)==5
    for p,h in PROTECTED.items():assert sha(ROOT/p)==h,p
    assert 'flags: 20004000' in git('ls-files','--debug','--','tests/unit/simulated_trading/test_ash01_settlement_regressions.py')
def production_guard():
    rows=json.loads((ROOT/'.tmp/ash03-auto-types-194/debt.inputs.json').read_text())['owned_files']
    for row in rows:assert sha(ROOT/row['path'])==row['raw_sha256'],row['path']
    return len(rows)
def run(d,tag,c,cwd=ROOT):
    t=time.monotonic()
    with (d/(tag+'.log')).open('xb') as out:r=subprocess.run(c,cwd=cwd,env=ENV,stdout=out,stderr=subprocess.STDOUT)
    result={'command':c,'cwd':str(cwd),'exit_code':r.returncode,'seconds':round(time.monotonic()-t,3),'log_sha256':sha(d/(tag+'.log'))}
    (d/(tag+'.result.json')).write_text(json.dumps(result,indent=2)+'\n');guard();print(json.dumps({'tag':tag,'exit_code':r.returncode,'seconds':result['seconds']}),flush=True)
    assert r.returncode==0,tag
    return result
