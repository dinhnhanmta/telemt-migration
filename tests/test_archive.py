import io,json,sqlite3,sys,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import archive,store

class RecoveryTests(unittest.TestCase):
    def fixture(self):
        data=b'private customer state';digest=archive.sha(data)
        return {'version':1,'kind':'state','entries':[{'path':'/etc/telemt/telemt.toml','type':'file','mode':0o600,'user':'root','group':'root','sha256':digest}]},{digest:data}

    def test_round_trip_and_permissions(self):
        manifest,objects=self.fixture();plain=archive.pack(manifest,objects)
        encrypted=archive.seal(plain,'test-recovery-password')
        self.assertNotIn(b'private customer state',encrypted)
        restored=archive.unpack(archive.unseal(encrypted,'test-recovery-password'),'state')
        with tempfile.TemporaryDirectory() as tmp:
            archive.materialize(*restored,target=Path(tmp),owners=False)
            p=Path(tmp)/'etc/telemt/telemt.toml'
            self.assertEqual(p.read_bytes(),b'private customer state')
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            self.assertEqual((Path(tmp)/'etc').stat().st_mode&0o777,0o755)

    def test_wrong_password_and_tampering(self):
        payload=archive.seal(archive.pack(*self.fixture()),'correct')
        with self.assertRaises(ValueError):archive.unseal(payload,'wrong')
        with self.assertRaises(ValueError):archive.unseal(payload[:-1]+bytes([payload[-1]^1]),'correct')

    def test_archive_traversal_and_links(self):
        for name,kind in [('../escape',tarfile.REGTYPE),('manifest.json',tarfile.SYMTYPE)]:
            buf=io.BytesIO()
            with tarfile.open(fileobj=buf,mode='w:gz') as tar:
                member=tarfile.TarInfo(name);member.type=kind;member.linkname='/etc/passwd';tar.addfile(member)
            with self.assertRaises(ValueError):archive.unpack(buf.getvalue(),'state')

    def test_destination_allowlist_and_symlink(self):
        manifest,objects=self.fixture()
        manifest['entries'][0]['path']='/etc/ssh/sshd_config'
        with self.assertRaises(ValueError):archive.unpack(archive.pack(manifest,objects),'state')
        manifest,objects=self.fixture()
        with tempfile.TemporaryDirectory() as tmp,tempfile.TemporaryDirectory() as elsewhere:
            root=Path(tmp);(root/'etc').symlink_to(elsewhere,target_is_directory=True)
            with self.assertRaises(ValueError):archive.materialize(manifest,objects,target=root,owners=False)

    def test_binary_content_deduplicated(self):
        data=b'same-binary'*100;digest=archive.sha(data)
        entries=[{'path':name,'type':'file','mode':0o755,'user':'root','group':'root','sha256':digest} for name in ['/usr/local/bin/telemt-panel','/usr/local/libexec/telemt-panel-privileged']]
        manifest,objects=archive.unpack(archive.pack({'version':1,'kind':'fixed','entries':entries},{digest:data}),'fixed')
        self.assertEqual(len(manifest['entries']),2);self.assertEqual(len(objects),1)

    def test_sqlite_live_wal_backup_and_no_change_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbfile=Path(tmp)/'panel.db';config=Path(tmp)/'telemt.toml';config.write_text('users = 3')
            with sqlite3.connect(dbfile) as db:
                db.execute('pragma journal_mode=wal');db.execute('create table counters(value)');db.execute('insert into counters values(7)');db.commit()
                paths={'/etc/telemt/telemt.toml':config,store.DATABASE:dbfile}
                with patch.object(store,'source_paths',return_value=paths):
                    a=store.capture('state');b=store.capture('state')
                    self.assertEqual(a[2:],b[2:])
                    db.execute('update counters set value=8');db.commit()
                    c=store.capture('state');self.assertNotEqual(a[2],c[2]);self.assertEqual(a[3],c[3])
                    config.write_text('users = 4');d=store.capture('state');self.assertNotEqual(c[3],d[3])
                copied=Path(tmp)/'copy.db';copied.write_bytes(store.database_copy(dbfile)[0])
                with sqlite3.connect(copied) as restored:self.assertEqual(restored.execute('select value from counters').fetchone()[0],8)

if __name__=='__main__':unittest.main()
