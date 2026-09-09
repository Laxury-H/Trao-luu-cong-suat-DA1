# PowerFlow — Phân Tích Chế Độ Xác Lập Lưới Điện (Đồ án 1)

Bộ chương trình Python tính toán **Trào lưu công suất AC** (Power Flow / Load Flow) bằng phương pháp **Newton–Raphson** cho hệ thống điện ba pha cân bằng. Hỗ trợ giao diện máy tính để bàn (GUI) hiện đại, sơ đồ 1 sợi tương tác, nhập/xuất Excel & CSV, và chế độ dòng lệnh (CLI).

---

## ⚡ Tính năng nổi bật

- **Thuật toán chính xác**:
  - Phương pháp **Newton–Raphson** tọa độ cực, giải lặp ma trận Jacobian đặc trưng.
  - Hỗ trợ đầy đủ các loại nút: **SLACK** (Nút cân bằng), **PV** (Nút máy phát có khống chế giới hạn $Q_{\min} \le Q \le Q_{\max}$), **PQ** (Nút phụ tải).
  - Mô hình hóa đường dây hình $\pi$ tương đương, máy biến áp điều chỉnh nấc phân áp (tap) và góc lệch pha ($\Delta\theta$), phần tử bù ngang (Shunt), nhánh đóng/cắt.
- **Giao diện người dùng (Desktop GUI)**:
  - **Sơ đồ 1 sợi tương tác (Single-Line Diagram)**: Vẽ thanh cái, máy phát, phụ tải, đường dây có mũi tên chỉ hướng dòng công suất ($P \rightarrow$) và đổi màu cảnh báo quá tải (<80%, 80–100%, >100%). Hỗ trợ kéo thả vị trí nút trực tiếp.
  - **Trình nhập liệu bảng trực quan (Visual Table Editor)**: Bảng Nút & Bảng Nhánh với các thao tác Thêm, Sửa, Xóa và **📋 Dán từ Excel (Clipboard)**. Tự động đồng bộ hai chiều với mã JSON.
  - **Nhập/Xuất Excel (.xlsx) & CSV**: Tự động nhận diện tên cột tiếng Việt / tiếng Anh. Có nút tải file mẫu Excel chuẩn `luoi_dien_mau.xlsx`.
  - **Bảng đồng hồ KPI & Đồ thị**: Đo lường tổng công suất phát, phụ tải, tổn thất ($\Delta P, \Delta Q$), % tổn thất, hệ số công suất $\cos\varphi$, biểu đồ điện áp nút với vùng an toàn IEEE $[0.95, 1.05\text{ p.u.}]$, đồ thị lịch sử hội tụ.
  - **Chế độ Sáng / Tối (Dark / Light Theme)**: Chuyển đổi nhanh qua nút bấm hoặc phím tắt `Ctrl + T`.
  - **Xuất báo cáo đa dạng**: Hỗ trợ xuất kết quả ra tệp TXT, JSON, và CSV chuẩn UTF-8-SIG mở trực tiếp trên Excel.

---

## 🚀 Cài đặt và Chạy chương trình

### 1. Yêu cầu hệ thống
- Python 3.10 trở lên.
- Các thư viện phụ thuộc: `numpy`, `matplotlib`, `openpyxl`.

### 2. Cài đặt thư viện
```bash
pip install -r requirements.txt
```

### 3. Khởi chạy giao diện Desktop (GUI)
- **Trên Windows**: Nhấp đúp vào tệp `CHAY_GIAO_DIEN.bat` hoặc chạy:
  ```bash
  python gui.py
  ```

### 4. Chạy chế độ dòng lệnh (CLI)
```bash
# Chạy ví dụ mặc định
python powerflow.py

# Chạy với tệp dữ liệu của bạn và xuất báo cáo
python powerflow.py examples/luoi_3_nut.json --output ket_qua.json --report bao_cao.txt

# Xem tất cả các tùy chọn hỗ trợ
python powerflow.py --help
```

---

## 🧪 Kiểm thử tự động (Unit Tests)

Dự án đi kèm bộ **41 bài kiểm thử tự động** bao phủ từ thuật toán số học đến giao diện người dùng và xuất nhập file:

```bash
python -m unittest discover -s tests -v
```

---

## 📁 Cấu trúc thư mục

```text
├── powerflow.py           # Bộ giải Newton-Raphson, xác thực dữ liệu và CLI
├── gui.py                 # Giao diện chính Desktop Tkinter
├── data_io.py             # Nhập/xuất dữ liệu Excel (.xlsx) & CSV
├── ui_table_editor.py     # Trình nhập liệu bảng trực quan (Bảng Nút & Nhánh)
├── ui_topology.py         # Sơ đồ 1 sợi trực quan tương tác
├── ui_dashboard.py        # Bảng điều khiển KPI và đồ thị Matplotlib
├── ui_editor.py           # Trình soạn thảo JSON có highlight cú pháp
├── CHAY_GIAO_DIEN.bat     # Khởi chạy ứng dụng nhanh trên Windows
├── requirements.txt       # Danh sách thư viện cần thiết
├── examples/              # Các tệp lưới mẫu JSON và file Excel chuẩn
├── results/               # Kết quả mẫu và báo cáo kiểm chứng
├── tests/                 # Bộ kiểm thử tự động (41 tests)
├── HUONG_DAN.md           # Tài liệu hướng dẫn sử dụng chi tiết
└── KIEM_CHUNG.md          # Báo cáo kiểm chứng thuật toán
```

---

## 📖 Hướng dẫn chi tiết
Chi tiết về mô hình toán học, công thức quy đổi p.u., cấu trúc dữ liệu và kiểm chứng được trình bày đầy đủ tại [HUONG_DAN.md](HUONG_DAN.md) và [KIEM_CHUNG.md](KIEM_CHUNG.md).
