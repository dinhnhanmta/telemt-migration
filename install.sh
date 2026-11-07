#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
BASE_URL='https://raw.githubusercontent.com/dinhnhanmta/telemt-migration/v1.0.0'
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
  echo 'Restore existing Telemt Web + Panel + Caddy binaries, services, customers and certificates.'
  echo 'Fresh Ubuntu24.04 amd64, root. Enter the recovery password; then update your DNS.'
  echo 'Options: --dry-run; --stage-dir /root/NEW_PRIVATE_DIRECTORY'
  exit 0
fi
[[ "$(uname -s)" == Linux && "$EUID" -eq 0 ]] || { echo 'Run as root on Ubuntu24.04 amd64.' >&2; exit 1; }
if ! command -v python3 >/dev/null || ! python3 -c 'import cryptography' 2>/dev/null || ! command -v curl >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l
  apt-get update -qq
  apt-get install -y --no-install-recommends python3 python3-cryptography curl ca-certificates
fi
work_dir=$(mktemp -d /root/telemt-bootstrap.XXXXXXXX)
cleanup() {
  rm -f -- "$work_dir/archive.py" "$work_dir/store.py" "$work_dir/transport.py" "$work_dir/backup.py" "$work_dir/automation.py" "$work_dir/restore.py" "$work_dir/SHA256SUMS"
  rmdir -- "$work_dir" 2>/dev/null || true
}
trap cleanup EXIT
for name in archive.py store.py transport.py backup.py automation.py restore.py; do
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 15 --max-time 90 "$BASE_URL/$name" -o "$work_dir/$name"
done
cat > "$work_dir/SHA256SUMS" <<'CHECKSUMS'
0d75612a483640cda6419299a19a564c6de60b78548891044086088acddb9c06  archive.py
2ec3996763c861a6719ef36f9e97108a5770227a93243cd8e538248b4ff01b5f  store.py
435e248a43d106ce5f079ab96051c9f6e521313a7cb66ba80b066f3bc1c8bfd2  transport.py
bf4939ab6a472819d07270c0e56928ec53c86e00270c99507af8926cf801c78e  backup.py
71c77cd115a6095f52a6bf0b872db45970e29b6e744f54536caf6206af75d36f  automation.py
ae7c29dc5d4cdc301b9da6a6053de19906ec5b7faf9c228bc6409991235bd668  restore.py
CHECKSUMS
(cd "$work_dir" && sha256sum -c SHA256SUMS)
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 "$work_dir/restore.py" "$@"
