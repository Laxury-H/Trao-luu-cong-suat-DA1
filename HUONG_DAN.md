# Chương trình tính chế độ xác lập của lưới điện

Bộ chương trình Python tính trào lưu công suất AC bằng Newton–Raphson, dành cho lưới ba pha cân bằng. Có giao diện máy tính để bàn và chế độ dòng lệnh. Bạn có thể sửa mã nguồn và thay các tệp dữ liệu mẫu bằng lưới của mình.

## 1. Chạy nhanh

Yêu cầu: Python 3.10 trở lên, NumPy, và Tkinter nếu dùng giao diện.

1. Giải nén `che_do_xac_lap.zip`.
2. Mở Terminal/PowerShell trong thư mục `che_do_xac_lap` vừa giải nén.
3. Cài thư viện rồi mở chương trình:

```bash
python -m pip install -r requirements.txt
python gui.py
```

Trên Windows, sau khi cài thư viện, có thể nhấp đúp `CHAY_GIAO_DIEN.bat`. Nếu máy dùng lệnh `py`, thay `python` bằng `py`; trên macOS/Linux có thể dùng `python3`.

Trong giao diện: chọn **Ví dụ 3 nút** → **TÍNH TOÁN (F5)** → xem các thẻ kết quả (**Tổng quan**, **Sơ đồ lưới**, **Điện áp nút**, **Công suất nhánh**, **Báo cáo**) → **Xuất báo cáo TXT**, **Xuất kết quả JSON** hoặc **Xuất CSV (Excel)**. Bạn có thể nhấn nút **Chế độ tối** (hoặc `Ctrl+T`) để chuyển đổi giao diện sáng/tối, kéo thả các nút trên tab **Sơ đồ lưới** để quan sát trực quan hướng dòng công suất. Dữ liệu nằm ở khung bên trái, có thể sửa trực tiếp hoặc mở tệp JSON khác. Khi dữ liệu hay tùy chọn thay đổi, kết quả cũ được xóa để tránh xuất nhầm.

Nếu Python báo thiếu `tkinter`, hãy cài thành phần Tk của bản Python đang dùng. Bộ giải dòng lệnh vẫn chạy được mà không cần Tkinter hay màn hình đồ họa.

## 2. Chạy bằng dòng lệnh

Chạy ví dụ mặc định 3 nút:

```bash
python powerflow.py
```

Chạy lưới của bạn và xuất kết quả:

```bash
python powerflow.py luoi_cua_ban.json --output ket_qua.json --report bao_cao.txt
```

Các ví dụ và tùy chọn:

```bash
python powerflow.py examples/luoi_9_nut.json
python powerflow.py examples/luoi_3_nut_gioi_han_q.json
python powerflow.py examples/luoi_9_nut.json --tol 1e-10 --max-iter 60
python powerflow.py examples/luoi_3_nut_gioi_han_q.json --no-q-limits
python powerflow.py --help
```

`--tol` là dung sai sai lệch công suất p.u., mặc định `1e-8`. `--max-iter` là số bước Newton tối đa **mỗi lượt giải**, mặc định `50`. Một lần chuyển PV sang PQ sẽ bắt đầu lượt giải mới. Khi không hội tụ hoặc dữ liệu không hợp lệ, chương trình báo lỗi và trả mã thoát `2`; không xuất kết quả mới. Nếu đường dẫn xuất đã có tệp từ lần chạy trước, tệp đó vẫn giữ nguyên và không đại diện cho lần chạy bị lỗi. Khi thành công, tệp kết quả được ghi đè theo đường dẫn đã chỉ định.

## 3. Mô hình và đơn vị

Mô hình áp dụng:

