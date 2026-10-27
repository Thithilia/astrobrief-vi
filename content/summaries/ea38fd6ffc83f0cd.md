---
id: ea38fd6ffc83f0cd
doi: 10.3847/1538-4357/aeaa36
title: JWST đo số lượng và sự tụ cụm của thiên hà ít tạo sao thời sơ khai
dek: Khảo sát JWST trên 34 hướng nhìn cho thấy các thiên hà lớn ít tạo sao phổ biến
  hơn nhiều mô hình dự đoán, đồng thời đo được dao động số lượng giữa các trường ở
  mức σ_CV ≈ 0,7 ± 0,3.
journal: apj
authors:
- Zhiyuan Ji
- Christina C. Williams
- Peter Behroozi
- Andrea Weibel
- Christian Kragh Jespersen
- Pascal A. Oesch
- Rachel Bezanson
- Katherine E. Whitaker
- Jenny E. Greene
- Gabriel Brammer
- Pratika Dayal
- Ivo Labbé
- Sinclaire M. Manning
- Pierluigi Rinaldi
- Mengyuan Xiao
- Yunchong Zhang
paper_title: 'PANORAMIC: The Dawn of Massive Quiescent Galaxies. I. Number Density
  and Cosmic Variance from 1000 arcmin 2 NIRCam Imaging'
published_online: '2026-10-26T00:00:00Z'
issue_date: '2026-11-01'
first_seen: '2026-10-26T10:05:03Z'
summary_date: '2026-10-27'
generated_at: '2026-10-27T07:41:54.244480Z'
topic: galaxies
reading_minutes: 6
source:
  kind: arxiv
  url: https://arxiv.org/abs/2604.05022v2
  version: 2604.05022v2
  doi: 10.3847/1538-4357/aeaa36
  sha256: a817c82dcef54a8cdd02fc058befd654b3aa211c81cf1714649a81b750afabe7
  license: null
figures: []
glossary:
- vi: Thiên hà ít tạo sao
  en: Quiescent galaxy
- vi: Dập tắt tạo sao
  en: Quenching
- vi: Dịch chuyển đỏ trắc quang
  en: Photometric redshift
- vi: Phân bố năng lượng phổ
  en: Spectral energy distribution, SED
- vi: Tốc độ tạo sao riêng
  en: Specific star formation rate, sSFR
- vi: Lịch sử tạo sao
  en: Star formation history, SFH
- vi: Mật độ số đồng chuyển
  en: Comoving number density
- vi: Phương sai vũ trụ
  en: Cosmic variance
- vi: Chấm đỏ nhỏ
  en: Little red dot, LRD
- vi: Nhân thiên hà hoạt động
  en: Active galactic nucleus, AGN
references:
- label: Bài công bố gốc (DOI)
  url: https://doi.org/10.3847/1538-4357/aeaa36
- label: Phiên bản toàn văn đã đọc
  url: https://arxiv.org/abs/2604.05022v2
byline: Tổng hợp tự động bằng Codex
---

## Những thiên hà lớn đã giảm tạo sao bằng cách nào?

Câu hỏi vật lý là làm thế nào những thiên hà ít tạo sao (quiescent galaxy) xuất hiện sớm giữa nguồn khí dồi dào của vũ trụ trẻ. Chúng phải tích lũy nhiều sao rất nhanh, rồi trải qua dập tắt tạo sao (quenching) và duy trì trạng thái ấy dù khí mới tiếp tục được cung cấp. Số lượng và nơi xuất hiện của chúng giúp kiểm tra hai yêu cầu này.

