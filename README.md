# Telemt Web + Panel + Caddy recovery

Panel đang có [mặc định tạo user Web với 2 IP](panel-customization/README.md). Binary tùy chỉnh được lưu trong gói cố định mã hóa; phục hồi sẽ giữ tính năng này.

Khôi phục **đúng binary, systemd service, khách/secret, cấu hình Web, database panel và bộ nhớ chứng chỉ Caddy** của máy đã sao lưu. Không chạy installer Telemt upstream và không tự mở cổng MTProxy công khai. Không chứa AWG, LucX hoặc Xray.

## Một lệnh khi chuyển VPS

Trên VPS **Ubuntu24.04 amd64 mới**, đăng nhập root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/dinhnhanmta/telemt-migration/main/install.sh)
```

Nhập **mật khẩu khôi phục riêng** (dùng cùng mật khẩu bộ AWG đã được chủ repo lưu). Khi báo RESTORED, kiểm tra dịch vụ trên IP mới rồi đổi bản ghi A trên Cloudflare, giữ nguyên domain và cổng443. Chế độ DNS giữ như máy cũ; không tự bật Cloudflare proxy nếu chưa kiểm tra tương thích Telemt Web.

Khách đang dùng domain giữ nguyên secret và đường dẫn kết nối. Kết nối TCP đang mở không thể chuyển nguyên phiên sang IP khác: giữ VPS cũ chạy trong lúc DNS cập nhật, tránh chỉnh khách trên panel cũ khi chuyển, và khách có thể cần kết nối lại. Cấu hình khách ghi IP cũ trực tiếp không được sửa chỉ bằng DNS.

## Những gì được lưu

- **Phần cố định:** Telemt, Panel, privileged helper, Caddy, web-manager, service/drop-in, tài khoản service và khóa ghi repo giới hạn cho repo này. Binary Panel trùng nội dung được lưu một lần trong gói.
- **Phần thay đổi:** cấu hình/secret khách, panel config, SQLite được sao lưu bằng Online Backup API, dữ liệu panel, cache cần thiết và Caddy data/config chứa chứng chỉ, private key và tài khoản ACME.
- Mọi dữ liệu trên được **mã hóa AES-256-GCM, khóa từ scrypt** trước khi tải lên nhánh `backups`. Mật khẩu, bot token và khóa riêng không có trong mã công khai. Bot token nằm trong phần cố định được mã hóa.

Gói cố định chỉ tải lại khi binary/service hoặc thông tin cố định đổi. Các bản dữ liệu khách không chứa lại binary. Giữ snapshot hiện tại và snapshot liền trước trong cây nhánh backup; Git còn lưu lịch sử commit.

## Tự sao lưu

File-watch phát hiện thay đổi cấu hình; timer kiểm tra bổ sung mỗi phút. Thay đổi khách/secret, cấu hình, passkey và cài đặt panel, chứng chỉ Caddy, binary hay service mới tạo snapshot tự động. Cache TLS/proxy của Telemt, phiên đăng nhập, lịch sử hoạt động và bộ đếm SQLite không tự kích hoạt backup; chúng vẫn có thể nằm trong gói đã mã hóa khi có thay đổi cần lưu. Khi phục hồi, panel giữ tài khoản/passkey nhưng bỏ phiên đăng nhập cũ, vì vậy hãy đăng nhập lại. Nếu chỉ mở panel hoặc cache tự làm mới, không có snapshot hay tin Telegram mới.

Snapshot mã hóa được đẩy lên GitHub và gửi dưới dạng tài liệu qua bot Telegram đã cấu hình. Mỗi gói cố định chỉ gửi khi nó đổi. Telegram lỗi sẽ giữ hàng đợi và thử lại; bản GitHub đã thành công vẫn được giữ.

```bash
telemt-backup --force
systemctl status telemt-migration-backup.timer telemt-migration-backup.path
journalctl -u telemt-migration-backup.service -n 30 --no-pager
```

`--force` là lệnh thủ công, lấy cả thay đổi SQLite và thời điểm hoạt động của phiên, chỉ tạo snapshot nếu dữ liệu thực sự khác. Chạy lệnh này ngay trước khi chuyển VPS để lấy bộ đếm mới nhất.

Sau khi phục hồi và kiểm tra thành công, VPS mới nhận quyền làm nguồn backup. VPS cũ thấy quyền đã chuyển sẽ ngừng ghi backup, nhưng **tiếp tục phục vụ khách**, tránh máy cũ ghi đè dữ liệu mới. Nếu dữ liệu nguồn đổi đúng lúc phục hồi, bộ cài dừng chuyển quyền và yêu cầu chạy lại trước khi đổi DNS.

## Kiểm tra mà chưa phục hồi

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/dinhnhanmta/telemt-migration/main/install.sh) --dry-run
bash <(curl -fsSL https://raw.githubusercontent.com/dinhnhanmta/telemt-migration/main/install.sh) --stage-dir /root/telemt-recovery-check
```

Gói được xác thực, kiểm tra SHA256/đường dẫn, database và cặp chứng chỉ/khóa trước khi ghi vào vị trí ứng dụng. Bộ cài từ chối ghi đè dịch vụ có sẵn trên VPS không thuộc bộ phục hồi này. Cần cho phép TCP80/443 ở firewall nhà cung cấp; backend và panel giữ listen localhost như bản sao lưu.

Chương trình backup chạy trực tiếp trên Linux bằng systemd, không phụ thuộc việc mở Codex. Giữ mật khẩu khôi phục ngoài VPS và GitHub. Chưa coi việc kiểm tra giải mã/staging là chứng nhận không gián đoạn trên mọi VPS mới; cần kiểm tra IP mới trước khi ngừng máy cũ.