- Lưới AC ba pha cân bằng, biểu diễn bằng mạch thứ tự thuận.
- Phụ tải P, Q không đổi; mỗi nút có một nguồn phát tương đương.
- Đường dây mô hình π, nhánh song song, nhánh đóng/cắt.
- Máy biến áp với tỷ số và góc dịch pha đặt cố định tại đầu `from_bus`.
- Shunt nút dạng tổng dẫn; nút SLACK, PV và PQ.
- Có thể giải nhiều đảo điện, mỗi đảo phải có đúng một nút SLACK.

| Đại lượng | Đơn vị / quy ước |
|---|---|
| `base_mva` | Công suất cơ sở **tổng ba pha**, MVA; mặc định 100 |
| P và Q của tải/nguồn | MW và Mvar **tổng ba pha** |
| `vm_pu` | Biên độ điện áp p.u. |
| `base_kv` | Điện áp cơ sở **dây–dây**, kV, tại từng nút |
| `va_deg`, `shift_deg` | Độ; bộ giải đổi sang radian khi tính |
| R, X, B và shunt | p.u. trên cùng cơ sở công suất và các cơ sở điện áp tương ứng |
| P/Q tải dương | Công suất tiêu thụ |
| P/Q nguồn dương | Công suất phát vào lưới |
| `b_shunt_pu > 0` | Shunt dung, phát công suất phản kháng |

Quy đổi thông số thực:

```text
Zbase (Ω) = Ubase_dây_dây (kV)^2 / Sbase_ba_pha (MVA)
Rpu = R(Ω) / Zbase
Xpu = X(Ω) / Zbase
Bpu = B(S) × Zbase
Zpu_mới = Zpu_cũ × (Sbase_mới/Sbase_cũ) × (Ubase_cũ/Ubase_mới)^2
```

Ví dụ: 110 kV, 100 MVA cho `Zbase = 121 Ω`. Nhánh có R = 2,42 Ω và X = 7,26 Ω được nhập `r_pu = 0.02`, `x_pu = 0.06`. Không nhập trực tiếp Ω vào trường p.u.

## 4. Cấu trúc và phương thức nhập dữ liệu đầu vào

Chương trình hỗ trợ **3 hình thức nhập dữ liệu lưới linh hoạt**, không bắt buộc phải viết mã JSON:

### Cách 1: Bảng dữ liệu trực quan (Visual Table Editor - Ngay trên giao diện)
- Chọn tab **"Bảng dữ liệu"** ở khung bên trái.
- Có sẵn 2 bảng: **Bảng Nút** và **Bảng Nhánh / Đường dây**.
- Nút **➕ Thêm**, **✏️ Sửa** (hoặc nhấp đúp vào hàng), **🗑️ Xóa** mở hộp thoại điền thông số có kiểm tra định dạng.
- Nút **📋 Dán Excel**: Cho phép bạn copy trực tiếp các hàng từ file Excel và bấm nút để nạp hàng loạt vào bảng!
- **Đồng bộ hai chiều tự động**: Bất kỳ thay đổi nào trên bảng sẽ tự động cập nhật sang tab **Mã JSON** và ngược lại.

### Cách 2: Nhập từ file Excel (.xlsx) hoặc CSV
- Nhấn nút **"Excel mẫu"** ở góc trên bên phải giao diện để tải file mẫu chuẩn `luoi_dien_mau.xlsx` (gồm 2 sheet: *Buses* và *Branches*).
- Bạn có thể mở file mẫu này bằng Microsoft Excel, Google Sheets hoặc WPS Office để điền số liệu đề bài bài tập lớn / đồ án.
- Tự động nhận diện linh hoạt tên cột cả bằng tiếng Việt (ví dụ: *Mã nút*, *Loại nút*, *Điện áp*, *Tải P*, *Phát P*, *Nút đầu*, *Nút cuối*, *Điện trở R*...) lẫn tiếng Anh (*id, type, vm_pu, pd_mw, pg_mw, from_bus, to_bus, r_pu*...).
- Bấm **Mở…** trên giao diện và chọn file `.xlsx` hoặc `.csv` để nạp trực tiếp vào chương trình.
- Sau khi chỉnh sửa, bạn cũng có thể chọn **Lưu…** và chọn đuôi `.xlsx` để xuất ngược ra file Excel chuẩn.

