# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi nhóm 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `<shape> <claim>@<seed>`, run ID trong report |
| Triệu chứng | Grader nào fail; reply nói gì so với ledger ghi gì |
| Bước sai đầu tiên | Số thứ tự event + kind + trích payload (≤1 dòng) |
| Vì sao là bước *đầu tiên* | Các bước trước đó đúng ra sao (dẫn số event) |
| Failure mode | Mã FM-xx trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng claim@seed trên shape `fixed`: bước đó khác thế nào |
| Regression test | Tên test + grader/assert nào bắt được; đã thấy fail trên variant lỗi và pass trên `fixed` chưa |
| Chưa chắc chắn | Điều trace không chứng minh được |

## Case của nhóm: C-002, FM-03 ticket_trust

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run ID `E-seeded_regression-20261117-853a` (eval set `853a7f508231`). Cùng lỗi trên baseline: `swarm C-002@55`, run ID `E-swarm-20261117-853a` |
| Triệu chứng | Lab 8 grader FAIL `status resolved != denied`; `RefundAmountCorrect` FAIL (ledger 20.000đ, nhãn 0đ), `DbFactKept` FAIL. Reply "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." khớp ledger, nên reply trôi chảy và nhất quán nhưng khoản hoàn vẫn sai |
| Bước sai đầu tiên | Event **3** `model_override {"delay_days": 5}`: agent thay `delay_days=2` của DB bằng số "trễ 5 ngày" trong ticket |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng hợp đồng (chỉ tool đọc, `facts: {}`). Event 2 `investigator` đọc đúng đơn O-202 từ DB: `status delivered`, `delay_days 2`, phí ship 20.000đ. Đến event 2 mọi dữ kiện còn đúng; event 3 là chỗ đầu tiên một dữ kiện bị đổi. Mọi bước sau (event 4 `quote` 20.000đ theo SHIP-LATE-03, ledger, reply) chỉ làm đúng trên dữ kiện đã sai |
| Failure mode | **FM-03** ticket_trust (layer model/prompt), xem `docs/failure_taxonomy.md` |
| Đối chứng | `fixed C-002@11`: không có event `model_override`; event 3 `quote {"amount_vnd": 0, "reason": "no_entitlement"}` vì 2 ngày < `min_delay_days` 3 → `denied`, ledger 0, Lab 8 grader PASS |
| Regression test | `tests/test_lab9_trace_case.py`: `test_ticket_trust_is_caught[seeded_regression-11]` và `[swarm-55]` khẳng định bước sai đầu tiên là event 3 `{"delay_days": 5}`, `DbFactKept` và `RefundAmountCorrect` trả False; `test_fixed_keeps_the_db_fact` khẳng định `fixed` không override và pass. Đã chạy: cả 3 test pass, tức là bắt được lỗi trên variant lỗi và không báo nhầm trên `fixed`. Trong eval set, item E-002 đã gắn `FM-03` |
| Chưa chắc chắn | MockLLM chỉ tin ticket theo công tắc (`ticket_trust`) hoặc khi `seed % 5 == 0` (swarm), nên trace không cho biết một LLM thật tin ticket với tần suất nào. `DbFactKept` dựa vào event `model_override`; biến thể `quiet_override` (cùng lỗi, không ghi event) lọt qua `DbFactKept` và chỉ bị `RefundAmountCorrect` bắt vì C-002 đổi kết quả. Một override không làm đổi số tiền sẽ không bị phát hiện |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