Zhiyuan Ji và cộng sự kết hợp khảo sát PANORAMIC với ảnh JWST lưu trữ để đo cả mật độ trung bình lẫn biến thiên giữa các vùng trời. Các nghiên cứu trước thường chỉ có 2–6 hướng nhìn độc lập; công trình này sử dụng 34, giúp phân biệt đặc điểm chung của quần thể với ảnh hưởng của từng vùng giàu thiên hà. Bài tổng hợp tự động bằng Codex này dựa trên bản arXiv 2604.05022v2. [P002-S005](#nguon-goc) [P003-S002](#nguon-goc)

## Ít tạo sao không đồng nghĩa với không còn sao

Dịch chuyển đỏ (redshift), ký hiệu z, càng lớn thì thời điểm quan sát càng sớm. Nhóm suy ra dịch chuyển đỏ trắc quang (photometric redshift), z_phot, từ độ sáng qua nhiều bộ lọc. Họ khớp phân bố năng lượng phổ (spectral energy distribution, SED) để ước lượng khối lượng sao và tốc độ tạo sao (star formation rate, SFR). Một nguồn đỏ có thể chứa quần thể sao đã tiến hóa hoặc bị bụi che khuất; màu đỏ riêng lẻ không quyết định được trạng thái tạo sao.

Đại lượng phân loại là tốc độ tạo sao riêng (specific star formation rate), sSFR = SFR/M∗. Bài dùng ngưỡng sSFR ≤ 0,2/t_H(z), với t_H là thời gian Hubble tại z theo ký hiệu của tác giả. Mật độ số đồng chuyển (comoving number density) đếm nguồn trong thể tích đã quy đổi để loại ảnh hưởng giãn nở. Còn phương sai vũ trụ (cosmic variance) mô tả dao động giữa các trường do cấu trúc không gian; σ_CV biểu thị độ phân tán tương đối sau khi trừ nhiễu đếm Poisson. [P006-S013](#nguon-goc) [P006-S014](#nguon-goc) [P014-S005](#nguon-goc)

## Từ ảnh sáu bộ lọc đến hai mức phân loại

Dữ liệu phủ 0,28 độ vuông, tương đương khoảng 1.000 phút cung vuông, và mỗi vùng phải có ít nhất sáu bộ lọc NIRCam. Nhóm kết hợp màu quan sát với màu trong hệ nghỉ (rest-frame colors), thu được 2.633 nguồn ban đầu. Hình 1 cho thấy các vùng khảo sát rải rác; Hình 2 trình bày hai không gian màu dùng trong sàng lọc. [P003-S004](#nguon-goc) [P005-S008](#nguon-goc)

Tiếp đó, phần mềm Prospector khớp ba lịch sử tạo sao (star formation history, SFH): một dạng trễ–τ và hai dạng phi tham số, lần lượt ưu tiên biến đổi êm hoặc cho phép bùng nổ mạnh. Nguồn đạt ngưỡng sSFR trong cả ba phép khớp thuộc mẫu vàng (gold); đạt trong một hoặc hai phép khớp thuộc mẫu bạc (silver). Cách chia này thể hiện mức phụ thuộc của phân loại vào giả thiết SFH. [P006-S013](#nguon-goc) [P007-S001](#nguon-goc)

Mẫu cuối gồm 406 nguồn, trong đó 238 có M∗ ≥ 10¹⁰ M⊙, với M⊙ là khối lượng Mặt Trời: 101 nguồn vàng và 137 nguồn bạc. Phân tích mật độ tập trung vào nhóm khối lượng này. Khi tính mật độ, mỗi nguồn đóng góp theo phân bố xác suất đồng thời của z_phot và sSFR, thay vì được tính chắc chắn là một thiên hà ít tạo sao tại một z duy nhất. [P007-S007](#nguon-goc) [P008-S007](#nguon-goc)

## Hiếm hơn ở thời điểm sớm, nhưng vẫn nhiều hơn dự đoán

Ở z = 3,0–3,5, mật độ mẫu vàng là (1,81 ± 0,53) × 10⁻⁵ Mpc⁻³; mẫu vàng cộng bạc đạt (3,14 ± 0,71) × 10⁻⁵ Mpc⁻³. Nhìn về thời điểm sớm hơn, tại z = 6–8, mật độ vàng còn (7 ± 6) × 10⁻⁷ Mpc⁻³. Sai số này bao gồm đo đạc, nhiễu đếm và phương sai vũ trụ. Xu hướng chính là giảm hơn 20 lần về phía dịch chuyển đỏ cao. [P010-S005](#nguon-goc) [P010-S006](#nguon-goc) [P011-S005](#nguon-goc)

Nhiều mô phỏng thủy động lực học (hydrodynamical simulations) dự đoán thiếu ít nhất 1 dex, tức khoảng mười lần, ở z ≳ 4. Hai mô hình bán giải tích (semi-analytic models) SHARK và GAEA tiến gần mép dưới của kết quả vàng tới z ∼ 5. UniverseMachine, một mô hình thực nghiệm, khá phù hợp ở z ≃ 3,5–5 nhưng thiếu nguồn rõ rệt sau z ≳ 5. Mức bất đồng vì thế phụ thuộc mô hình và thời điểm. [P012-S009](#nguon-goc) [P013-S010](#nguon-goc) [P014-S001](#nguon-goc)

Với mẫu gộp, phương pháp tái lấy mẫu cho σ_CV = 0,71 (+0,20; −0,28), trên thang một ô quan sát NIRCam. Để so sánh, nhóm chọn các thiên hà có sSFR thấp nhất trong UniverseMachine sao cho mật độ trung bình khớp quan sát. Phương sai nội tại của mẫu mô phỏng này khoảng 0,43. Quan sát nghiêng về tụ cụm mạnh hơn, nhưng chênh lệch hiện chỉ khoảng 1σ. [P015-S004](#nguon-goc) [P015-S007](#nguon-goc) [P016-S004](#nguon-goc) [P018-S005](#nguon-goc)

## Những giả thiết quyết định cách đọc kết quả

Một lựa chọn quan trọng là loại nguồn có F277W−F444W ≥ 1 mag để giảm lẫn các chấm đỏ nhỏ (little red dot, LRD), vốn có thể mang bức xạ mạnh từ nguồn năng lượng ngoài sao. Nhưng ở z ∼ 7, thiên hà ít tạo sao thật cũng có thể rất đỏ. Chính một thiên hà đã được xác nhận bằng quang phổ ở z ≃ 7,3 bị loại bởi màu 1,1 mag. Vì vậy, số đếm cao nhất về z chịu ảnh hưởng trực tiếp của cách xử lý nhóm nguồn này. [P007-S003](#nguon-goc) [P020-S002](#nguon-goc) [P020-S003](#nguon-goc)

So sánh mô hình còn giả định rằng khối lượng và SFR suy từ ánh sáng tương ứng với các đại lượng vật lý trong mô phỏng. Kiểm tra trực tiếp giả định ấy cần tạo ảnh giả lập rồi xử lý bằng cùng quy trình; bài chưa có phép thử này cho toàn bộ mô hình. Ngoài ra, mẫu vàng riêng chưa đủ thống kê để đo σ_CV vững chắc, nên kết quả phương sai sử dụng cả mẫu bạc, nơi phân loại nhạy hơn với SFH. [P012-S007](#nguon-goc) [P031-S008](#nguon-goc)

## Phép thử tiếp theo nằm ở cả khí và môi trường

Ý nghĩa vật lý của phép đo kép là mô hình phải giải thích được bao nhiêu thiên hà bị dập tắt và chúng nằm ở đâu. Tác giả thảo luận phản hồi (feedback) từ nhân thiên hà hoạt động (active galactic nucleus, AGN): gió có thể tống khí ra ngoài hoặc gia nhiệt, giúp giảm tạo sao nhanh. SHARK và GAEA đều có thêm kênh gió AGN hiệu suất bức xạ cao và cho số đếm gần quan sát hơn. Đây là diễn giải cơ chế từ so sánh mô hình; công trình trực tiếp đo mật độ và biến thiên giữa các trường. [P018-S001](#nguon-goc) [P018-S008](#nguon-goc)

Bước tiếp theo là bổ sung khoảng 50–150 hướng nhìn độc lập, duy trì độ phủ bộ lọc và thực hiện quang phổ (spectroscopy) cho mẫu được chọn đồng nhất. Quang phổ sẽ kiểm tra mức lẫn của mẫu bạc và phân biệt thiên hà ít tạo sao với LRDs. Thêm hướng nhìn sẽ thu hẹp sai số của σ_CV. Nếu phần dư tụ cụm tồn tại, môi trường trở thành ràng buộc mạnh hơn lên cơ chế dập tắt; nếu biến mất, yêu cầu giải thích số lượng cao vẫn còn. [P020-S008](#nguon-goc) [P022-S004](#nguon-goc)
