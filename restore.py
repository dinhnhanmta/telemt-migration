"""Restore existing binaries/services/customer state, without running an upstream installer."""
import argparse,getpass,json,os,platform,pwd,shutil,sqlite3,subprocess,tempfile,time,tomllib,urllib.request
from pathlib import Path
from archive import *
from store import without_active_sessions

REPO='dinhnhanmta/telemt-migration'

def fetch(url,limit=55*1024*1024):
    request=urllib.request.Request(url,headers={'User-Agent':'telemt-migration'})
    with urllib.request.urlopen(request,timeout=120) as response:data=response.read(limit+1)
    if len(data)>limit:raise ValueError('Download too large')
    return data

def snapshot():
    commit=json.loads(fetch('https://api.github.com/repos/'+REPO+'/commits/backups',1024*1024))['sha']
    if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('Invalid backup revision')
    base='https://raw.githubusercontent.com/'+REPO+'/'+commit+'/'
    data=json.loads(fetch(base+'snapshot.json',1024*1024))
    return base,data

def load(base,entry,password,kind):
    if not re.fullmatch(kind+r'-[a-f0-9]{64}\.enc',entry['path']):raise ValueError('Invalid snapshot filename')
    data=fetch(base+entry['path'])
    if sha(data)!=entry['sha256']:raise ValueError('Encrypted snapshot checksum mismatch')
    return unpack(unseal(data,password),kind)

def validate(fixed,state):
    manifest,objects=fixed
    verify_certificates(*state)
    if manifest.get('platform')!='ubuntu24.04-amd64':raise ValueError('Unsupported source platform')
    if set(FIXED_FILES)-{x['path'] for x in manifest['entries']}:raise ValueError('Fixed snapshot incomplete')
    entries={x['path']:x for x in state[0]['entries'] if x['type']=='file'}
    for path in ['/etc/telemt/telemt.toml','/etc/telemt-panel/config.toml','/var/lib/telemt-panel/panel.db','/etc/caddy/Caddyfile']:
        if path not in entries:raise ValueError('State snapshot incomplete: '+path)
    for path in ['/etc/telemt/telemt.toml','/etc/telemt-panel/config.toml']:
        tomllib.loads(state[1][entries[path]['sha256']].decode())
    with tempfile.TemporaryDirectory(prefix='telemt-db-check-') as temporary:
        dbfile=Path(temporary)/'panel.db';dbfile.write_bytes(state[1][entries['/var/lib/telemt-panel/panel.db']['sha256']])
        with sqlite3.connect(dbfile) as db:
            if db.execute('pragma quick_check').fetchone()[0]!='ok':raise ValueError('Invalid panel database')

def accounts(manifest):
    expected={'telemt':('/opt/telemt','/usr/sbin/nologin'),'telemt-panel':('/nonexistent','/usr/sbin/nologin'),'caddy':('/var/lib/caddy','/usr/sbin/nologin')}
    for entry in manifest['accounts']:
        name=entry['name']
        if name not in expected or (entry['home'],entry['shell'])!=expected[name] or entry['group']!=name:raise ValueError('Unexpected account metadata')
        try:
            user=pwd.getpwnam(name)
            if user.pw_uid==0 or user.pw_shell not in ['/usr/sbin/nologin','/bin/false']:raise ValueError('Existing account is not a service user: '+name)
        except KeyError:
            subprocess.run(['useradd','--system','--user-group','--home-dir',entry['home'],'--shell',entry['shell'],name],check=True)
        if entry['home']!='/nonexistent':
            home=Path(entry['home']);home.mkdir(parents=True,exist_ok=True)
            user=pwd.getpwnam(name);os.chown(home,user.pw_uid,user.pw_gid)

def run_services(action):subprocess.run(['systemctl',action,'telemt','telemt-panel','caddy'],check=True)

