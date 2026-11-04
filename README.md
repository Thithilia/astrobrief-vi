# AstroBrief Việt

Theo dõi **A&A, ApJ, ApJL, ApJS, AJ và MNRAS**, giải thích tối đa năm bài mỗi ngày bằng tiếng Việt cho sinh viên vật lý và thiên văn.

Web đọc công khai: **https://thithilia.github.io/astrobrief-vi/**. Việc tạo nội dung chạy trên máy Windows của người quản trị bằng Codex CLI đăng nhập ChatGPT. GitHub Pages phục vụ nội dung đã tạo ngay cả khi máy này tắt.

Hệ thống v2 tách sản xuất tại Windows khỏi phát hành trên GitHub: hàng đợi xuyên ngày, kho mục tiêu 35 bài đã duyệt, sổ phát hành xác nhận từ website và trạng thái thực tế `0–5/5`. Đặc tả và tiêu chí nghiệm thu: [OPERATIONS_DESIGN.md](OPERATIONS_DESIGN.md). Con số 35 là mục tiêu kho, không phải lượng bài đang có; xem trạng thái hiện tại trên trang chính hoặc bằng lệnh `status`.

## Cài đặt

Yêu cầu Node.js 24, Python 3.11+, Git, Codex CLI đã đăng nhập ChatGPT, và Git Credential Manager đăng nhập GitHub tài khoản `Thithilia`. Không cần OpenAI API key. `scripts/setup.ps1` tạo môi trường Python và cài dependencies.

```powershell
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m pipeline collect --days 30
.\.venv\Scripts\python.exe -m pipeline prepare-sources --target 30
.\.venv\Scripts\python.exe -m pipeline produce --target 35 --publish
npm.cmd run check
npm.cmd run build
```

## Công cụ quản trị

```powershell
.\.venv\Scripts\python.exe -m pipeline status
.\.venv\Scripts\python.exe -m pipeline collect
.\.venv\Scripts\python.exe -m pipeline prepare-sources --target 30 --budget-minutes 10
.\.venv\Scripts\python.exe -m pipeline produce --target 35 --max-items 5 --budget-minutes 120 --publish
.\.venv\Scripts\python.exe -m pipeline reconcile
.\.venv\Scripts\python.exe -m pipeline export
.\.venv\Scripts\python.exe -m pipeline publish
.\.venv\Scripts\python.exe -m pipeline deployment-status
```

Thiết lập repository công khai và Pages lần đầu sau khi kiểm tra nội dung:

```powershell
.\.venv\Scripts\python.exe -m pipeline init-github
.\.venv\Scripts\python.exe -m pipeline publish --bootstrap
.\.venv\Scripts\python.exe -m pipeline enable-pages
.\scripts\install-tasks.ps1
```

Git Credential Manager cung cấp xác thực qua bộ nhớ tiến trình; token không được lưu vào mã nguồn, đầu ra hay nhật ký. Publisher chỉ dùng Git push bình thường, không force-push hay tự ghi đè thay đổi trên remote. Có thể dùng GitHub CLI đăng nhập qua trình duyệt nếu máy chưa có xác thực Git.

Với v2, `publish` chỉ đồng bộ metadata, bài đã duyệt và hình được phép dùng từ một checkout tạm của remote mới nhất; không sửa branch/index hoặc đưa thay đổi mã nguồn đang làm dở lên GitHub. `daily --limit 1` là lệnh tương thích để chuẩn bị tối đa một bài; nó không có nghĩa đã hoàn thành phiên phát hành 5 bài. Mã thoát 2 nghĩa ngày còn thiếu bài, 1 là lỗi vận hành, 0 là đã đạt điều kiện lệnh/ngày tương ứng. `status` luôn lấy số công khai từ sổ phát hành.

## Lịch chạy

Hai tác vụ `AstroBriefVi-Collect` và `AstroBriefVi-Daily` chạy nền hằng giờ và khi đăng nhập Windows. Collect đồng bộ RSS/Crossref và chuẩn bị toàn văn; Daily chạy worker sản xuất kho, kể cả trước 07:00. Mỗi lượt sản xuất tối đa 5 bài hoặc 120 phút rồi giữ checkpoint; các lượt tiếp theo tiếp tục đến mục tiêu kho 35. Tác vụ chạy khi tài khoản Windows hiện tại đã đăng nhập, kể cả lúc khóa màn hình; không lưu mật khẩu Windows và không thay đổi cài đặt nguồn điện.