### Cách 3: Nhập tệp JSON truyền thống
Tệp UTF-8 chứa một đối tượng JSON. Các khóa chính: `name`, `description`, `source` (thông tin tùy chọn), `base_mva`, `buses` và `branches`. Phải có `buses` và `branches`. Dùng dấu chấm thập phân; JSON không cho phép chú thích hoặc dấu phẩy thừa. Khóa lặp, trường không được hỗ trợ, NaN và vô cùng đều bị từ chối để phát hiện nhầm dữ liệu.

Mẫu tối thiểu cho lưới 2 nút:

```json
{
  "name": "Lưới 2 nút",
  "base_mva": 100,
  "buses": [
    {"id": "1", "type": "SLACK", "vm_pu": 1.0},
    {"id": "2", "type": "PQ", "pd_mw": 50, "qd_mvar": 20}
  ],
  "branches": [
    {"from_bus": "1", "to_bus": "2", "r_pu": 0, "x_pu": 0.1}
  ]
}
```

### Dữ liệu nút

| Trường | Ý nghĩa | Mặc định |
|---|---|---|
| `id` | Mã duy nhất, chuỗi hoặc số nguyên; đầu ra chuẩn hóa thành chuỗi | Bắt buộc |
| `type` | `SLACK`, `PV`, `PQ` | Bắt buộc |
| `vm_pu` | Điện áp đặt tại SLACK/PV; giá trị khởi tạo tại PQ | 1 |
| `va_deg` | Góc cố định tại SLACK; góc khởi tạo tại PV/PQ | 0 |
| `pg_mw`, `qg_mvar` | P, Q nguồn phát tương đương | 0 |
| `pd_mw`, `qd_mvar` | P, Q phụ tải tại nút | 0 |
| `g_shunt_pu`, `b_shunt_pu` | Phần thực và ảo của tổng dẫn shunt nút | 0 |
| `base_kv` | Cơ sở điện áp để đổi U sang kV và I sang kA | `null` |
| `qmin_mvar`, `qmax_mvar` | Giới hạn Q **của nguồn**, không phải Q ròng sau khi trừ tải | `null` = không giới hạn |
| `pmin_mw`, `pmax_mw` | Giới hạn P dùng để phát cảnh báo | `null` |
| `vmin_pu`, `vmax_pu` | Ngưỡng điện áp dùng để phát cảnh báo | 0.9 và 1.1 |

`g_shunt_pu` phải không âm; `b_shunt_pu` có thể dương hoặc âm. P/Q tải có thể âm để biểu diễn công suất bơm vào nút; cần tránh nhập trùng phần bơm này vào nguồn phát.

| Loại nút | Đại lượng cố định | Đại lượng tính được |
|---|---|---|
| SLACK | U, góc; P/Q tải | Pg, Qg |
| PV | Pg, U; P/Q tải | Góc, Qg |
| PQ | Pg, Qg, P/Q tải | U, góc |

Tại SLACK, `pg_mw` và `qg_mvar` đầu vào không ràng buộc nghiệm. Tại PV, `qg_mvar` đầu vào không ràng buộc nghiệm. Ngưỡng U mặc định là ngưỡng minh họa của chương trình; hãy đặt lại theo yêu cầu lưới của bạn.

### Dữ liệu nhánh

