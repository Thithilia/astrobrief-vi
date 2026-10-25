# AstroBrief Việt

Theo dõi **A&A, ApJ, ApJL, ApJS, AJ và MNRAS**, giải thích tối đa năm bài mỗi ngày bằng tiếng Việt cho sinh viên vật lý và thiên văn.

Web đọc công khai: **https://thithilia.github.io/astrobrief-vi/**. Việc tạo nội dung chạy trên máy Windows của người quản trị bằng Codex CLI đăng nhập ChatGPT. GitHub Pages phục vụ nội dung đã tạo ngay cả khi máy này tắt.

## Cài đặt

Yêu cầu Node.js 24, Python 3.11+, Git, Codex CLI đã đăng nhập ChatGPT, và Git Credential Manager đăng nhập GitHub tài khoản `Thithilia`. Không cần OpenAI API key. `scripts/setup.ps1` tạo môi trường Python và cài dependencies.

```powershell
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m pipeline collect --days 30
.\.venv\Scripts\python.exe -m pipeline daily
npm.cmd run check
npm.cmd run build
```

## Công cụ quản trị

```powershell
.\.venv\Scripts\python.exe -m pipeline status
.\.venv\Scripts\python.exe -m pipeline collect
.\.venv\Scripts\python.exe -m pipeline daily --catch-up
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

## Lịch chạy

Hai tác vụ `AstroBriefVi-Collect` và `AstroBriefVi-Daily` chạy nền hằng giờ và khi đăng nhập Windows. Thu thập đọc các feed và đối chiếu Crossref. Phiên hằng ngày bắt đầu từ **07:00 Asia/Saigon**, có tối đa năm bài được tạo trong ngày; lần gọi lại sau đó tiếp tục công việc còn dở hoặc kết thúc nhanh nếu đủ năm bài. Tác vụ chạy dưới tài khoản hiện tại, không lưu mật khẩu Windows và không thay đổi cài đặt nguồn điện.

Máy tắt hoặc mất mạng: website vẫn giữ bản gần nhất. Khi máy hoạt động trở lại, metadata được bù từ checkpoint; bài được phát hiện muộn không bị loại khỏi hàng đợi chỉ vì đã qua ngày xuất bản. Codex hết hạn mức sẽ chờ lần chạy tiếp theo. Trạng thái đọc được bằng lệnh `status`; chi tiết nằm trong `.local/logs` và `.local/runs`.

## Quy trình biên tập

1. DOI chuẩn hóa là khóa nhận diện. Ngày online, ngày ghi trên issue, ngày phát hiện và ngày summary được giữ riêng.
2. AI xếp hạng ứng viên theo câu hỏi khoa học, kết quả cụ thể, bằng chứng và sự đa dạng chủ đề.
3. Đọc toàn văn publisher, gồm bản xuất bản chính thức được lưu ở kho trường/viện khi xác nhận được DOI ở trang đầu; nếu không tải được thì tìm bản arXiv khớp DOI, giữ đúng ID và phiên bản. Không biến abstract thành một bài giải thích toàn văn.
4. Viết bài tiếng Việt có thuật ngữ tiếng Anh ở lần đầu, các đối chiếu kết quả với vị trí trong nguồn, và nhãn **Tổng hợp tự động bằng Codex**.
5. Một lượt Codex riêng kiểm tra số liệu, đơn vị, kết luận, giả thiết và hình. Các bằng chứng được kiểm tra khớp văn bản trước khi xuất bản. Bài chưa đạt được giữ để sửa, chuyển sang ứng viên tiếp theo.

Các render nguyên trang PDF chỉ dùng nội bộ để đọc hình. Hình đưa lên web phải có quyền sử dụng, credit và vị trí nguồn rõ ràng; không xác định được quyền thì chỉ dẫn tới bài gốc. Cấu trúc giải thích tham khảo [Astrobites](https://astrobites.org/apply-to-write-for-astrobites/); văn bản được viết độc lập từ nghiên cứu gốc.

## Dữ liệu và kiểm tra

- `public/data/catalog.json`: metadata và thông tin tóm tắt công khai, không chứa toàn văn hay credentials.
- `content/summaries/*.md`: bài đã kiểm tra, metadata YAML và nội dung Markdown.
- `.local/`: SQLite, toàn văn, cache, bản nháp, bằng chứng và nhật ký; được Git bỏ qua.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd run check
npm.cmd run build
.\scripts\install-tasks.ps1 -DryRun
```

Nguồn metadata là RSS các journal và [Crossref](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/). Feed bị giới hạn số mục; giao diện hiển thị lần đồng bộ thực tế, không gắn nhãn đã bao phủ toàn bộ mọi bài trong ngày. Các phản hồi 429 được xử lý bằng backoff; 403/CAPTCHA không được coi là feed rỗng và không bị vượt qua.

Kết quả kiểm tra bản khởi tạo: [VALIDATION.md](VALIDATION.md).
