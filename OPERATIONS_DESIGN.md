# AstroBrief Việt — yêu cầu thiết kế vận hành 5 summary/ngày

Ngày thiết kế: 04/11/2026. Trạng thái: **đã có mã triển khai v2; đang kiểm tra triển khai thực tế**. Tài liệu này ghi yêu cầu nghiệm thu; kiểm thử giả lập không thay thế 7 ngày quan sát vận hành và không chứng minh kho đã có đủ 35 bài.

## 1. Đầu ra phải đo được

- Một ngày tính theo `Asia/Saigon`, từ 00:00 đến trước 00:00 hôm sau. Mỗi ngày phát hành **5 summary khác DOI**, không vượt 5 và không lặp lại bài đã phát hành trước đó.
- Bắt đầu phát hành từ 07:00. Mốc chốt mặc định của thiết kế là **23:30**; đây là thời gian dành cho hoàn tất và đối soát, không phải cam kết phát hành đúng phút 07:00.
- Một bài chỉ được tính là đã phát hành khi deployment GitHub Pages thành công và website công khai chứa đúng ID, DOI và phiên bản nội dung của bài. Tạo Markdown, lưu SQLite, commit hoặc push đều chưa đủ điều kiện này.
- `complete` của ngày chỉ có nghĩa `published_count == 5`. Lệnh thử một bài có thể hoàn thành yêu cầu của lệnh, nhưng không được làm ngày thành `complete` khi mới có `1/5`.
- Bài nghiên cứu và Letters được ưu tiên. Bài trong hàng đợi từ ngày trước được dùng khi cần; luôn hiển thị đúng ngày online, ngày phát hiện, ngày viết và ngày phát hành. Không gọi bài cũ là bài mới đăng hôm nay.
- Giữ nguyên yêu cầu tiếng Việt, thuật ngữ Anh ở lần đầu, cấu trúc giải thích, đọc toàn văn, kiểm tra độc lập và quyền sử dụng hình. Không hạ tiêu chuẩn để đủ số lượng.

## 2. Những điểm phải thay trong hệ thống hiện tại

Đối chiếu mã và SQLite ngày 04/11/2026:

| Hiện tại | Yêu cầu mới |
| --- | --- |
| `daily --limit 1` có thể lưu báo cáo `complete`, dù ngày mới có một summary | Tách kết quả một lệnh khỏi tình trạng hoàn thành ngày; chỉ sổ phát hành công khai quyết định `5/5` |
| SQLite lưu summary và tăng bộ đếm trước khi push/deploy | Tách bài đã duyệt, bài đang phát hành và bài đã xác nhận công khai |
| Lựa chọn tối đa 15 ứng viên trong mỗi lượt | Giới hạn 15 chỉ là kích thước một lô; hết lô phải lấy lô tiếp nếu còn thiếu và còn thời gian/tài nguyên |
| Thu thập metadata trước khi viết có thể chặn cả phiên `daily` | Thu thập, chuẩn bị nguồn, viết và phát hành là các công việc độc lập |
| Bài thiếu toàn văn bị loại đến hết ngày | Phân loại lỗi, lưu từng lần thử và có `next_retry_at`; thử lại khi đến hạn hoặc có nguồn thay thế mới |
| Trạng thái bản nháp gắn với ngày chạy | Hàng đợi bài và phiên bản bản nháp tồn tại qua nhiều ngày; ngày phát hành là thực thể riêng |
| GitHub Actions chỉ build khi máy đã đẩy nội dung mới | Actions có thể phát hành bài đã duyệt trong kho dự phòng mà không cần Codex hay máy Windows |
| Lỗi quota/phiên viết có thể kết thúc CLI với mã 0 | Phân biệt rõ thành công, còn thiếu, đang chờ phụ thuộc và lỗi; ngày thiếu bài không được báo thành công |

## 3. Hai luồng độc lập

### Chuẩn bị bài tại Windows

`Metadata → tìm toàn văn → xác nhận DOI/phiên bản → chọn theo giá trị khoa học → viết → kiểm tra → sửa từng đoạn → duyệt → đồng bộ kho dự phòng`

Python, SQLite, PDF/cache và Codex đăng nhập ChatGPT tiếp tục ở máy hiện tại. Giữ mô hình và mức reasoning đang cấu hình; không chuyển sang API trả phí. Việc viết được phép chạy trước ngày phát hành và không bị giới hạn bởi trần phát hành 5 bài/ngày.

### Phát hành trên GitHub

`Kho bài đã duyệt → chọn các chỗ còn thiếu của ngày → dựng website → triển khai Pages → kiểm tra công khai → xác nhận số bài đã phát hành`