| Trường | Ý nghĩa | Mặc định |
|---|---|---|
| `id` | Mã nhánh duy nhất | L1, L2, … theo thứ tự |
| `from_bus`, `to_bus` | Mã hai nút đã khai báo, khác nhau | Bắt buộc |
| `r_pu`, `x_pu` | Điện trở, điện kháng nối tiếp | Bắt buộc |
| `b_pu` | **Tổng** điện nạp shunt của nhánh; mô hình chia B/2 về hai đầu | 0 |
| `tap` | Tỷ số biến áp tương đối, đặt ở đầu `from_bus`, phải > 0 | 1 |
| `shift_deg` | Góc dịch pha của biến áp ở đầu `from_bus` | 0 |
| `rate_mva` | Định mức công suất biểu kiến để tính tải nhánh | `null` |
| `status` | `true`/1: đóng; `false`/0: cắt | `true` |

`tap = 1` nghĩa là tỷ số phù hợp với các cơ sở điện áp đã chọn. Không nhập tỷ số kV cao/thấp trực tiếp vào `tap` nếu hai đầu đã dùng cơ sở điện áp tương ứng. Quy ước điện áp phía sau biến áp lý tưởng: `Vfrom / (tap × exp(j × shift))`. Giá trị `tap = 0` không được chấp nhận; khi chuyển dữ liệu MATPOWER, hãy đổi giá trị mặc định 0 của MATPOWER thành 1.

Nhánh đang đóng cần R ≥ 0 và tổng trở khác 0; nếu hai nút nối tắt lý tưởng, hãy gộp chúng trước. X có thể âm để biểu diễn bù nối tiếp trong mô hình này. Không dùng mô hình này để mô phỏng quá trình đóng cắt theo thời gian.

## 5. Phương pháp tính

Với điện áp phức V và ma trận tổng dẫn nút Ybus:

```text
S_i = V_i × liên_hợp(Σ Y_ik V_k)
P_đặt_i = (Pg_i − Pd_i) / Sbase
Q_đặt_i = (Qg_i − Qd_i) / Sbase
```

Nếu `Yik = Gik + jBik`, `θik = θi − θk`:

```text
P_i = U_i Σ U_k [Gik cos(θik) + Bik sin(θik)]
Q_i = U_i Σ U_k [Gik sin(θik) − Bik cos(θik)]
```

Ẩn số gồm góc của mọi nút khác SLACK và biên độ U tại các nút PQ. Mỗi bước lặp:

1. Tính P/Q từ điện áp hiện tại.
2. Lập sai lệch ΔP tại PV/PQ và ΔQ tại PQ.
3. Nếu sai lệch lớn nhất không vượt dung sai, kết thúc lượt giải.
4. Lập Jacobian giải tích, giải `J Δx = [ΔP; ΔQ]`, rồi cập nhật điện áp.
5. Nếu bước đầy đủ không giảm sai lệch hoặc làm U không dương, giảm bước và thử lại.

Không nghịch đảo Jacobian trực tiếp; chương trình dùng `numpy.linalg.solve`.

Mô hình một nhánh, với `y = 1/(r+jx)` và `t = tap × exp(j×shift)`:

```text
Yff = (y + jB/2) / |t|²       Yft = −y / liên_hợp(t)
Ytf = −y / t                  Ytt = y + jB/2
If  = Yff Vf + Yft Vt         It  = Ytf Vf + Ytt Vt
Sf  = Vf × liên_hợp(If) × Sbase
St  = Vt × liên_hợp(It) × Sbase
```

Sau khi một lượt giải hội tụ, chương trình tính Qg tại các PV. Nếu có vi phạm Q, nút vi phạm lớn nhất được giữ Qg tại giới hạn và đổi sang PQ, rồi giải lại. Trong cùng lần tính, nút đã chuyển không tự phục hồi PV. Giới hạn Q áp dụng cho nguồn phát tổng hợp ở nút. SLACK giữ nhiệm vụ cân bằng; nếu Pg/Qg của SLACK vượt giới hạn thì chương trình cảnh báo.

## 6. Đọc kết quả

Kết quả JSON chứa điện áp, góc, phát/tải ở từng nút, công suất và dòng ở hai đầu nhánh, tổn thất, tải nhánh, lịch sử lặp, lịch sử đổi loại nút và các cảnh báo.

