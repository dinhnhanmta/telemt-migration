#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
BASE_URL='https://raw.githubusercontent.com/dinhnhanmta/telemt-migration/v1.0.2'
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
22321afbfc7f911877ada29d61214482054bdd096afd698303bcdd689c84dcfc  store.py
435e248a43d106ce5f079ab96051c9f6e521313a7cb66ba80b066f3bc1c8bfd2  transport.py
c0d2fd8db3d591b713f73e4673f9b8360888ee019223f028f220c1c22c87ee20  backup.py
71c77cd115a6095f52a6bf0b872db45970e29b6e744f54536caf6206af75d36f  automation.py
31eca35b8407551a9130f8614a6122523562946dc09bae543b7ee25bd60539b9  restore.py
CHECKSUMS
(cd "$work_dir" && sha256sum -c SHA256SUMS)
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 "$work_dir/restore.py" "$@"
