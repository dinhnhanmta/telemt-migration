"""Consistent live capture with deduplicated binaries and SQLite online backup."""
import grp,hashlib,json,os,pwd,sqlite3,stat,tempfile,time
from pathlib import Path
from archive import *

DATABASE='/var/lib/telemt-panel/panel.db'
VOLATILE_TABLES={'metric_points','history_events','user_ip_history','user_ip_history_collection',
 'user_traffic_buckets','user_traffic_collector','user_traffic_users'}

def stable_read(path):
    for _ in range(3):
        before=path.stat();data=path.read_bytes();after=path.stat()
        if (before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns):return data
    raise RuntimeError('File is being modified; retry backup: '+str(path))

def database_copy(path):
    with tempfile.TemporaryDirectory(prefix='telemt-sqlite-') as temporary:
        target=Path(temporary)/'snapshot.db'
        with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=5) as source,sqlite3.connect(target) as dest:
            source.backup(dest,pages=128,sleep=0.02)
            if dest.execute('pragma quick_check').fetchone()[0]!='ok':raise ValueError('SQLite backup failed validation')
            lines=list(dest.iterdump())
        return target.read_bytes(),sha('\n'.join(lines).encode())

def source_paths(kind):
    roots=FIXED_FILES+FIXED_TREES if kind=='fixed' else STATE_ROOTS
    result={}
    for name in roots:
        source=Path(name)
        if name=='/etc/systemd/system/caddy.service' and not source.exists():source=Path('/usr/lib/systemd/system/caddy.service')
        if not source.exists():continue
        if source.is_symlink():raise ValueError('Unexpected source symlink: '+str(source))
        result[name]=source
        if source.is_dir():
            for current,dirs,files in os.walk(source):
                dirs[:]=[d for d in dirs if d not in ['staging','backups','.git'] and not d.startswith('.tmp')]
                for leaf in dirs+files:
                    path=Path(current)/leaf
                    if path.is_symlink():raise ValueError('Unexpected source symlink: '+str(path))
                    if leaf.endswith(('-wal','-shm','-journal','.lock')) or leaf.startswith('.panel.lock'):continue
                    if leaf.startswith('.') and source==Path('/opt/telemt'):continue
                    result[name+'/'+str(path.relative_to(source))]=path
    return result

def capture(kind):
    objects={};entries=[];finger=[]
    for name,source in sorted(source_paths(kind).items()):
        info=source.stat()
        if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):raise ValueError('Unsupported source file: '+str(source))
        user=pwd.getpwuid(info.st_uid).pw_name;group=grp.getgrgid(info.st_gid).gr_name
        if user not in ['root',*ACCOUNTS] or group not in ['root',*ACCOUNTS]:raise ValueError('Unexpected source owner: '+name+' '+user+':'+group)
        entry={'path':name,'type':'dir' if source.is_dir() else 'file','mode':stat.S_IMODE(info.st_mode)&0o777,'user':user,'group':group}
        compare=dict(entry)
        if source.is_file():
            if name==DATABASE:data,logical=database_copy(source)
            else:data=stable_read(source);logical=sha(data)
            entry['sha256']=sha(data);objects[entry['sha256']]=data
            compare['sha256']=logical
        entries.append(entry);finger.append(compare)
    if kind=='fixed':
        required=set(FIXED_FILES)
        if not required.issubset({e['path'] for e in entries}):raise ValueError('Required binary/service/backup key missing')
    critical=[e for e in finger if e['path']!=DATABASE]
    manifest={'version':1,'kind':kind,'entries':entries}
    return manifest,objects,sha(json.dumps(finger,sort_keys=True).encode()),sha(json.dumps(critical,sort_keys=True).encode())

def account_manifest():
    result=[]
    for name in ACCOUNTS:
        user=pwd.getpwnam(name)
        result.append({'name':name,'home':user.pw_dir,'shell':user.pw_shell,'group':grp.getgrgid(user.pw_gid).gr_name})
    return result
