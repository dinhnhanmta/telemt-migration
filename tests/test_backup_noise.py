import copy,io,json,sys,tempfile,unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import archive,backup,store

def fixture(last_seen='2026-11-10T10:00:00Z',counter=1,setting='keep'):
    state={'sessions':{'test-session':{'Created':'2026-11-09T00:00:00Z','LastSeen':last_seen,'AuthMethod':'password'}},
           'settings':{'site':setting},'passkeys':{'test-key':{'public_key':'test-public-key'}}}
    objects={};entries=[]
    for path,data in [(store.PANEL_STATE,json.dumps(state).encode()),(store.DATABASE,str(counter).encode())]:
        digest=archive.sha(data);objects[digest]=data
        entries.append({'path':path,'type':'file','mode':0o600,'user':'root','group':'root','sha256':digest})
    manifest={'version':1,'kind':'state','entries':entries}
    return manifest,objects,archive.sha(json.dumps(entries,sort_keys=True).encode()),store.critical_fingerprint(manifest,objects)

class BackupNoiseTests(unittest.TestCase):
    def test_session_touch_and_metrics_change_only_full_snapshot_hash(self):
        a=fixture();b=fixture(last_seen='2026-11-10T10:05:00Z',counter=900)
        self.assertNotEqual(a[2],b[2]);self.assertEqual(a[3],b[3])
        original=archive.pack(*b[:2]);manifest,objects=archive.unpack(original,'state')
        entry=next(e for e in manifest['entries'] if e['path']==store.PANEL_STATE)
        self.assertEqual(json.loads(objects[entry['sha256']])['sessions']['test-session']['LastSeen'],'2026-11-10T10:05:00Z')

    def test_settings_passkeys_session_revocation_and_permissions_still_trigger(self):
        manifest,objects,_,baseline=fixture()
        for change in ['setting','passkey','revoke','new_session','permission']:
            m=copy.deepcopy(manifest);o=copy.deepcopy(objects)
            entry=next(e for e in m['entries'] if e['path']==store.PANEL_STATE)
            state=json.loads(o[entry['sha256']])
            if change=='setting':state['settings']['site']='changed'
            if change=='passkey':state['passkeys']['test-key']['public_key']='changed'
            if change=='revoke':state['sessions'].clear()
            if change=='new_session':state['sessions']['second']={'LastSeen':'now','Created':'now'}
            if change=='permission':entry['mode']=0o640
            data=json.dumps(state).encode();entry['sha256']=archive.sha(data);o[entry['sha256']]=data
            self.assertNotEqual(store.critical_fingerprint(m,o),baseline,change)

    def exercise_backup(self,changed,force=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'work';work.mkdir();repo=work/'repo';repo.mkdir();etc=root/'etc';etc.mkdir()
            (etc/'backup-password').write_text('unit-test-recovery-password\n')
            base=fixture();state_name='state-'+base[2]+'.enc'
            encrypted=archive.seal(archive.pack(*base[:2]),'unit-test-recovery-password')
            (repo/state_name).write_bytes(encrypted)
            previous={'version':1,'created_utc':'2026-11-10T10:00:00Z','fixed_fingerprint':'same-fixed',
                      'state_fingerprint':base[2],'critical_fingerprint':'legacy-raw-hash',
                      'state':{'path':state_name,'sha256':archive.sha(encrypted)},'fixed':{'path':'fixed-same.enc','sha256':'same'}}
            (repo/'snapshot.json').write_text(json.dumps(previous));(repo/'writer.json').write_text(json.dumps({'id':'unit-host'}))
            (work/'last.json').write_text(json.dumps({'fixed_stat':archive.sha(json.dumps([]).encode()),'last_database_checkpoint':0}))
            with patch.object(backup,'WORK',work),patch.object(backup,'ETC',etc),\
                 patch.object(backup,'prepare_repo',return_value=(repo,True)),patch.object(backup,'host_id',return_value='unit-host'),\
                 patch.object(backup,'source_paths',return_value={}),patch.object(backup,'capture',return_value=changed),\
                 patch.object(backup,'push') as push,patch.object(backup,'send_document',return_value=123) as send,\
                 patch.object(sys,'argv',['backup.py']+(['--force'] if force else [])),redirect_stdout(io.StringIO()):
                backup.main()
            return push.call_count,send.call_count,json.loads((repo/'snapshot.json').read_text())

    def test_upgrade_and_old_hourly_checkpoint_do_not_send_runtime_only_changes(self):
        pushed,sent,snapshot=self.exercise_backup(fixture(last_seen='2026-11-10T12:05:00Z',counter=999))
        self.assertEqual((pushed,sent),(0,0))
        self.assertEqual(snapshot['critical_fingerprint'],'legacy-raw-hash')

    def test_real_setting_change_still_uploads_and_notifies(self):
        pushed,sent,snapshot=self.exercise_backup(fixture(setting='new-setting'))
        self.assertEqual((pushed,sent),(1,1))
        self.assertEqual(snapshot['critical_fingerprint_version'],store.CRITICAL_FINGERPRINT_VERSION)

    def test_explicit_manual_force_can_save_latest_counters(self):
        pushed,sent,_=self.exercise_backup(fixture(counter=999),force=True)
        self.assertEqual((pushed,sent),(1,1))

if __name__=='__main__':unittest.main()