Luồng này không gọi Codex, không cần đăng nhập ChatGPT và không lấy PDF. Khi máy Windows tắt hoặc Codex hết hạn mức, nó vẫn dùng được những bài đã duyệt và đồng bộ trước đó.

Bản summary đã duyệt đặt trong vùng riêng của repo, dự kiến `content/ready/`, chưa được Astro đưa vào trang đọc hay catalog. Vì repository công khai, nội dung dự phòng có thể được đọc qua repo trước ngày lên website. Chỉ đẩy văn bản đã duyệt, metadata, dấu kiểm tra và hình có quyền sử dụng; không đẩy bản nháp chưa duyệt, PDF, trích xuất toàn văn, credentials, SQLite hay nhật ký riêng.

## 4. Kho dự phòng và năng lực tạo bài

Các mức dưới đây là cấu hình ban đầu của thiết kế, cần đo lại trong giai đoạn nghiệm thu:

| Kho | Mức yêu cầu |
| --- | --- |
| Ứng viên có toàn văn đã xác minh, chưa có summary | Mục tiêu ít nhất 30 bài, có nhiều chủ đề khi nguồn cho phép |
| Summary đã duyệt và đã đồng bộ lên GitHub, chưa phát hành/chưa đặt chỗ | Mục tiêu 35 bài, tương đương 7 ngày phát hành |
| Kho đã duyệt còn dưới 10 bài | Cảnh báo thiếu dự phòng; ưu tiên bổ sung trước các công việc không thiết yếu |
| Kho đã duyệt còn dưới 5 bài | Báo nguy cơ không đủ một ngày; tiếp tục sản xuất và hiển thị số còn thiếu |

Chọn mức 35 để có khoảng dự phòng dài hơn đợt không tạo được summary từ cuối 29/10 đến 03/11 đã quan sát. Đây là dung lượng thiết kế, không phải số bài dự phòng hiện có.

Kho ưu tiên bài gần đây, nhưng không tự xóa bài được phát hiện muộn chỉ vì ngày online đã qua. Đa dạng chủ đề là ưu tiên mềm; không bắt buộc mỗi journal có một bài. Giữ tiêu chí lựa chọn khoa học 60/25/15 đã thống nhất.

Phải ghi thời gian, số lần gọi, token đầu vào/đầu ra, lượt sửa và nguyên nhân loại của từng bài. Năng lực dài hạn chỉ đạt khi tốc độ tạo **summary được duyệt mới** trung bình ít nhất 5/ngày; tăng kho dự phòng còn cần tốc độ cao hơn mức tiêu thụ. Nếu hạn mức của tài khoản với mô hình hiện tại không đáp ứng tốc độ đó, báo thiếu năng lực và số bài thiếu; kho dự phòng chỉ trì hoãn việc cạn bài.

## 5. Hàng đợi bền vững và điều phối

Mỗi DOI có một hồ sơ biên tập tồn tại qua các ngày:

`discovered → source_pending → source_ready → drafting → validating → reviewing → repairing → approved → reserved → deploying → published`

Các trạng thái chờ phải có mã nguyên nhân, thời điểm thử lại và công việc tiếp theo: `waiting_source`, `waiting_quota`, `waiting_auth`, `waiting_network`, `needs_attention`. Trạng thái chờ của một bài không khóa các bài khác.

- Chọn từ nguồn đã xác minh trước. Nếu chưa đủ, bộ tìm nguồn tiếp tục mở rộng hàng đợi; không dùng abstract thay toàn văn.
- Chỉ một worker viết/sửa tại một thời điểm trong cấu hình ban đầu để kiểm soát quota; thu thập và phát hành không giữ cùng khóa với worker này.
- Mỗi lượt worker có ngân sách thời gian. Hết ngân sách thì lưu checkpoint và lên lịch tiếp, không đánh dấu hoàn tất ngày.
- Tối đa ba lượt sửa tự động cho một phiên bản bản nháp. Hết lượt thì giữ lỗi để xử lý, chuyển ngay sang ứng viên khác. Không tạo lại toàn bài hoặc đặt lại bộ đếm chỉ vì sang ngày mới.
- Tiến độ gồm bản nháp hiện có, các patch, nguồn đã đọc, lỗi kiểm tra và fingerprint của lần duyệt. Khôi phục đúng bước sau mất điện, quota hoặc lỗi mạng.
- Không phụ thuộc file khóa còn sót. Công việc có chủ sở hữu, heartbeat và thời hạn giữ chỗ; công việc bị bỏ dở được thu hồi sau khi xác nhận worker cũ đã kết thúc. Không tạo hai worker cho cùng DOI/phiên bản.
- Nếu cả một lô 15 bài không đạt, xử lý lô kế tiếp. Chỉ kết thúc lượt vì đã đủ đầu ra, hết ngân sách lượt, hết ứng viên thực sự hoặc một phụ thuộc chung không thể dùng.

