# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (judge replay, verdict lưu sẵn trong CSV; lớp dương = `FAIL`).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** | **dùng** (chỉ cho tiêu chí giọng văn, không chặn release một mình) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** (κ, R) | **loại** |

Ma trận nhầm lẫn (FAIL = dương):

| | tp | fp | fn | tn | Tỉ lệ FAIL judge quan sát | Sau Rogan-Gladen |
|---|---|---|---|---|---|---|
| tone_ok | 24 | 4 | 6 | 66 | 0.28 | 0.30 |
| helpful | 9 | 0 | 21 | 70 | 0.09 | 0.30 |

## Audit thủ công: 10 bất đồng của `tone_ok` (đủ cả 10, yêu cầu ≥5)
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã. Rubric: liệt kê cách xưng hô bắt buộc ("LogiX", "anh/chị"); "em/bạn" + tiểu từ "nha/nhé" = FAIL. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn…" | PASS | FAIL | Người | Cùng lỗi xưng hô như #1; judge đánh đồng "thân thiện" với "lịch sự". Thêm ví dụ FAIL có "bạn ơi" vào few-shot. |
| 3 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ dò từ khóa lịch sự ("Dạ, vui lòng"). Rubric: câu mệnh lệnh / cấm khách liên hệ = FAIL dù có "Dạ". |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ…" | FAIL | PASS | Người | Judge phạt vì thiếu xin lỗi. Rubric: xin lỗi **không bắt buộc** khi đã giải quyết xong; ngắn gọn ≠ thô lỗ. |
| 5 | H-051 "…LogiX đã refund 90.000đ…" | FAIL | PASS | Người | Style guide CS LogiX cho phép "refund". Đưa danh sách từ mượn được phép vào rubric. |
| 6 | H-063 "…và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người | Hứa ngoài kết quả hệ thống. Đây là lỗi **nội dung**, không phải giọng văn: không giao cho judge tone, chấm bằng code (reply ↔ ledger, như FM-08). |
| 7 | H-070 "…ạ 😂😂" | PASS | FAIL | Người | Rubric: emoji trong phản hồi khiếu nại = FAIL. |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện…" | FAIL | PASS | **Judge** | Ghi chú CSV: người đọc nhầm ticket. Nhãn người phải sửa thành FAIL ở tập nhãn kế tiếp; không sửa file `_public.csv` vì test tham chiếu (κ=0.757) dựa trên nó. |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn…" | FAIL | PASS | Người (lỗi nhỏ) | Lặp "Dạ" do gõ nhầm; không phải giọng văn kém. Rubric: lỗi gõ đơn lẻ không làm FAIL. |
| 10 | H-094 "Da, LogiX da hoan… xin loi…" | PASS | FAIL | Người | Mất dấu tiếng Việt (dịch máy). Rubric: tiếng Việt không dấu = FAIL. |

Tóm lại: 9/10 bất đồng người đúng, 1/10 (H-081) nhãn người sai. Lỗi của judge chia hai hướng:
quá dễ với xưng hô suồng sã / emoji / không dấu (6 fn) và quá khắt khe với câu ngắn không xin lỗi / từ "refund" (4 fp, trong đó H-081 thực ra đúng).

## Vì sao `helpful` bị loại
Cả 21 bất đồng đều là **fn** (người FAIL, judge PASS), fp = 0. Judge quá dễ dãi: P=1.0 trông đẹp nhưng chỉ bắt 9/30 lỗi (R=0.3), κ=0.375 < 0.6.
Nếu dùng làm gate, tỉ lệ lỗi quan sát 9% che giấu tỉ lệ thật ≈ 30% (Rogan-Gladen), tức bỏ lọt khoảng 2/3 reply không hữu ích.

Ba nhóm fn, mỗi nhóm cần một cách sửa khác nhau:

| Nhóm | Case | Nguyên nhân | Cách xử lý |
|---|---|---|---|
| Số tiền sai so với ledger | HL-015, HL-020, HL-062, HL-087, HL-100 | Judge chỉ thấy reply, không thấy ledger, nên không thể biết 55.000đ là sai (ledger 40.000đ) | **Không dùng judge**: chấm bằng code, metric FM-08 (số trong reply = ledger) ở M3 |
| Xin lỗi lặp lại, dài dòng | HL-016, 028, 035, 041, 043, 053, 058, 070, 072, 074, 090, 096, 098 | Thiên vị độ dài / lời xin lỗi (verbosity bias) | Rubric: lặp xin lỗi ≥2 lần hoặc thông tin chính bị chôn = FAIL; thêm ví dụ FAIL dài vào few-shot; calibrate lại |
| Trả lời mơ hồ, thiếu số tiền | HL-047, HL-091, HL-097 "Ok bạn, đơn … xử lý rồi nhé." | Judge không kiểm tra thông tin bắt buộc | Kiểm tra bằng code: reply `resolved` phải có số tiền + mã đơn; giọng văn để judge tone |

## Kết luận
- **tone_ok: dùng được** cho tiêu chí giọng văn (κ=0.757, P=0.857, R=0.8 đều trên sàn), kèm các sửa rubric ở bảng audit. Không dùng nó để chấm tiền hay cam kết (case #6).
- **helpful: loại**, không được làm gate: κ=0.375, R=0.3 dưới sàn (ma trận tp=9, fp=0, fn=21, tn=70). Phần "hữu ích" đo được bằng code (số tiền đúng ledger, có mã đơn) chuyển sang grader code; phần còn lại cần rubric mới + calibrate lại trên nhãn mới.
- Quy tắc giữ nguyên: tiền và approval luôn chấm bằng code; judge chỉ cho tiêu chí đã qua FLOORS.
- **Rủi ro còn lại:** judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí); rubric sửa theo chính các case này nên cần nhãn người mới để có held-out thật. Một nhãn người đã biết là sai (H-081), nên các nhãn còn lại cũng cần người thứ hai kiểm.
