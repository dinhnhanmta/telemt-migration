# Mặc định tạo user Telemt Web

Bản đang dùng: `1.0.0-rc.3-pinpin.1`, dựa trên
[`amirotin/telemt_panel` v1.0.0-rc.3](https://github.com/amirotin/telemt_panel/tree/f872cfe46f1478785c1c4995488ff121797024d5).

- Form tạo mới điền sẵn **2 IP**; vẫn có thể đổi hoặc xóa giới hạn trước khi lưu.
- Secret được sinh tự động. Chỉ cần nhập tên và chọn ngày hết hạn.
- Sau khi tạo, panel tự thêm Web profile **DD** vào vhost đầu tiên đang cấu hình. Hiện là `tg-ru.pinpinvpn.uk`, cổng Web vẫn là 443.
- Dùng revision mới sau khi tạo và `If-Match` khi ghi Web; xung đột được đọc lại và thử tối đa ba lần. Không sửa profile của user khác.
- Đợi runtime reload thành công trước khi báo Web sẵn sàng. Nếu bước Web lỗi sau khi user đã tồn tại, vẫn giữ và hiển thị secret, báo cần hoàn tất Web; không tự tạo lại user.
- Đây là mặc định của **form tạo user trên panel**. API tạo user và luồng sửa user có sẵn giữ hành vi upstream.

Binary panel và helper đã được hệ thống backup lưu mã hóa. Khôi phục bằng `install.sh` như trước sẽ giữ tính năng này, không cần build trên VPS mới. Cập nhật panel bằng bản upstream sẽ thay binary tùy chỉnh; khi đó cần áp dụng lại patch.

## Build lại khi cần

Yêu cầu Go 1.27.x, Node 24 và npm. Checkout đúng commit phía trên, tải `source.patch` trong thư mục này rồi chạy tại thư mục repo upstream:

```bash
git apply --check /path/to/source.patch
git apply /path/to/source.patch
cd web
npm ci
npm test -- src/people/createUserWithWeb.test.ts src/people/UserFormSheet.test.tsx src/people/connectionLinks.test.ts src/i18n/i18n.test.ts
npm run build
cd ..
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags='-s -w -X main.version=1.0.0-rc.3-pinpin.1' -o telemt-panel ./cmd/panel
```

Đã kiểm tra 94 test frontend và thử bằng trình duyệt thật với binary Linux: chỉ nhập tên/ngày hết hạn, xác nhận giới hạn 2 IP, Web profile DD đã áp dụng, profile cũ không đổi và xóa sạch tài khoản thử. Khi triển khai chỉ khởi động lại panel quản trị; tiến trình Telemt và Caddy giữ nguyên.

Các thay đổi `.tsx` ở hai import chỉ giúp build được trên filesystem Windows. Giấy phép upstream được giữ tại `LICENSE.upstream`.