## 6. Nguồn và kiểm tra khoa học

- Chỉ `source_ready` khi toàn văn đầy đủ, DOI và phiên bản được xác nhận, checksum/cache còn hợp lệ. Cờ `complete: true` riêng lẻ không đủ.
- Ưu tiên publisher và bản xuất bản ở kho trường/viện; arXiv phải khớp DOI theo chứng cứ nhận diện đã quy định. Không vượt CAPTCHA/403.
- Lưu nguyên nhân từng URL: 403, 429, timeout, chỉ có abstract, PDF thiếu trang hoặc chưa xác nhận DOI. Không gộp tất cả thành một lỗi không có chi tiết.
- 429 tuân thủ thời gian chờ của nguồn; 403/CAPTCHA áp dụng cooldown và chuyển nguồn/ứng viên. Một nguồn thay thế mới được phép đánh thức lại công việc trước lịch thử cũ.
- Kiểm tra độ dài, thuật ngữ, link và trích dẫn trước khi gọi reviewer. Dấu bất đẳng thức phải được chấp nhận; HTML thực sự và link nguy hiểm bị chặn.
- Reviewer kiểm tra tuyên bố thực tế của summary với nguồn, gồm số liệu, giả thiết, phạm vi và hình; không yêu cầu summary chép mọi kết quả của bài gốc. Thiếu điều kiện làm đổi nghĩa kết luận phải bị giữ.
- Quote là nguyên văn nguồn, không dịch hoặc sửa số mũ trong quote để làm đẹp. Diễn giải số mũ trong thân bài phải đúng theo PDF/ngữ cảnh; khi trích xuất làm mất ký hiệu, kiểm tra trực tiếp trang gốc.
- Sửa bằng thay thế chính xác trên bản nháp hiện có; bảo toàn phần không bị đánh dấu. Không chép yêu cầu nội bộ như “cần kiểm tra Hình X” vào bài công khai; thực hiện kiểm tra đó hoặc bỏ tuyên bố quá cụ thể.
- Mọi thay đổi nội dung/nguồn/hình sau duyệt làm mất hiệu lực lần duyệt tương ứng. Chỉ bài vượt toàn bộ kiểm tra, gắn đúng fingerprint, mới vào kho phát hành.
- Hình chưa xác định quyền sử dụng được bỏ khỏi bài; thiếu hình không tự làm bài thiếu điều kiện nếu phần giải thích còn đầy đủ.

## 7. Ngày phát hành, chống trùng và nguồn trạng thái chính

Tách ít nhất các thực thể sau khi triển khai:

| Thực thể | Vai trò |
| --- | --- |
| `editorial_items` / `attempts` tại máy | Nguồn, bản nháp, phiên bản duyệt, checkpoint, lỗi, mức tiêu thụ và thời gian thử lại |
| `approved_inventory` trên GitHub | Danh sách nội dung đã duyệt được phép phát hành; ID/DOI, chủ đề, hash nội dung/nguồn/hình và bằng chứng duyệt đã lọc dữ liệu riêng |
| `editions` / `edition_slots` trên GitHub | Ngày dự kiến và tối đa 5 chỗ được giữ, tránh hai lượt đồng thời chọn cùng bài |
| `release_ledger` trên GitHub | Commit, deployment, ID/DOI, `published_at`, `verified_at`; nguồn chính cho số bài công khai |

Ngày và số bài công khai được tính từ sổ phát hành, không từ thời điểm viết hay lần chạy gần nhất. SQLite đồng bộ sổ này trước khi chuẩn bị/lựa chọn bài tiếp. Ngày đã công khai có tối đa 5 DOI; một DOI chỉ có một lần phát hành đầu tiên trên toàn website.

Giữ riêng `generated_at`, `reviewed_at`, `edition_date`, `published_at`, `verified_at`. `summary_date` công khai lấy ngày của deployment đã phát hành theo Asia/Saigon. Thời điểm kiểm tra lại một trang cũ không làm đổi ngày phát hành ban đầu.

