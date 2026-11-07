"""Authenticated, path-checked snapshots; no plaintext secrets are published."""
import hashlib,io,json,os,re,tarfile
from pathlib import Path,PurePosixPath
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC=b'TELKIT1\0'
MAX_PLAIN=200*1024*1024
FIXED_FILES=['/usr/bin/telemt','/usr/local/bin/telemt-panel','/usr/local/libexec/telemt-panel-privileged',
 '/usr/bin/caddy','/usr/local/sbin/telemt-web-manager','/etc/systemd/system/telemt.service',
 '/etc/systemd/system/telemt-panel.service','/etc/systemd/system/caddy.service',
 '/etc/telemt-migration/github-key','/etc/telemt-migration/known_hosts','/etc/telemt-migration/telegram.json']
FIXED_TREES=['/etc/systemd/system/telemt.service.d','/etc/systemd/system/telemt-panel.service.d',
 '/etc/systemd/system/caddy.service.d','/etc/systemd/system/telemt-web-manager.service.d']
STATE_ROOTS=['/etc/telemt','/etc/telemt-panel','/etc/telemt-panel-privileged','/etc/caddy',
 '/etc/sudoers.d/telemt-panel','/etc/telemt-web-manager','/opt/telemt','/var/lib/telemt',
 '/var/lib/telemt-panel','/var/lib/caddy/.local/share/caddy','/var/lib/caddy/.config/caddy']
ACCOUNTS=['telemt','telemt-panel','caddy']

def sha(data):return hashlib.sha256(data).hexdigest()

def allowed(path,kind):
    p=PurePosixPath(path)
    if not p.is_absolute() or '..' in p.parts or '\\' in path or '\x00' in path:return False
    roots=STATE_ROOTS if kind=='state' else FIXED_TREES
    return path in FIXED_FILES if kind=='fixed' and path in FIXED_FILES else any(path==r or path.startswith(r+'/') for r in roots)

def seal(plain,password):
    header=MAGIC+os.urandom(16)+os.urandom(12)
    key=Scrypt(salt=header[8:24],length=32,n=2**17,r=8,p=1).derive(password.encode())
    return header+AESGCM(key).encrypt(header[24:36],plain,header)

def unseal(data,password):
    if len(data)<52 or data[:8]!=MAGIC:raise ValueError('Invalid encrypted snapshot format')
    key=Scrypt(salt=data[8:24],length=32,n=2**17,r=8,p=1).derive(password.encode())
    try:return AESGCM(key).decrypt(data[24:36],data[36:],data[:36])
    except InvalidTag as error:raise ValueError('Wrong recovery password or damaged snapshot; no files restored') from error

def pack(manifest,objects):
    data=io.BytesIO()
    with tarfile.open(fileobj=data,mode='w:gz',compresslevel=6) as archive:
        values={'manifest.json':json.dumps(manifest,sort_keys=True).encode(),**{'objects/'+k:v for k,v in objects.items()}}
        for name,content in sorted(values.items()):
            member=tarfile.TarInfo(name);member.size=len(content);member.mode=0o600
            archive.addfile(member,io.BytesIO(content))
    return data.getvalue()

def verify_certificates(manifest,objects):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    files={e['path']:e for e in manifest['entries'] if e['type']=='file'}
    for path,entry in files.items():
        if not path.endswith('.crt'):continue
        key=files.get(path[:-4]+'.key')
        if not key:continue
        cert=x509.load_pem_x509_certificate(objects[entry['sha256']])
        private=serialization.load_pem_private_key(objects[key['sha256']],password=None)
        fmt=(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        if cert.public_key().public_bytes(*fmt)!=private.public_key().public_bytes(*fmt):raise ValueError('Certificate/private key mismatch in snapshot')

def unpack(plain,expected_kind):
    objects={};manifest=None;total=0
    with tarfile.open(fileobj=io.BytesIO(plain),mode='r:gz') as archive:
        for number,member in enumerate(archive):
            if number>10000 or not member.isfile() or member.size<0:raise ValueError('Unsafe archive member')
            total+=member.size
            if total>MAX_PLAIN:raise ValueError('Snapshot too large')
            if member.name=='manifest.json':
                if manifest is not None:raise ValueError('Duplicate manifest')
                manifest=json.loads(archive.extractfile(member).read())
            elif re.fullmatch(r'objects/[a-f0-9]{64}',member.name):
                content=archive.extractfile(member).read();digest=member.name[8:]
                if digest in objects or sha(content)!=digest:raise ValueError('Object checksum mismatch')
                objects[digest]=content
            else:raise ValueError('Unsafe archive path')
    if not manifest or manifest.get('kind')!=expected_kind or manifest.get('version')!=1:raise ValueError('Unexpected manifest')
    seen=set()
    for entry in manifest['entries']:
        path=entry['path']
        if path in seen or not allowed(path,expected_kind):raise ValueError('Disallowed restore destination: '+path)
        seen.add(path)
        if entry['type'] not in ('file','dir'):raise ValueError('Links and special files are not accepted')
        if entry['type']=='file' and entry['sha256'] not in objects:raise ValueError('Missing file object')
        if not 0<=entry['mode']<=0o777:raise ValueError('Unexpected file permissions')
        if entry['user'] not in ['root',*ACCOUNTS] or entry['group'] not in ['root',*ACCOUNTS]:raise ValueError('Unexpected file owner')
    return manifest,objects

def materialize(manifest,objects,target=Path('/'),owners=True):
    import grp,pwd
    root=target.resolve()
    def destination(name):
        path=root/name.lstrip('/')
        for parent in [path,*path.parents]:
            if parent==root:break
            if parent.is_symlink():raise ValueError('Refusing to traverse destination symlink: '+str(parent))
        return path
    entries=sorted(manifest['entries'],key=lambda e:(e['type']!='dir',len(PurePosixPath(e['path']).parts),e['path']))
    for entry in entries:
        path=destination(entry['path'])
        missing=[];parent=path.parent
        while not parent.exists():missing.append(parent);parent=parent.parent
        for parent in reversed(missing):parent.mkdir(mode=0o755);parent.chmod(0o755)
        if entry['type']=='dir':path.mkdir(exist_ok=True)
        else:
            temp=path.with_name(path.name+'.telemt-restore-new')
            if temp.is_symlink():raise ValueError('Unsafe temporary destination')
            temp.write_bytes(objects[entry['sha256']]);temp.chmod(entry['mode']);temp.replace(path)
        path.chmod(entry['mode'])
        if owners:os.chown(path,pwd.getpwnam(entry['user']).pw_uid,grp.getgrnam(entry['group']).gr_gid)
    return len(entries)
