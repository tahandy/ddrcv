"""Real locked/inexact update and wheel checks in disposable Windows venvs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path.cwd()
OUT = ROOT/'experiments/jacket_lookup/artifacts/integration'
UV = ROOT/'.tools/uv-0.10.12/uv.exe'
ENV = OUT/'install-venv'
PYTHON = ENV/'Scripts/python.exe'
records = []


def run(name, args, *, env=None, cwd=ROOT):
    result = subprocess.run([str(a) for a in args], env=env, cwd=cwd,
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    (OUT/f'install-{name}.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    records.append(dict(name=name,ok=result.returncode==0))
    if result.returncode:
        raise RuntimeError(f'{name} failed: '+result.stderr[-2000:])


def main():
    if not PYTHON.exists():
        run('venv',[UV,'venv','--seed','--python',sys.executable,'--no-python-downloads',ENV])
    env = {**os.environ, 'UV_PROJECT_ENVIRONMENT':str(ENV)}
    base=[UV,'sync','--locked','--inexact','--no-dev','--extra','workbench',
          '--python',PYTHON,'--no-python-downloads']
    run('fresh',base,env=env)
    sentinel = OUT/'ddrcv_install_sentinel-0.0.0-py3-none-any.whl'
    with zipfile.ZipFile(sentinel,'w') as z:
        z.writestr('ddrcv_install_sentinel.py','VALUE = 123\n')
        z.writestr('ddrcv_install_sentinel-0.0.0.dist-info/METADATA',
                   'Metadata-Version: 2.1\nName: ddrcv-install-sentinel\nVersion: 0.0.0\n')
        z.writestr('ddrcv_install_sentinel-0.0.0.dist-info/WHEEL',
                   'Wheel-Version: 1.0\nGenerator: integration-check\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        z.writestr('ddrcv_install_sentinel-0.0.0.dist-info/RECORD','')
    run('sentinel',[UV,'pip','install','--python',PYTHON,'--no-deps',sentinel])
    run('repeat',base,env=env)
    run('existing-update',base+['--extra','jacket-lookup'],env=env)
    run('repeat-update',base+['--extra','jacket-lookup'],env=env)
    run('preserved',[PYTHON,'-B','-c','import ddrcv_install_sentinel; assert ddrcv_install_sentinel.VALUE == 123'])
    wheel=next((OUT/'dist').glob('ddrcv-*-py3-none-any.whl'))
    run('wheel',[UV,'pip','install','--python',PYTHON,'--reinstall','--no-deps',wheel])
    with tempfile.TemporaryDirectory(prefix='ddrcv wheel check ') as tmp:
        shutil.copy2(ROOT/'tests/test_packaging.py',Path(tmp)/'test_packaging.py')
        run('wheel-assets',[PYTHON,'-B',Path(tmp)/'test_packaging.py'],cwd=tmp)
        script = """
from pathlib import Path
import ddrcv
assert 'site-packages' in str(Path(ddrcv.__file__)).lower(), ddrcv.__file__
import urllib.request
urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError('Network during lookup'))
from ddrcv.jacket_lookup.assets import load, processor
from ddrcv.jacket_lookup.images import read_image
lookup=load(dict(catalog_file=CATALOG))
worker=processor(dict(catalog_file=CATALOG),lookup=lookup)
try:
 result=worker.analyze(read_image(FRAME))
 assert result['accepted'],result
finally: worker.close()
"""
        frame=ROOT/'experiments/jacket_lookup/artifacts/corpus/frames/2025-03-19_16-29-40_00.png'
        script='CATALOG='+repr(str(OUT/'dia_del_ritmo_26.ddrcatalog'))+'\nFRAME='+repr(str(frame))+'\n'+script
        run('wheel-offline',[PYTHON,'-B','-c',script],cwd=tmp)
    # Only the base image dependencies: no OCR, neural runtime, or editable install.
    minimal=OUT/'minimal-venv'; mini_python=minimal/'Scripts/python.exe'
    if not mini_python.exists():
        run('minimal-venv',[UV,'venv','--python',sys.executable,'--no-python-downloads',minimal])
    run('minimal-install',[UV,'pip','install','--reinstall','--python',mini_python,wheel])
    run('minimal-offline',[mini_python,'-B','-c',
        "import importlib.util; assert importlib.util.find_spec('onnxruntime') is None; "
        "assert importlib.util.find_spec('rapidocr') is None;\n"+script],cwd=OUT)
    run('browser-tools',[UV,'pip','install','--python',PYTHON,'playwright==1.58.0'])
    (OUT/'installation.json').write_text(json.dumps(dict(checks=records),indent=2))
    print(json.dumps(records))


if __name__=='__main__': main()
