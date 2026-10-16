"""Private filesystem view. PRoot is isolation for evaluator tools, not hostile-code containment."""
import os
import shutil
import subprocess
from pathlib import Path
from .common import ROOT, sha, require

PROOT_HASH = 'db185300a9daabbce86aca7632d8c7fdc4249f6f153171954013b70c5f491ec0'


def command(attempt, argv):
    binary = ROOT/'.runtime/proot'
    require(sha(binary.read_bytes()) == PROOT_HASH, 'PRoot binary hash mismatch')
    root = attempt/'fs-root'
    mounts = [(Path(p), p) for p in ['/usr', '/bin', '/lib', '/lib64']]
    mounts += [(attempt/'workspace', '/work'), (attempt/'dsh-home', '/dsh-home'),
               (attempt/'private-tmp', '/tmp'), (attempt/'private-home', '/home/evaluator'),
               (ROOT/'.runtime/node_modules', '/opt/dsh/node_modules')]
    # Only mount the node executable, not its user's home or entire runtime prefix.
    node = Path(shutil.which('node')).resolve()
    mounts.append((node, '/opt/node'))
    for n in ['resolv.conf','hosts','nsswitch.conf','passwd','group','ssl/certs']:
        mounts.append((Path('/etc')/n, '/etc/'+n))
    for n in ['null','zero','random','urandom']:
        mounts.append((Path('/dev')/n, '/dev/'+n))
    for n in ['workspace','dsh-home','private-tmp','private-home','fs-root']:
        (attempt/n).mkdir(parents=True,exist_ok=True)
    cmd = [str(binary), '-r', str(root), '-w', '/work']
    for src, dst in mounts:
        if not src.exists(): continue
        target = root/dst.lstrip('/')
        target.parent.mkdir(parents=True,exist_ok=True)
        if src.is_dir(): target.mkdir(exist_ok=True)
        else: target.touch(exist_ok=True)
        cmd += ['-b', str(src)+':'+dst]
    env = {'PATH':'/opt:/usr/local/bin:/usr/bin:/bin', 'HOME':'/home/evaluator',
           'TMPDIR':'/tmp', 'LANG':'C.UTF-8', 'DSH_HOME':'/dsh-home',
           'DSH_PERMISSION_MODE':'danger-full-access', 'DSH_TELEMETRY_MODE':'OFF'}
    return cmd+argv, env


def probe(folder):
    folder.mkdir(parents=True,exist_ok=True)
    sentinel = ROOT/'.runtime/isolation-sentinel'
    sentinel.write_text('must not be visible')
    script = "const fs=require('fs'); if(fs.existsSync(process.argv[1])||fs.existsSync('/proc/1/environ'))process.exit(8);fs.writeFileSync('/tmp/probe','private'); console.log('private filesystem OK')"
    cmd, env = command(folder, ['/opt/node', '-e', script, str(sentinel)])
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    require(p.returncode==0, 'Isolation preflight failed: '+p.stderr)
    require((folder/'private-tmp/probe').is_file(), 'Private tmp missing')
    return {'private_filesystem':True,'private_tmp':True,'host_project_and_proc_hidden':True,'proot_sha256':PROOT_HASH}