def health():
    import socket,ssl
    deadline=time.monotonic()+35
    while True:
        try:
            for port in [8080,9091,18080,443]:
                with socket.create_connection(('127.0.0.1',port),timeout=1):pass
            for name in ['telemt','telemt-panel','caddy']:
                subprocess.run(['systemctl','is-active','--quiet',name],check=True)
            return
        except (OSError,subprocess.CalledProcessError):
            if time.monotonic()>deadline:raise RuntimeError('Restored service health check failed; inspect journalctl locally')
            time.sleep(1)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--stage-dir',type=Path,help='Decrypt into an empty private directory, do not start services')
    args=p.parse_args();os.umask(0o077)
    if os.geteuid()!=0:raise ValueError('Run as root')
    password=getpass.getpass('Recovery password (same as the existing AWG recovery kit): ')
    base,info=snapshot();fixed=load(base,info['fixed'],password,'fixed');state=load(base,info['state'],password,'state')
    validate(fixed,state)
    print('Authenticated snapshot '+info['created_utc']+'; binaries, customers, panel database and Caddy storage verified.',flush=True)
    if args.dry_run:return
    if args.stage_dir:
        target=args.stage_dir
        if not target.is_absolute() or len(target.parts)<3 or target.exists():raise ValueError('Stage directory must be a new private absolute directory')
        target.mkdir(mode=0o700)
        materialize(*fixed,target=target,owners=False);materialize(*without_active_sessions(*state),target=target,owners=False)
        print('Staged verified snapshot without changing services: '+str(target));return
    release=dict(line.split('=',1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if platform.machine()!='x86_64' or release.get('ID','').strip('"')!='ubuntu' or release.get('VERSION_ID','').strip('"')!='24.04':raise ValueError('Fresh Ubuntu24.04 amd64 is required')
    marker=Path('/etc/telemt-migration/restored.json')
    if not marker.exists():
        for path in ['/usr/bin/telemt','/usr/local/bin/telemt-panel','/etc/caddy/Caddyfile','/etc/telemt/telemt.toml']:
            if Path(path).exists():raise ValueError('Existing application detected; restore on a fresh VPS: '+path)
        import socket
        for port in [80,443,8080,9091,18080,8443]:
            with socket.socket() as sock:
                if sock.connect_ex(('127.0.0.1',port))==0:raise ValueError('Existing listener conflicts with restore: '+str(port))
    env=os.environ.copy();env.update(DEBIAN_FRONTEND='noninteractive',NEEDRESTART_MODE='l')
    subprocess.run(['apt-get','update','-qq'],env=env,check=True)
    subprocess.run(['apt-get','install','-y','--no-install-recommends','libgcc-s1','libzstd1','sudo','git','openssh-client','curl','ca-certificates'],env=env,check=True)
    accounts(fixed[0])
    # Download the latest state again after dependency installation; old server stays serving.
    base,latest=snapshot()
    if latest['fixed']!=info['fixed']:fixed=load(base,latest['fixed'],password,'fixed')
    state=load(base,latest['state'],password,'state');info=latest;validate(fixed,state)
    if marker.exists():run_services('stop')
    materialize(*fixed);materialize(*without_active_sessions(*state))
    app=Path('/usr/local/lib/telemt-migration');app.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name in ['archive.py','store.py','transport.py','backup.py','automation.py','restore.py']:
        sourcefile=Path(__file__).resolve().parent/name
        if sourcefile.resolve()!=(app/name).resolve():shutil.copyfile(sourcefile,app/name)
        (app/name).chmod(0o600)
    private=Path('/etc/telemt-migration');private.mkdir(exist_ok=True,mode=0o700);private.chmod(0o700)
    (private/'backup-password').write_text(password+'\n');(private/'backup-password').chmod(0o600)
    marker.write_text(json.dumps({'version':1,'snapshot':info['created_utc']}))
    subprocess.run(['visudo','-cf','/etc/sudoers.d/telemt-panel'],check=True)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','telemt','telemt-panel','caddy'],check=True)
    run_services('start');health()
    if subprocess.run(['sh','-c','command -v ufw >/dev/null && ufw status | head -n1 | grep -qx "Status: active"']).returncode==0:
        for port in ['80/tcp','443/tcp']:subprocess.run(['ufw','allow',port,'comment','telemt-web'],check=True)
    # Transfer backup ownership only after successful restoration. Old writer then becomes standby.
    from transport import prepare_repo,host_id,push
    repo,exists=prepare_repo()
    current=json.loads((repo/'snapshot.json').read_text())
    if current['state_fingerprint']!=info['state_fingerprint'] or current['fixed_fingerprint']!=info['fixed_fingerprint']:
        raise RuntimeError('Source changed during final restore. Keep DNS on old VPS, rerun this command before cutover.')
    (repo/'writer.json').write_text(json.dumps({'id':host_id(),'updated_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}))
    push(repo,'Transfer backup ownership after verified VPS restore')
    from automation import install
    install()
    print('RESTORED. Existing customer secrets/domain/port are retained. Now update Cloudflare A record; keep old VPS online during DNS propagation.')
    print('Auto-backup ownership moved here. No upstream Telemt installer or public MTProxy port was used.')

if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Restore stopped: '+str(error))
