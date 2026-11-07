import http.client,json,os,shlex,subprocess,uuid
from pathlib import Path

ETC=Path('/etc/telemt-migration')
WORK=Path('/var/lib/telemt-migration')
REMOTE='ssh://git@ssh.github.com:443/dinhnhanmta/telemt-migration.git'
BRANCH='backups'

def git(repo,*args,check=True):
    env=os.environ.copy()
    env['GIT_SSH_COMMAND']=shlex.join(['ssh','-i',str(ETC/'github-key'),'-o','IdentitiesOnly=yes','-o','BatchMode=yes',
      '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(ETC/'known_hosts'),'-o','ConnectTimeout=15'])
    result=subprocess.run(['git','-C',str(repo),*args],env=env,capture_output=True,text=True,timeout=180)
    if check and result.returncode:raise RuntimeError('Git operation failed: '+result.stderr.strip()[:700])
    return result

def prepare_repo():
    repo=WORK/'repo'
    repo.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not (repo/'.git').exists():
        git(repo,'init','--initial-branch='+BRANCH)
        git(repo,'remote','add','origin',REMOTE)
        git(repo,'config','user.name','telemt-backup')
        git(repo,'config','user.email','telemt-backup@localhost')
        git(repo,'config','core.autocrlf','false')
    assert git(repo,'remote','get-url','origin').stdout.strip()==REMOTE,'Unexpected backup repository'
    exists=bool(git(repo,'ls-remote','origin','refs/heads/'+BRANCH).stdout.strip())
    if exists:
        git(repo,'fetch','--quiet','origin',BRANCH)
        # Only the dedicated encrypted-data checkout is reset, never the application files.
        git(repo,'reset','--hard','FETCH_HEAD')
    return repo,exists

def host_id():
    path=ETC/'host-id'
    if not path.exists():path.write_text(uuid.uuid4().hex);path.chmod(0o600)
    return path.read_text().strip()

def push(repo,message):
    git(repo,'add','--all')
    if git(repo,'diff','--cached','--quiet',check=False).returncode==0:return False
    git(repo,'commit','--quiet','-m',message)
    git(repo,'push','--quiet','origin','HEAD:refs/heads/'+BRANCH)
    return True

def send_document(path,caption):
    config=json.loads((ETC/'telegram.json').read_text())
    boundary='telemt-'+uuid.uuid4().hex
    fields=b''
    for key,value in [('chat_id',str(config['chat_id'])),('caption',caption)]:
        fields+=('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+value+'\r\n').encode()
    head=fields+('--'+boundary+'\r\nContent-Disposition: form-data; name="document"; filename="'+path.name+'"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
    tail=('\r\n--'+boundary+'--\r\n').encode()
    if path.stat().st_size>49*1024*1024:raise RuntimeError('Encrypted attachment exceeds Telegram upload limit')
    connection=http.client.HTTPSConnection('api.telegram.org',timeout=120)
    try:
        connection.putrequest('POST','/bot'+config['token']+'/sendDocument')
        connection.putheader('Content-Type','multipart/form-data; boundary='+boundary)
        connection.putheader('Content-Length',str(len(head)+path.stat().st_size+len(tail)))
        connection.endheaders();connection.send(head)
        with path.open('rb') as source:
            while chunk:=source.read(1024*1024):connection.send(chunk)
        connection.send(tail)
        response=connection.getresponse();data=json.loads(response.read())
        if response.status!=200 or not data.get('ok'):raise RuntimeError('Telegram document upload failed (HTTP '+str(response.status)+')')
        return data['result']['message_id']
    finally:connection.close()