- **Công suất dương ở mỗi đầu nhánh**: từ nút đó đi vào nhánh. Đầu nhận thường có P âm. Công suất nhận từ nhánh vào nút cuối là `−p_to_mw`, `−q_to_mvar`.
- **Tổn thất P của nhánh**: `p_from_mw + p_to_mw`.
- **Q thuần của nhánh**: `q_from_mvar + q_to_mvar`; có thể âm vì điện nạp đường dây phát Q. Trường này đặt tên `q_net_mvar`, không đồng nhất với tổn thất phản kháng nối tiếp.
- **Công suất shunt nút**: `Psh = U² Gsh Sbase`, `Qsh = −U² Bsh Sbase`.
- **Tổng tổn thất P**: tổng tổn thất nhánh cộng tiêu thụ P của shunt nút.
- **Tải nhánh (%)**: `100 × max(|Sf|, |St|) / rate_mva`.
- **Điện áp kV** là điện áp dây–dây. Dòng kA là dòng dây, tính riêng theo cơ sở điện áp ở từng đầu. Nếu thiếu `base_kv`, kết quả kV/kA là `null`.
- **Sai số cân bằng toàn mạng** kiểm tra `ΣPg − ΣPd − Pmạng` và `ΣQg − ΣQd − Qmạng`.

Ví dụ 3 nút, dung sai 1e-8 p.u., bật giới hạn Q:

| Nút | Loại cuối | U (p.u.) | Góc (độ) | Pg (MW) | Qg (Mvar) |
|---|---|---:|---:|---:|---:|
| 1 | SLACK | 1.060000 | 0.00000 | 52.74517 | 46.98589 |
| 2 | PV | 1.040000 | −0.14866 | 50.00000 | −6.74668 |
| 3 | PQ | 0.989366 | −4.10575 | 0.00000 | 0.00000 |

Tổng tổn thất khoảng **2.745173 MW**, hội tụ sau **3 bước**. Giá trị Qg âm tại nút 2 nghĩa là nguồn hấp thụ phản kháng. Lưới 9 nút hội tụ sau 4 bước với tổn thất khoảng **4.954702 MW**. Ở ví dụ giới hạn Q, nút 2 đổi PV → PQ, Qg giữ 10 Mvar và U giảm từ giá trị đặt 1.06 xuống khoảng 1.028137 p.u. Sai khác ở chữ số cuối có thể phụ thuộc môi trường số học.

## 7. Gọi bộ giải từ chương trình khác

```python
from powerflow import load_case, solve_power_flow, format_report

du_lieu = load_case("examples/luoi_3_nut.json")
ket_qua = solve_power_flow(
    du_lieu,
    tolerance=1e-8,
    max_iterations=50,
    enforce_q_limits=True,
    q_limit_tolerance_mvar=1e-5,
)
print(format_report(ket_qua))
```

API nhận một `dict`; không sửa dữ liệu đầu vào. Lỗi dữ liệu phát sinh `CaseError`; không hội tụ phát sinh `PowerFlowError`, trong đó thuộc tính `history` chứa lịch sử sai lệch. Không có kết quả trả về được đánh dấu thành công nếu chưa đạt dung sai.

## 7. Các tính năng mở rộng chuyên sâu (Advanced Features)

### 7.1. Tự động quét và đánh giá sự cố N-1 (N-1 Contingency Analysis)
- Thẻ **🛡️ Quét sự cố N-1**: Tự động giả lập lần lượt sự cố cô lập/ngắt từng đường dây và máy biến áp trong lưới điện.
- Với mỗi sự cố, chương trình tự động kiểm tra:
  - Khả năng hội tụ trào lưu công suất và kiểm tra rã lưới/đảo điện (islanding).
  - Tình trạng quá tải nhánh (>100% dòng định mức) và mang tải cao (>80%).
  - Vi phạm ngưỡng điện áp cho phép ($U < 0.95$ p.u. hoặc $U > 1.05$ p.u.).
  - Tính toán chỉ số mức độ nghiêm trọng **PI (Performance Index)** và tự động xếp hạng sự cố nguy cấp nhất lên đầu.
