"""Install local file watches plus a minute safety poll; no desktop scheduler required."""
from pathlib import Path
import subprocess

APP=Path('/usr/local/lib/telemt-migration')
SERVICE='''[Unit]
Description=Encrypted Telemt recovery backup to GitHub and Telegram
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
UMask=0077
Nice=15
IOSchedulingClass=idle
TimeoutStartSec=600
ExecStart=/usr/bin/python3 /usr/local/lib/telemt-migration/backup.py
'''
TIMER='''[Unit]
Description=Check Telemt recovery changes every minute
[Timer]
OnBootSec=2min
OnUnitInactiveSec=1min
AccuracySec=5s
Unit=telemt-migration-backup.service
[Install]
WantedBy=timers.target
'''
WATCH='''[Unit]
Description=Back up changes to Telemt users, configuration and Caddy
[Path]
PathChanged=/etc/telemt
PathChanged=/etc/telemt-panel
PathChanged=/etc/telemt-panel-privileged
PathChanged=/etc/caddy
PathChanged=/etc/sudoers.d/telemt-panel
PathChanged=/usr/bin/telemt
PathChanged=/usr/local/bin/telemt-panel
PathChanged=/usr/local/libexec/telemt-panel-privileged
PathChanged=/usr/bin/caddy
PathChanged=/etc/systemd/system/telemt.service
PathChanged=/etc/systemd/system/telemt-panel.service
PathChanged=/var/lib/caddy/.local/share/caddy
Unit=telemt-migration-backup.service
[Install]
WantedBy=multi-user.target
'''

def install(start=True):
    for name,content in [('service',SERVICE),('timer',TIMER),('path',WATCH)]:
        path=Path('/etc/systemd/system/telemt-migration-backup.'+name)
        if path.exists() and path.read_text()!=content:raise RuntimeError('Existing unrelated automation: '+str(path))
        path.write_text(content);path.chmod(0o644)
    wrapper=Path('/usr/local/sbin/telemt-backup')
    wrapper.write_text('#!/bin/sh\nexec /usr/bin/python3 /usr/local/lib/telemt-migration/backup.py "$@"\n');wrapper.chmod(0o700)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    if start:subprocess.run(['systemctl','enable','--now','telemt-migration-backup.timer','telemt-migration-backup.path'],check=True)
