# Kiểm tra bản khởi tạo — 26/10/2026

Đã thu thập 1.553 article từ sáu journal trong đợt khởi tạo 30 ngày, tạo năm bài giải thích tiếng Việt và sáu hình CC BY. Mỗi bài có khoảng sáu phút đọc theo tốc độ 220 từ cách nhau bằng khoảng trắng mỗi phút.

| DOI | Toàn văn thực tế đã đọc | Hình công khai |
| --- | --- | --- |
| 10.3847/1538-3881/ae9d73 | Bản xuất bản AJ trong kho Caltech | Hình 1–2, CC BY 4.0 |
| 10.3847/1538-4357/ae9d7c | arXiv 2608.16787v2, DOI được xác nhận trong metadata arXiv | Không có |
| 10.3847/1538-4357/ae91e7 | Bản xuất bản ApJ trong kho LJMU | Hình 1–2, CC BY 4.0 |
| 10.3847/1538-4357/ae9869 | arXiv 2609.36697v1 | Hình 1–2, CC BY 4.0 |
| 10.1051/0004-6361/202558662 | arXiv 2608.06017v1, DOI được xác nhận trong bản ghi arXiv | Không có |

Năm bản nháp và năm lượt kiểm tra nguồn cuối cùng đều chạy bằng Codex CLI đăng nhập ChatGPT, giữ model `gpt-6.1-sol` và reasoning `xhigh`. Bằng chứng riêng của mỗi bài gồm trích dẫn nguyên văn, nhãn đoạn/trang và kết quả duyệt. Các bản nháp có lỗi được sửa rồi kiểm tra lại. Hai nguồn không xác định được quyền tái sử dụng hình chỉ cung cấp liên kết toàn văn.

Các kiểm tra đã thực hiện:

- `python -m pytest -q`: **52 passed**. Bao gồm RSS namespace và thứ tự, DOI trùng, Crossref đăng ký muộn, ngày online khác ngày issue, thiếu toàn văn, sai DOI, số liệu không được nguồn hỗ trợ, hình chưa có quyền, gián đoạn ghi, quota, chạy lại, export đồng thời và thu thập bù trước khi chọn bài lúc 07:00.
- Chạy lại phiên thực tế sau khi đủ năm bài: `created=0`, `total_today=5`.
- Codex CLI được tìm thấy và xác nhận đăng nhập ChatGPT khi bỏ PATH của phiên ứng dụng; tác vụ định giờ không phụ thuộc PATH do cửa sổ Codex thêm vào.
- `npm run check`: **0 lỗi, 0 cảnh báo, 0 gợi ý**. `npm run build`: **9 trang**, gồm năm trang summary.
- Kiểm tra trình duyệt ở desktop và chiều rộng 390 px: không tràn ngang; hình và font tải được; mục lục và neo nguồn hoạt động; không có lỗi trình duyệt.
- Tìm kiếm bằng cụm chỉ có trong thân summary trả đúng bài. Kiểm tra đường dẫn và tài nguyên với tiền tố `/astrobrief-vi/`: không có đường dẫn nội bộ hỏng.
- GitHub Actions triển khai Pages thành công. Trang chính, catalog JSON, năm trang summary và sáu hình công khai đều trả HTTP 200. Kiểm tra trình duyệt trên website công khai: tìm kiếm và bộ lọc hoạt động; 22 yêu cầu trang/CSS/font/hình đều trả HTTP 200, không có lỗi hay cảnh báo trình duyệt.
- Đã đăng ký và xác nhận hai tác vụ Windows `AstroBriefVi-Collect` và `AstroBriefVi-Daily` ở trạng thái Ready, quyền Limited và LogonType Interactive; lặp hằng giờ và chạy bù khi đăng nhập. Phiên summary áp dụng mốc 07:00 và giới hạn năm bài theo giờ Việt Nam.

Toàn văn, nhật ký Codex, bằng chứng duyệt và SQLite được lưu trong `.local/` ở máy quản trị. Dữ liệu công khai là catalog JSON, summary Markdown và các hình được phép tái sử dụng.