- Nhấp đúp vào bất kỳ sự cố nào để tự động chuyển sang tab **Sơ đồ lưới** và làm nổi bật phân đoạn sự cố.
- Hỗ trợ nút **Xuất bảng N-1...** lưu toàn bộ kết quả phân tích ra tệp CSV.

### 7.2. Chế độ so sánh kịch bản (Scenario Comparison Mode)
- Thẻ **⚖️ So sánh kịch bản**:
  - Nhấn **📌 Lưu làm Base Case** để lưu chế độ cơ sở làm mốc tham chiếu.
  - Sau đó điều chỉnh phụ tải, công suất phát hoặc đóng/cắt phần tử và bấm **F5**.
  - Chương trình tự động tính bảng sai biệt so sánh:
    - $\Delta P_{\text{loss}}$ (Tăng/giảm tổn thất công suất MW và %).
    - $|\Delta U|_{\max}$ và bảng độ lệch điện áp từng nút kèm nhãn cảnh báo biến động.
    - $|\Delta \text{Load}|_{\max}\%$ và bảng thay đổi mức mang tải từng đường dây.

### 7.3. Sơ đồ đơn tuyến thông minh (Single-Line Diagram Enhancements)
- Nút **⚡ Cấp điện áp**: Bố trí mạng điện theo phân tầng cấp điện áp (buses cấp áp cao/nguồn ở tầng trên, phụ tải ở tầng dưới).
- Thanh tìm kiếm **🔍 Tìm nút**: Gõ mã nút (ví dụ: `8`) và bấm **Định vị** hoặc ấn Enter để tự động phóng to và căn giữa thanh cái cần tìm.
- Nút **📷 Xuất vector...**: Xuất sơ đồ ra tệp vector sắc nét PostScript (`.eps` / `.ps`) phục vụ chèn vào báo cáo hoặc khóa luận mà không bị vỡ hạt.
- Tự động bật High-DPI Awareness trên Windows, giúp chữ và sơ đồ hiển thị sắc nét, không bị mờ nhòe.

### 7.4. Xuất báo cáo đa trang Excel (.xlsx) chuyên nghiệp
- Nút **Xuất Excel (4 sheet)…** tạo file Excel định dạng chuẩn quốc tế:
  1. **Trang 1: Tổng quan**: Bảng thông số hệ thống, thời gian giải, số bước lặp, tổn thất và hệ số cos phi.
  2. **Trang 2: Điện áp nút**: Toàn bộ $U$ (p.u., kV), góc pha, $P_g, Q_g, P_d, Q_d$.
  3. **Trang 3: Công suất nhánh**: Chi tiết dòng $P, Q, I$ hai đầu, tổn thất $\Delta P, \Delta Q$ và % mang tải.
  4. **Trang 4: Cảnh báo & vi phạm**: Tóm tắt danh sách cảnh báo nút sụt áp, quá áp hoặc nhánh quá tải.

## 8. Kiểm chứng và phạm vi

Chạy lại bộ kiểm thử:

```bash
python -m unittest discover -s tests -v
```

Bộ giải đã vượt qua **48 kiểm thử tự động** trên Python 3.13 / NumPy với 100% độ chính xác: bài toán 2 nút nghiệm giải tích, lưới IEEE 9 nút, IEEE 14 nút, IEEE 30 nút, kiểm thử N-1 contingency, kiểm thử so sánh kịch bản, kiểm thử xuất nhập Excel/CSV và các thuật toán bố cục sơ đồ.

Giới hạn hiện tại:

