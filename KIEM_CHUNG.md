# Báo cáo kiểm chứng bộ giải

Ngày thực hiện: 09/09/2026. Môi trường: Python 3.12.14, NumPy 2.3.5, Linux.

## Kết quả

Lệnh `python -m unittest discover -s tests -v` hoàn thành **17/17 kiểm thử**, không có lỗi. Bộ kiểm thử chỉ cần NumPy và thư viện chuẩn Python.

| Nội dung kiểm chứng | Điều kiện đạt |
|---|---|
| Lưới 2 nút, đường dây thuần kháng | U khớp nghiệm giải tích đến 10 chữ số thập phân; tổn thất P bằng 0 trong sai số số học |
| Lưới MATPOWER case9 | Điện áp phức khớp bộ giải đối chiếu tọa độ chữ nhật với sai số tuyệt đối < 1e-10 p.u. |
| Jacobian giải tích có biến áp dịch pha và shunt | Khớp sai phân trung tâm, dung sai tuyệt đối/tương đối 2e-8 |
| Máy biến áp, shunt, nhánh song song và nhánh cắt | Khớp dòng tính trực tiếp từ tổng trở; nhánh cắt có công suất 0 |
| Tổn thất P từng nhánh | Khớp R × |I nối tiếp|² × Sbase |
| Dòng điện kA | Khớp |S| / (√3 × U dây–dây) |
| Qmax với tải ngay tại nút nguồn | Giới hạn áp dụng cho Qg tổng; điện áp PV được thả khi chuyển PQ |
| Qmin và tắt xử lý Q | Chuyển PQ đúng giới hạn; chế độ không cưỡng chế giữ điện áp PV và cảnh báo |
| Nhiều nút PV chạm giới hạn | Có hai lần chuyển loại nút và ba lượt giải |
| SLACK vượt Q | Giữ điện áp, giữ vai trò SLACK, phát cảnh báo |
| Một nút SLACK và lưới không có PQ | Giải được cả trường hợp không có ẩn số và chỉ có ẩn góc |
| Hai đảo điện hợp lệ | Mỗi đảo có một SLACK; tổn thất tổng bằng tổng hai bài toán riêng |
| Đảo thiếu hoặc thừa SLACK | Từ chối dữ liệu trước khi giải |
| Điện áp thấp / nhánh quá tải | Cảnh báo mà không tự thay đổi tải hay công suất đặt |
| JSON, dữ liệu và tùy chọn không hợp lệ | Từ chối khóa lặp, trường lạ, NaN, dữ liệu sai kiểu, tap/tổng trở không hợp lệ |
| Không hội tụ | Phát sinh lỗi, có lịch sử sai lệch, không trả kết quả thành công |
| Tính toàn vẹn dữ liệu và CLI | Đầu vào không bị sửa; xuất JSON/TXT thành công; lần giải lỗi trả mã 2 và không tạo tệp kết quả mới |

Các hàng trong bảng là nhóm điều kiện; một hàm kiểm thử có thể kiểm tra nhiều điều kiện.

## Đối chiếu độc lập lưới 9 nút

Trong `tests/test_powerflow.py`, bộ giải đối chiếu sử dụng phần thực và phần ảo của điện áp làm ẩn. Nó lập phương trình công suất cùng ràng buộc biên độ PV, tính dòng từng nhánh từ định luật Ohm và tỷ số biến áp, sau đó dùng Jacobian sai phân trung tâm. Bộ giải này không gọi hàm dựng Ybus, hàm Jacobian hoặc hàm giải Newton của chương trình chính.

Với dung sai bộ giải chính 1e-11 p.u., sai lệch điện áp phức lớn nhất giữa hai cách giải là **3.46 × 10⁻¹⁵ p.u.** trong môi trường nêu trên. Không chạy MATLAB/MATPOWER; chỉ sử dụng [dữ liệu case9 công bố bởi MATPOWER](https://matpower.org/docs/ref/matpower6.0/case9.html).

## Các lần chạy mẫu

| Dữ liệu | Bước Newton | Lượt giải | Sai lệch cuối (p.u.) | Tổn thất P (MW) |
|---|---:|---:|---:|---:|
| Lưới 3 nút | 3 | 1 | 6.370e-10 | 2.745173 |
| Lưới 9 nút | 4 | 1 | 5.462e-14 | 4.954702 |
| Lưới 3 nút, PV chạm Qmax | 6 | 2 | 2.198e-11 | 2.698672 |

Kết quả chi tiết và lịch sử sai lệch có trong thư mục `results/`. Số chữ số cuối có thể thay đổi theo NumPy và thư viện đại số tuyến tính của máy.

## Phần chưa được kiểm chứng

- Giao diện Tkinter: đã kiểm tra cú pháp và nhập mô-đun, chưa kiểm tra trực quan hoặc thao tác cửa sổ vì môi trường không có màn hình đồ họa.
- Tệp khởi chạy `.bat`: chưa chạy trên Windows.
- Chưa đánh giá hiệu năng lưới hàng nghìn nút, trường hợp gần sụp đổ điện áp hoặc mô hình thiết bị ngoài phạm vi ghi trong hướng dẫn.

Kiểm thử xác nhận các trường hợp đã nêu, không chứng minh hội tụ với mọi cấu hình lưới. Hãy kiểm tra dữ liệu cơ sở, dấu công suất và cảnh báo trước khi diễn giải kết quả cho lưới cụ thể.
