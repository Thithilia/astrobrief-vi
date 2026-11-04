# Kiểm tra triển khai vận hành v2 — 04/11/2026

## Đã kiểm tra

- 84 kiểm thử Python đạt. Gồm kho giả lập 35 bài phát hành trong 7 ngày, trần 5/ngày, chống trùng, nguồn không truy cập được ở hơn một lô, quota giữa chừng, fingerprint, chặn Markdown chưa duyệt và bảo toàn cập nhật remote khi Git push đồng thời.
- Astro check: 0 lỗi, 0 cảnh báo, 0 gợi ý. Build trước lần phát hành đầu tạo 21 trang; bài trong `content/ready` chưa xuất hiện trong trang đọc.
- Đối soát 17 summary cũ với catalog và các trang công khai trước chuyển đổi. Giữ ngày cũ với độ chính xác ngày; không suy đoán giờ phát hành lịch sử.
- Tác vụ Windows Collect và Daily đã đăng ký lại, bật và chạy mã v2. Daily sản xuất kho, không ghi trực tiếp bài mới vào vùng công khai.
- Worker thật đã duyệt DOI `10.1051/0004-6361/202662789`, tạo kho kèm hash nội dung và bằng chứng kiểm tra nguồn.
- GitHub Actions [41818004898](https://github.com/Thithilia/astrobrief-vi/actions/runs/41818004898) hoàn tất thành công: giữ chỗ, build, deploy, xác minh catalog/route/hash, ghi sổ và triển khai trạng thái đã xác nhận.
- Sau lượt đó, website có 18 summary, gồm 2 bài ngày 04/11. Bài mới trả HTTP 200 và đúng hash `eaf4fc53f9ce346ddaf9557d63f72af549459057f4ef95792ecb4082ddd60795`.
- Trên viewport 390 × 844: trang chính hiện đúng `2/5`, dự phòng `0/35`; trang bài có 6 phần và đúng marker phiên bản; cả hai không tràn ngang. Nền trắng đã được kiểm tra trực tiếp.
- Bộ tìm nguồn chạy thực tế, phát hiện thêm 13 DOI có bản ghi kho trường/viện và kiểm tra được 13 toàn văn sẵn sàng trong lượt đầu. Chi tiết và số thay đổi tiếp tục lưu tại SQLite, không tính số này là summary đã duyệt.

## Đang vận hành để đo tiếp

Worker tiếp tục viết, kiểm tra và đồng bộ bài đã duyệt; GitHub tự điền các chỗ còn thiếu của ngày và giữ trần 5. Kho 35 là mục tiêu, chưa phải số dự phòng đã có ở lần kiểm tra trên.

Chưa có 7 ngày vận hành thực tế của v2. Lịch sử được lưu ở `public/data/editions.json`, số bài công khai ở `public/data/releases.json`, trạng thái hiện tại ở `public/data/health.json`. Số bài được duyệt mới, lượt gọi, thời gian, token và lỗi lưu tại các bảng `editorial_items`/`editorial_attempts` trong SQLite. Dùng các số này để đánh giá khả năng bổ sung ít nhất 5 bài/ngày với cấu hình Codex hiện tại.

Không coi kiểm thử 7 ngày giả lập là 7 ngày hoạt động thực tế. Không coi một ngày đủ 5 là bằng chứng đã có kho 35 hoặc năng lực tạo 35 bài mới mỗi tuần.