- Chưa xét mất cân bằng ba pha, dây trung tính, phụ tải ZIP/động, ngắn mạch hoặc quá trình quá độ.
- Không giải OPF, không tự điều chỉnh P nguồn, nấc phân áp hay bù để loại bỏ vi phạm U/tải nhánh.
- Hội tụ phương trình không có nghĩa mọi giới hạn vận hành đều được thỏa mãn; cần đọc cảnh báo.
- Cách chuyển PV → PQ là vòng lặp giới hạn Q đơn giản, không phục hồi PV và không biểu diễn đầy đủ đường cong khả năng máy phát hay phân chia Q giữa nhiều máy cùng nút.
- Jacobian/Ybus dạng ma trận đặc, phù hợp học tập và lưới nhỏ đến vừa; chưa tối ưu cho hàng nghìn nút.
- Newton không bảo đảm tìm được nghiệm cho mọi điểm khởi tạo hoặc mọi mức tải. Không hội tụ không đủ để kết luận lưới không có nghiệm hay mất ổn định điện áp.

## 9. Tệp trong bộ chương trình

| Tệp / thư mục | Nội dung |
|---|---|
| `powerflow.py` | Bộ giải trào lưu công suất Newton–Raphson, kiểm tra dữ liệu và CLI |
| `contingency.py` | Phân tích sự cố N-1 tự động, tính chỉ số PI và xếp hạng mức độ nguy cấp |
| `data_io.py` | Nhập/xuất dữ liệu Excel (.xlsx) & CSV, tạo template và xuất báo cáo Excel 4 sheets |
| `gui.py` | Giao diện đồ họa chính (Desktop UI) với chế độ N-1 và so sánh kịch bản |
| `ui_table_editor.py` | Trình nhập liệu bảng trực quan (Bảng Nút & Bảng Nhánh) |
| `ui_topology.py` | Sơ đồ 1 sợi trực quan tương tác, thuật toán bố cục lực đẩy, đa tầng & cấp áp |
| `ui_dashboard.py` | Bảng đồng hồ KPIs, biểu đồ điện áp và tiến trình hội tụ |
| `ui_editor.py` | Trình soạn thảo JSON có đánh số dòng, highlight cú pháp |
| `CHAY_GIAO_DIEN.bat` | Khởi chạy giao diện nhanh trên Windows |
| `requirements.txt` | Thư viện cần cài (numpy, matplotlib, openpyxl) |
| `examples/` | Dữ liệu mẫu JSON (3 nút, 9 nút, IEEE 14 nút, IEEE 30 nút) và template Excel |
| `results/` | Kết quả JSON và báo cáo TXT đã tính |
| `tests/` | Bộ 48 bài kiểm thử tự động toàn diện |
| `HUONG_DAN.md` | Hướng dẫn sử dụng chi tiết |
| `KIEM_CHUNG.md` | Báo cáo kiểm chứng |

## 10. Tài liệu tham khảo

Các quy ước trào lưu, Jacobian và mô hình nhánh được đối chiếu với tài liệu chính thức; bộ mã nguồn Python được viết riêng cho chương trình này.

- [MATPOWER — AC Power Flow: các loại nút và xử lý giới hạn Q](https://matpower.app/manual/matpower/ACPowerFlow.html).
- [MATPOWER — newtonpf: phương pháp Newton ở tọa độ cực](https://matpower.org/docs/ref/matpower7.0/lib/newtonpf.html).
- [MATPOWER — makeYbus: mô hình nhánh và shunt](https://matpower.org/docs/ref/matpower7.1/lib/makeYbus.html).
- [MATPOWER — case9: nguồn các thông số số học của ví dụ 9 nút](https://matpower.org/docs/ref/matpower6.0/case9.html). Chỉ chuyển các thông số trào lưu, không sao chép bộ giải hay mô hình chi phí OPF. Đây là kết quả tự tính trên dữ liệu case9; không tuyên bố đã chạy MATLAB/MATPOWER để đối chiếu.