Nếu deployment chậm qua nửa đêm, đối soát bài đó vào ngày thực tế phát hành và sửa metadata ngày tương ứng; không lùi ngày để che ngày thiếu bài. Không mở lượt phát hành mới khi lượt cũ chưa rõ kết quả; tính lại các chỗ còn trống trước lượt tiếp. Không đăng bù 10 bài hôm sau để gọi là đủ hai ngày.

Các thay đổi kho và sổ phát hành phải được tuần tự hóa, kiểm tra phiên bản remote trước khi ghi. Mất kết nối giữa commit/push/deploy/ghi sổ phải khôi phục cùng bản phát hành, không chọn một bộ bài mới. Không force-push hoặc ghi đè thay đổi mã nguồn của người dùng.

## 8. Lịch, phát hành và xác nhận

- Windows tiếp tục thu thập hằng giờ và khi đăng nhập. Worker sản xuất tiếp tục khi có nguồn/usage; ưu tiên thiếu hụt hôm nay, rồi bổ sung dự phòng.
- GitHub Actions thử phát hành từ 07:00; đề xuất các lượt kiểm tra bù lúc phút 17 và 47 mỗi giờ, đến mốc chốt. Mỗi lượt thoát nhanh khi đã đủ 5. Có `workflow_dispatch` để chạy thủ công hoặc Windows yêu cầu chạy bù.
- Mọi đường phát hành dùng chung cơ chế tuần tự hóa. Lượt đồng bộ metadata không được triển khai snapshot cũ làm mất những bài vừa phát hành.
- Kiểm tra checksum/bằng chứng duyệt, bộ đếm và DOI trước build; chạy Astro check/build; triển khai đúng snapshot; xác minh catalog và từng route mới bằng HTTP, DOI và hash phiên bản công khai.
- Tách lượt triển khai nội dung khỏi lượt cập nhật trạng thái sau xác nhận. Snapshot đầu hiển thị đang xác nhận; sau khi kiểm tra công khai thành công, ghi sổ và triển khai cập nhật trạng thái một lần. Lượt chỉ cập nhật trạng thái không dùng thêm chỗ, không làm đổi `published_at` và không tự lặp triển khai vô hạn. Hash phiên bản bài không gồm các trường trạng thái thay đổi sau phát hành.
- Pipeline phát hành phải trực tiếp chạy hoặc gọi bước build/deploy trong cùng chuỗi công việc. Không dựa vào một push bằng `GITHUB_TOKEN` để tự kích hoạt workflow Pages khác: GitHub nêu rõ các commit đó không kích hoạt Pages build. [GitHub Docs](https://docs.github.com/en/actions/concepts/security/github_token)
- GitHub cũng nêu lịch `schedule` có thể trễ hoặc bị bỏ lượt khi tải cao; repo công khai không hoạt động 60 ngày có thể bị tắt lịch. Vì vậy phải có các lượt đối soát bù, kiểm tra lịch còn bật và heartbeat; không coi cron là bằng chứng đã phát hành. [GitHub Docs](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- Khi GitHub/Pages không sẵn sàng hoặc không có đủ 5 bài đã duyệt, lưu đúng số thiếu và nguyên nhân. Không đánh dấu `complete` hoặc tự hạ chuẩn kiểm tra.

## 9. Trạng thái và cảnh báo

`health.json` công khai và lệnh `status` phải phân biệt:

- Ngày hiện tại, mục tiêu 5, số đã xác nhận công khai, đang triển khai và còn thiếu.
- Số bài đã duyệt còn trong kho; số ngày dự phòng = phần nguyên của số bài chưa đặt chỗ chia 5.
- Trạng thái thu thập, lần sản xuất thành công gần nhất, lần phát hành thành công gần nhất, heartbeat của từng worker.
- Mã lý do chờ và thời điểm thử lại; thời điểm dữ liệu trạng thái được tạo để người đọc nhận ra thông tin đã cũ.

Sau 07:00 nếu chưa đủ 5: `running` hoặc mã chờ cụ thể. Đến 23:30 chưa đủ: `missed`, kèm số thực tế và nguyên nhân. Một lệnh thử thành công hoặc một tác vụ Windows trả mã 0 không được đổi kết quả này.

Cảnh báo tại bảng trạng thái và thông báo Windows khi kho thấp, ngày thiếu bài, cần đăng nhập hoặc phát hành thất bại. Chỉ thông báo khi có thay đổi đáng kể; không lặp mỗi lần retry. Không tự gửi email/Slack hay bật kênh liên lạc bên ngoài.

Website tĩnh không thể tự ghi trạng thái mới khi mọi tác vụ phát hành đều ngừng. Giao diện phải dựa vào ngày hiện tại và heartbeat để hiện “trạng thái chưa cập nhật”, tránh giữ nhãn xanh từ hôm trước. Chưa có bộ giám sát độc lập luôn bật thì không được tuyên bố đã phát hiện được mọi lần cron không chạy.

## 10. Tiêu chí nghiệm thu

| Tình huống | Điều kiện đạt |
| --- | --- |
| Còn hơn 5 bài đã duyệt; Codex không khả dụng | Phát hành đúng 5 từ kho, không gọi Codex |
| Windows tắt trong hai ngày; kho đã đồng bộ còn ít nhất 10 | GitHub phát hành 5 bài mỗi ngày; không cần Windows khởi động |
| Có 35 bài dự phòng và mô phỏng 7 ngày không sản xuất | Bộ điều phối dùng 35 DOI khác nhau, mỗi ngày đúng 5, không vượt trần |
| 15 ứng viên đầu thiếu nguồn hoặc lỗi review | Sang lô kế; không báo hoàn tất khi mới hết một lô |
| Bài review không đạt; có ứng viên khác đủ chuẩn | Giữ bài lỗi, chọn bài khác; không đăng bài lỗi |
| Quota ngắt giữa sửa/review | Giữ checkpoint, sử dụng kho dự phòng và tiếp tục đúng bước khi dùng được Codex |
| Lỗi 403/429/timeout; có nguồn thay thế khớp DOI | Tuân thủ cooldown; thử đúng nguồn/lịch, không dùng abstract thay toàn văn |
| Tắt tiến trình ở từng bước commit/push/deploy/ghi sổ | Khôi phục đúng ID/DOI và deployment; không thiếu hoặc nhân đôi chỗ đã dùng |
| Hai trigger đồng thời; metadata được đẩy trong lúc phát hành | Không vượt 5, không chọn trùng, không làm mất bài hoặc dữ liệu vừa phát hành |
| Deployment trễ qua nửa đêm | Ngày công khai đúng, giữ trần ngày thực tế, không lùi ngày |
| `daily --limit 1` và lệnh chạy lại | Ngày vẫn hiện 1/5; không tạo hay đăng lại bài cũ |
| Kho còn 3 bài, không thể sản xuất | Công khai tối đa 3, báo thiếu 2 và nguyên nhân; không báo 5/5 |
| Phép so sánh vật lý, quote sai, hình thiếu phép hoặc DOI sai | Chấp nhận bất đẳng thức; chặn các lỗi nguồn/quyền; không làm mất tiêu chuẩn hiện có |
| Workflow không chạy, dữ liệu trạng thái sang ngày mới | Website nhận ra heartbeat cũ; không hiện hoàn tất hôm nay bằng số hôm qua |

Nghiệm thu thực tế cần **7 ngày liên tiếp**, mỗi ngày đối chiếu 5 DOI và phiên bản trên website với sổ phát hành. Báo cáo riêng số bài lấy từ kho và số bài mới được duyệt; việc tiêu hết kho mà không bổ sung được không chứng minh năng lực dài hạn. Đối chiếu trực tiếp ít nhất 5 summary với toàn văn, kiểm tra tiếng Việt, điện thoại, hình và đường dẫn Pages. Kiểm thử giả lập không được ghi thành kết quả phát hành thực tế.

## 11. Thứ tự triển khai

1. Tách bộ đếm công khai khỏi bài đã tạo; sửa `complete`, tạo sổ phát hành và đối soát 17 summary hiện có với website/deployment.
2. Chuyển công việc biên tập sang hàng đợi xuyên ngày; thêm lịch thử lại, lô kế tiếp, checkpoint và ngân sách công việc.
3. Tạo kho bài đã duyệt và đồng bộ lên GitHub; xác minh quyền sử dụng và fingerprint trước khi nhận vào kho.
4. Thêm luồng GitHub phát hành độc lập, dùng chung cơ chế tuần tự hóa với Pages hiện tại; kiểm thử dừng máy và phục hồi.
5. Thêm bảng trạng thái/cảnh báo, kiểm thử lỗi có chủ đích, tạo kho ban đầu và đo năng lực sản xuất với đúng cấu hình Codex.
6. Chạy nghiệm thu 7 ngày. Chỉ báo hệ thống đạt yêu cầu sau khi có bằng chứng đủ đầu ra, không trùng, không vượt trần và không che các ngày thiếu.

Trong thời gian chuyển đổi, giữ các summary đã phát hành và lịch hiện tại. Không bật hai publisher độc lập cùng ghi nội dung; chuyển quyền phát hành sang luồng mới sau khi đối soát xong.