GitHub Actions phát hành từ **07:00 Asia/Saigon**, có lượt bù ở phút 17 và 47 mỗi giờ, chốt ngày lúc 23:30. Lịch có thể trễ; các lượt sau đối soát sổ và chỉ điền chỗ còn thiếu, không vượt 5. Actions chỉ dùng bài đã duyệt, không gọi Codex. Tạo file/commit/push chưa được tính là phát hành; cần xác minh deployment, DOI và hash trên từng trang công khai. Chỉ khi đủ 5 bài xác nhận mới báo `complete`.

Máy tắt hoặc Codex hết hạn mức: GitHub vẫn phát hành nếu còn đủ bài đã duyệt được đồng bộ. Hết kho thì báo đúng số thiếu. Khi máy hoạt động lại, worker tiếp tục bản nháp cũ, không đặt lại số lượt sửa chỉ vì sang ngày mới. Trạng thái đọc được trên trang chính hoặc lệnh `status`; chi tiết riêng nằm trong `.local/logs`, `.local/editorial` và SQLite. Không gửi email/Slack tự động.

## Quy trình biên tập

1. DOI chuẩn hóa là khóa nhận diện. Ngày online, ngày ghi trên issue, ngày phát hiện và ngày summary được giữ riêng.
2. AI xếp hạng ứng viên theo câu hỏi khoa học, kết quả cụ thể, bằng chứng và sự đa dạng chủ đề.
3. Đọc toàn văn publisher, gồm bản xuất bản chính thức được lưu ở kho trường/viện khi xác nhận được DOI ở trang đầu; nếu không tải được thì tìm bản arXiv khớp DOI, giữ đúng ID và phiên bản. Không biến abstract thành một bài giải thích toàn văn.
4. Viết bài tiếng Việt có thuật ngữ tiếng Anh ở lần đầu, các đối chiếu kết quả với vị trí trong nguồn, và nhãn **Tổng hợp tự động bằng Codex**.
5. Một lượt Codex riêng kiểm tra số liệu, đơn vị, kết luận, giả thiết và hình. Các bằng chứng được kiểm tra khớp văn bản trước khi xuất bản. Khi có lỗi, Codex sửa từng đoạn trên bản nháp hiện có bằng các phép thay thế chính xác; phần còn lại và các trích dẫn không bị viết lại. Mỗi thay đổi đều được kiểm tra lại với nguồn. Tối đa ba lượt sửa tự động cho một phiên bản bản nháp, lưu xuyên ngày. Khi chưa đạt, giữ lỗi và chuyển sang ứng viên tiếp theo; lô 15 ứng viên chỉ là kích thước lựa chọn, không phải giới hạn toàn phiên.
6. Bài đã duyệt vào kho, chưa gán ngày phát hành. GitHub giữ chỗ theo ngày, build, deploy, kiểm tra phiên bản công khai rồi ghi sổ. Lần chạy bị ngắt khôi phục cùng bộ bài; deployment qua nửa đêm lấy ngày thực tế, không lùi ngày để che số thiếu.

Các render nguyên trang PDF chỉ dùng nội bộ để đọc hình. Hình đưa lên web phải có quyền sử dụng, credit và vị trí nguồn rõ ràng; không xác định được quyền thì chỉ dẫn tới bài gốc. Cấu trúc giải thích tham khảo [Astrobites](https://astrobites.org/apply-to-write-for-astrobites/); văn bản được viết độc lập từ nghiên cứu gốc.

## Dữ liệu và kiểm tra

- `public/data/catalog.json`: metadata và thông tin tóm tắt công khai, không chứa toàn văn hay credentials.
- `content/summaries/*.md`: bài đã kiểm tra, metadata YAML và nội dung Markdown.
- `content/ready/*.json`: bài đã duyệt chưa hoặc đã phát hành; không nằm trong trang đọc trước khi được chọn phát hành. Repo công khai nên nội dung kho có thể xem qua repo.
- `public/data/releases.json`: sổ bài đã xác nhận công khai; `release-state.json`: chỗ đang giữ khi deployment; `health.json`: tiến độ và số thiếu; `editions.json`: lịch sử ngày đạt/thiếu.
- `.local/`: SQLite, toàn văn, cache, bản nháp, bằng chứng và nhật ký; được Git bỏ qua.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd run check
npm.cmd run build
.\scripts\install-tasks.ps1 -DryRun
```

Nguồn metadata là RSS các journal và [Crossref](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/). Feed bị giới hạn số mục; giao diện hiển thị lần đồng bộ thực tế, không gắn nhãn đã bao phủ toàn bộ mọi bài trong ngày. Các phản hồi 429 được xử lý bằng backoff; 403/CAPTCHA không được coi là feed rỗng và không bị vượt qua.

Kết quả kiểm tra bản khởi tạo: [VALIDATION.md](VALIDATION.md).
