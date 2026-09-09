"""Mô-đun phân tích sự cố N-1 (N-1 Contingency Analysis) cho hệ thống điện.

Tự động giả lập cô lập (trip) từng đường dây và máy biến áp trong lưới điện,
đánh giá độ ổn định, kiểm tra quá tải và sụt áp sau sự cố, và xếp hạng
mức độ nguy hiểm theo Chỉ số Mức độ Nghiêm trọng (Performance Index - PI).
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional

from powerflow import CaseError, PowerFlowError, solve_power_flow, validate_case


def run_n1_contingency_analysis(
    base_case: Dict[str, Any],
    tolerance: float = 1e-6,
    max_iterations: int = 40,
    enforce_q_limits: bool = True,
    v_min_threshold: float = 0.95,
    v_max_threshold: float = 1.05,
    loading_warn_threshold: float = 80.0,
    loading_crit_threshold: float = 100.0,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> Dict[str, Any]:
    """Thực hiện quét toàn bộ các kịch bản sự cố N-1 trên tất cả các nhánh.

    Args:
        base_case: Dữ liệu lưới điện gốc.
        tolerance: Dung sai hội tụ trào lưu công suất.
        max_iterations: Số bước lặp tối đa.
        enforce_q_limits: Kiểm soát giới hạn phát công suất phản kháng của máy phát.
        v_min_threshold: Ngưỡng điện áp tối thiểu an toàn (p.u.).
        v_max_threshold: Ngưỡng điện áp tối đa an toàn (p.u.).
        loading_warn_threshold: Ngưỡng % mang tải cảnh báo (thường 80%).
        loading_crit_threshold: Ngưỡng % mang tải nguy cấp / quá tải (100%).
        progress_callback: Hàm callback nhận (current, total, branch_id) để cập nhật thanh tiến trình.

    Returns:
        Dict chứa tổng kết phân tích N-1 và danh sách kịch bản đã được sắp xếp theo mức độ nghiêm trọng.
    """
    branches = base_case.get("branches", [])
    active_branches = [br for br in branches if br.get("status", True)]
    total_contingencies = len(active_branches)

    results: List[Dict[str, Any]] = []
    secure_count = 0
    warning_count = 0
    critical_count = 0

    for idx, branch in enumerate(active_branches, start=1):
        branch_id = str(branch.get("id", f"B{idx}"))
        fb = str(branch.get("from_bus", ""))
        tb = str(branch.get("to_bus", ""))

        if progress_callback:
            progress_callback(idx, total_contingencies, branch_id)

        # Tạo bản sao lưới với nhánh này bị cắt (status = False)
        case_clone = copy.deepcopy(base_case)
        for br in case_clone.get("branches", []):
            if str(br.get("id")) == branch_id:
                br["status"] = False
                break

        record: Dict[str, Any] = {
            "branch_id": branch_id,
            "from_bus": fb,
            "to_bus": tb,
            "converged": False,
            "status_text": "",
            "severity": "SECURE",
            "pi_score": 0.0,
            "max_loading": 0.0,
            "worst_loading_branch": "—",
            "min_voltage": 1.0,
            "worst_voltage_bus": "—",
            "overloaded_count": 0,
            "voltage_violation_count": 0,
            "detail_message": ""
        }

        try:
            # Kiểm tra xem việc cắt nhánh có gây đảo điện thiếu SLACK không
            validate_case(case_clone)
            # Giải trào lưu công suất sau sự cố
            pf_res = solve_power_flow(
                case_clone,
                tolerance=tolerance,
                max_iterations=max_iterations,
                enforce_q_limits=enforce_q_limits
            )

            record["converged"] = True
            record["iterations"] = pf_res["iterations"]

            # Phân tích mức mang tải các đường dây còn lại
            max_loading = 0.0
            worst_loading_br = "—"
            overloads = 0
            warnings_list = []
            pi_branch_term = 0.0

            for br in pf_res["branches"]:
                if not br.get("status", True):
                    continue
                load_pct = br.get("loading_percent")
                if load_pct is not None:
                    ratio = load_pct / 100.0
                    pi_branch_term += ratio ** 4  # Số mũ bậc 4 làm nổi bật đường dây quá tải
                    if load_pct > max_loading:
                        max_loading = load_pct
                        worst_loading_br = str(br.get("id"))
                    if load_pct >= loading_crit_threshold:
                        overloads += 1
                        warnings_list.append(f"Nhánh {br.get('id')} quá tải {load_pct:.1f}%")
                    elif load_pct >= loading_warn_threshold:
                        warnings_list.append(f"Nhánh {br.get('id')} mang tải cao {load_pct:.1f}%")

            # Phân tích điện áp các nút
            min_v = 2.0
            max_v = 0.0
            worst_v_bus = "—"
            v_violations = 0
            pi_voltage_term = 0.0

            for b in pf_res["buses"]:
                vm = b.get("vm_pu", 1.0)
                b_id = str(b.get("id"))
                dev = abs(vm - 1.0) / 0.1
                pi_voltage_term += dev ** 2

                if vm < min_v:
                    min_v = vm
                    worst_v_bus = b_id
                if vm > max_v:
                    max_v = vm

                if vm < v_min_threshold:
                    v_violations += 1
                    warnings_list.append(f"Nút {b_id} sụt áp U = {vm:.4f} pu")
                elif vm > v_max_threshold:
                    v_violations += 1
                    warnings_list.append(f"Nút {b_id} quá áp U = {vm:.4f} pu")

            # Chỉ số mức độ nghiêm trọng PI
            pi_total = pi_branch_term + pi_voltage_term
            record["pi_score"] = round(pi_total, 2)
            record["max_loading"] = round(max_loading, 1)
            record["worst_loading_branch"] = worst_loading_br
            record["min_voltage"] = round(min_v, 4)
            record["worst_voltage_bus"] = worst_v_bus
            record["overloaded_count"] = overloads
            record["voltage_violation_count"] = v_violations

            # Xếp loại mức độ nghiêm trọng
            if overloads > 0 or min_v < 0.90:
                record["severity"] = "CRITICAL"
                record["status_text"] = "Nguy cấp"
                critical_count += 1
            elif max_loading >= loading_warn_threshold or v_violations > 0:
                record["severity"] = "WARNING"
                record["status_text"] = "Cảnh báo"
                warning_count += 1
            else:
                record["severity"] = "SECURE"
                record["status_text"] = "An toàn"
                secure_count += 1

            record["detail_message"] = "; ".join(warnings_list) if warnings_list else "Vận hành bình thường trong giới hạn an toàn."

        except CaseError as exc:
            # Nhánh cắt tạo thành đảo điện không có nút cân bằng
            record["converged"] = False
            record["severity"] = "CRITICAL"
            record["status_text"] = "Rã lưới / Đảo điện"
            record["pi_score"] = 9999.0
            record["detail_message"] = f"Gây mất kết nối / Đảo điện: {exc}"
            critical_count += 1

        except PowerFlowError as exc:
            # Mất ổn định điện áp / Bộ giải phân kỳ
            record["converged"] = False
            record["severity"] = "CRITICAL"
            record["status_text"] = "Mất ổn định / Phân kỳ"
            record["pi_score"] = 8888.0
            record["detail_message"] = f"Bộ giải không hội tụ sau {max_iterations} bước: {exc}"
            critical_count += 1

        except Exception as exc:
            record["converged"] = False
            record["severity"] = "CRITICAL"
            record["status_text"] = "Lỗi tính toán"
            record["pi_score"] = 7777.0
            record["detail_message"] = str(exc)
            critical_count += 1

        results.append(record)

    # Sắp xếp kịch bản theo thứ tự PI giảm dần (nguy hiểm nhất lên đầu)
    results.sort(key=lambda r: r["pi_score"], reverse=True)

    # Đánh giá chỉ số an toàn toàn hệ thống N-1 Compliance
    n1_secure = (critical_count == 0)

    worst_contingency = results[0]["branch_id"] if results else "—"

    return {
        "case_name": base_case.get("name", "Lưới điện"),
        "total_contingencies": total_contingencies,
        "secure_count": secure_count,
        "warning_count": warning_count,
        "critical_count": critical_count,
        "n1_compliant": n1_secure,
        "worst_contingency": worst_contingency,
        "contingencies": results
    }
