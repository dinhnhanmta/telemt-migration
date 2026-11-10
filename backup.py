"""Push only changed encrypted snapshots; never stop or reload the live services."""
import argparse,fcntl,json,os
from datetime import datetime,timezone
from pathlib import Path
from archive import *
from store import capture,account_manifest,source_paths,critical_fingerprint,CRITICAL_FINGERPRINT_VERSION
from transport import *

def atomic_json(path,value):
    temp=path.with_suffix('.new');temp.write_text(json.dumps(value,indent=2));temp.chmod(0o600);temp.replace(path)

def previous_critical(repo,previous,password,local):
    if not previous:return None
    if previous.get('critical_fingerprint_version')==CRITICAL_FINGERPRINT_VERSION:
        return previous['critical_fingerprint']
    # Migrate an old baseline by interpreting its authenticated archived bytes
    # with the new rules. Do not send a false change notification on upgrade.
    entry=previous['state'];cached=local.get('critical_baseline',{})
    if cached.get('snapshot_sha256')==entry['sha256'] and cached.get('version')==CRITICAL_FINGERPRINT_VERSION:
        return cached['fingerprint']
    if not re.fullmatch(r'state-[a-f0-9]{64}\.enc',entry['path']):raise ValueError('Invalid previous snapshot filename')
    data=(repo/entry['path']).read_bytes()
    if sha(data)!=entry['sha256']:raise ValueError('Previous encrypted snapshot checksum mismatch')
    manifest,objects=unpack(unseal(data,password),'state')
    fingerprint=critical_fingerprint(manifest,objects)
    local['critical_baseline']={'snapshot_sha256':entry['sha256'],'version':CRITICAL_FINGERPRINT_VERSION,'fingerprint':fingerprint}
    return fingerprint

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--force',action='store_true',help='Manually include changed runtime counters and session timestamps')
    args=parser.parse_args()
    assert os.geteuid()==0,'Run as root'
    os.umask(0o077);WORK.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (WORK/'backup.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        repo,exists=prepare_repo();owner=host_id()
        if exists:
            writer=json.loads((repo/'writer.json').read_text())
            if writer['id']!=owner:
                print('Standby writer: a restored VPS owns backups. Live services remain running.');return
        localfile=WORK/'last.json'
        local=json.loads(localfile.read_text()) if localfile.exists() else {}
        previous=json.loads((repo/'snapshot.json').read_text()) if (repo/'snapshot.json').exists() else {}
        stamp=datetime.now(timezone.utc).isoformat()
        signature=[(name,path.stat().st_size,path.stat().st_mtime_ns,path.stat().st_mode,path.stat().st_uid,path.stat().st_gid)
                   for name,path in sorted(source_paths('fixed').items())]
        stat_fingerprint=sha(json.dumps(signature).encode())
        password=(ETC/'backup-password').read_text().strip()
        fixed_changed=not previous or local.get('fixed_stat')!=stat_fingerprint
        fixed_plain=None
        if fixed_changed:
            manifest,objects,fixed_hash,_=capture('fixed')
            manifest['accounts']=account_manifest();manifest['platform']='ubuntu24.04-amd64'
            if fixed_hash!=previous.get('fixed_fingerprint'):fixed_plain=pack(manifest,objects)
        else:fixed_hash=previous['fixed_fingerprint']
        state_manifest,state_objects,state_hash,critical_hash=capture('state')
        verify_certificates(state_manifest,state_objects)
        critical_changed=critical_hash!=previous_critical(repo,previous,password,local)
        state_changed=state_hash!=previous.get('state_fingerprint')
        changed=bool(fixed_plain) or critical_changed or (state_changed and args.force)
        if changed:
            state_plain=pack(state_manifest,state_objects)
            snapshot={'version':1,'created_utc':stamp,'fixed_fingerprint':fixed_hash,'state_fingerprint':state_hash,
             'critical_fingerprint':critical_hash,'critical_fingerprint_version':CRITICAL_FINGERPRINT_VERSION,'platform':'ubuntu24.04-amd64'}
            pending=local.get('pending_telegram',[])
            if fixed_plain:
                filename='fixed-'+fixed_hash+'.enc'
                (repo/filename).write_bytes(seal(fixed_plain,password))
                snapshot['fixed']={'path':filename,'sha256':sha((repo/filename).read_bytes())}
                pending.append({'file':filename,'caption':'Telemt recovery: fixed binaries/services/Caddy support. '+stamp})
            else:snapshot['fixed']=previous['fixed']
            state_name='state-'+state_hash+'.enc'
            if not (repo/state_name).exists():(repo/state_name).write_bytes(seal(state_plain,password))
            snapshot['state']={'path':state_name,'sha256':sha((repo/state_name).read_bytes())}
            if state_hash!=previous.get('state_fingerprint'):
                pending.append({'file':state_name,'caption':'Telemt recovery: encrypted customers/config/SQLite/Caddy certificates. '+stamp})
            # Retain the immediately previous snapshot as an independent fallback.
            if previous:atomic_json(repo/'previous.json',previous)
            atomic_json(repo/'snapshot.json',snapshot)
            atomic_json(repo/'writer.json',{'id':owner,'updated_utc':stamp})
            keep={snapshot[x]['path'] for x in ['fixed','state']}
            if previous:keep|={previous[x]['path'] for x in ['fixed','state']}
            keep|={x['file'] for x in pending}
            for path in repo.glob('*.enc'):
                if path.name not in keep:path.unlink()
            push(repo,'Encrypted Telemt recovery snapshot '+stamp)
            local.update({'pending_telegram':pending})
            print('Uploaded changed encrypted snapshot to GitHub: '+stamp)
        else:print('No recovery changes; no commit and no Telegram message.')
        local['fixed_stat']=stat_fingerprint
        atomic_json(localfile,local)
        failures=[]
        for item in local.get('pending_telegram',[]):
            try:
                message=send_document(repo/item['file'],item['caption'])
                print('Telegram encrypted backup delivered; message '+str(message))
            except Exception as error:
                failures.append(item)
                print('Telegram delivery pending: '+type(error).__name__)
        local['pending_telegram']=failures
        atomic_json(localfile,local)

if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Backup failed: '+str(error))
