"""Mô-đun nhập/xuất dữ liệu lưới điện từ Excel (.xlsx) và CSV.

Hỗ trợ tự động nhận diện tên cột tiếng Anh / tiếng Việt, chuyển đổi
hai chiều giữa file bảng tính và đối tượng dữ liệu lưới điện chuẩn.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from powerflow import CaseError

BUS_SYNONYMS = {
    "id": ["id", "ma_nut", "so_nut", "stt", "bus_id", "node_id", "bus_number", "nut"],
    "type": ["type", "loai", "loai_nut", "kieu_nut", "bus_type"],
    "vm_pu": ["vm_pu", "u_pu", "v_pu", "vm", "dien_ap", "dien_ap_pu", "dien_ap_u"],
    "va_deg": ["va_deg", "goc_deg", "goc_do", "va", "goc_pha", "delta", "theta"],
    "pd_mw": ["pd_mw", "p_tai", "pd", "p_load", "pl", "tai_p", "p_tieu_thu"],
    "qd_mvar": ["qd_mvar", "q_tai", "qd", "q_load", "ql", "tai_q", "q_tieu_thu"],
    "pg_mw": ["pg_mw", "p_phat", "pg", "p_gen", "phat_p", "p_nguon"],
    "qg_mvar": ["qg_mvar", "q_phat", "qg", "q_gen", "phat_q", "q_nguon"],
    "qmin_mvar": ["qmin_mvar", "qmin", "q_min", "qg_min"],
    "qmax_mvar": ["qmax_mvar", "qmax", "q_max", "qg_max"],
    "pmin_mw": ["pmin_mw", "pmin", "p_min", "pg_min"],
    "pmax_mw": ["pmax_mw", "pmax", "p_max", "pg_max"],
    "vmin_pu": ["vmin_pu", "vmin", "u_min", "umin_pu", "u_duoi"],
    "vmax_pu": ["vmax_pu", "vmax", "u_max", "umax_pu", "u_tren"],
    "base_kv": ["base_kv", "ubase_kv", "ubase", "u_co_so", "dien_ap_co_so"],
    "g_shunt_pu": ["g_shunt_pu", "g_shunt", "g_pu"],
    "b_shunt_pu": ["b_shunt_pu", "b_shunt", "b_pu"],
}

BRANCH_SYNONYMS = {
    "id": ["id", "ma_nhanh", "ten_nhanh", "line_id", "branch_id", "nhanh"],
    "from_bus": ["from_bus", "nut_dau", "dau_nut", "dau", "from", "nut_1", "f_bus"],
    "to_bus": ["to_bus", "nut_cuoi", "cuoi_nut", "cuoi", "to", "nut_2", "t_bus"],
    "r_pu": ["r_pu", "dien_tro", "r"],
    "x_pu": ["x_pu", "dien_khang", "x"],
    "b_pu": ["b_pu", "dung_dan", "b"],
    "tap": ["tap", "ty_so", "ty_so_k", "he_so_k", "k", "bien_ap"],
    "shift_deg": ["shift_deg", "goc_lech_pha", "goc_dich_pha", "shift", "lech_pha"],
    "rate_mva": ["rate_mva", "dinh_muc", "s_dm", "cong_suat_dm", "rate"],
    "status": ["status", "dong_cat", "trang_thai", "dong", "status_branch"],
}


def _clean_id(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        if isinstance(val, float) and not val.is_integer():
            return str(val).strip()
        return str(int(val))
    s = str(val).strip()
    if s.endswith(".0"):
        try:
            return str(int(float(s)))
        except ValueError:
            pass
    return s


def _clean_str(text: Any) -> str:
    s = str(text).strip().lower()
    trans = str.maketrans(
        "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ",
        "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"
    )
    return s.translate(trans)


def _match_column(col_name: Any, synonyms: Dict[str, List[str]]) -> Optional[str]:
    col_str = str(col_name).strip()
    if not col_str:
        return None

    # 0. Nếu trong tên cột có ngoặc đơn mã trường như (id), (type), (vm_pu)...
    paren = re.search(r"\(([\w_]+)\)", col_str)
    if paren:
        tag = _clean_str(paren.group(1))
        for canonical, aliases in synonyms.items():
            if tag == canonical or tag in aliases:
                return canonical

    clean = _clean_str(col_str)
    clean_norm = re.sub(r"[^\w\s]", " ", clean)
    clean_norm = "_".join(clean_norm.split())

    # 1. Khớp chính xác tên chuẩn hoặc alias
    for canonical, aliases in synonyms.items():
        if clean_norm == canonical or clean_norm in aliases:
            return canonical

    # 2. Khớp cụm từ con dài nhất
    tokens = set(clean_norm.split("_"))
    for canonical, aliases in synonyms.items():
        if canonical in tokens:
            return canonical
        for a in aliases:
            if a in tokens:
                return canonical

    # 3. Khớp substring nếu alias dài >= 3 ký tự
    for canonical, aliases in synonyms.items():
        for a in aliases:
            if len(a) >= 4 and a in clean_norm:
                return canonical

    return None


def _to_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    if value is None or str(value).strip() in ("", "—", "None", "nan"):
        return default
    try:
        val_str = str(value).strip().replace(",", ".")
        return float(val_str)
    except (ValueError, TypeError):
        return default


def _to_bool(value: Any, default: bool = True) -> bool:
    if value is None or str(value).strip() in ("", "—", "None", "nan"):
        return default
    v = str(value).strip().lower()
    if v in ("1", "1.0", "true", "yes", "co", "đóng", "dong", "on"):
        return True
    if v in ("0", "0.0", "false", "no", "khong", "cắt", "cat", "off"):
        return False
    return default


def load_from_excel(path: Union[str, Path]) -> Dict[str, Any]:
    """Đọc dữ liệu lưới điện từ file Excel .xlsx."""
    if not HAS_OPENPYXL:
        raise CaseError("Cần thư viện openpyxl để đọc file Excel. Vui lòng cài đặt: pip install openpyxl")

    file_path = Path(path)
    if not file_path.exists():
        raise CaseError(f"Không tìm thấy file: {file_path}")

    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
    except Exception as exc:
        raise CaseError(f"Không đọc được file Excel: {exc}") from exc

    sheet_buses = None
    sheet_branches = None
    for sheet_name in wb.sheetnames:
        norm = _clean_str(sheet_name)
        if norm in ("buses", "nut", "danh_sach_nut", "bus"):
            sheet_buses = wb[sheet_name]
        elif norm in ("branches", "nhanh", "duong_day", "branch", "lines"):
            sheet_branches = wb[sheet_name]

    if sheet_buses is None:
        sheet_buses = wb.sheetnames[0] if wb.sheetnames else None
        sheet_buses = wb[sheet_buses] if sheet_buses else None

    if sheet_branches is None and len(wb.sheetnames) >= 2:
        sheet_branches = wb[wb.sheetnames[1]]

    if sheet_buses is None:
        raise CaseError("File Excel thiếu sheet danh sách nút ('Buses' hoặc 'Nut').")

    base_mva = 100.0
    case_name = file_path.stem

    for sheet in wb.worksheets:
        for r in range(1, min(5, sheet.max_row + 1)):
            for c in range(1, min(5, sheet.max_column + 1)):
                cell_val = _clean_str(sheet.cell(r, c).value or "")
                if "base_mva" in cell_val or "s_co_so" in cell_val:
                    next_val = sheet.cell(r, c + 1).value
                    parsed_base = _to_float(next_val, None)
                    if parsed_base and parsed_base > 0:
                        base_mva = parsed_base
                elif "ten_luoi" in cell_val or "name" in cell_val:
                    next_val = sheet.cell(r, c + 1).value
                    if next_val:
                        case_name = str(next_val).strip()

    # Đọc Bảng Nút
    buses_list = []
    rows = list(sheet_buses.iter_rows(values_only=True))
    if not rows:
        raise CaseError("Sheet danh sách nút trống.")

    header_idx = -1
    col_map = {}
    for idx, row in enumerate(rows):
        matched = {}
        for col_i, val in enumerate(row):
            if val is not None:
                canonical = _match_column(str(val), BUS_SYNONYMS)
                if canonical:
                    matched[col_i] = canonical
        if "id" in matched.values() and ("type" in matched.values() or len(matched) >= 3):
            header_idx = idx
            col_map = matched
            break

    if header_idx == -1:
        raise CaseError("Không nhận diện được tiêu đề các cột trong sheet Nút.")

    for row in rows[header_idx + 1:]:
        if not any(row):
            continue
        row_dict = {}
        for col_i, canonical in col_map.items():
            if col_i < len(row):
                row_dict[canonical] = row[col_i]

        bus_id = _clean_id(row_dict.get("id"))
        if not bus_id or bus_id.lower() == "none":
            continue

        raw_type = str(row_dict.get("type") or "PQ").strip().upper()
        if raw_type in ("1", "SLACK", "NUT_CAN_BANG", "CAN_BANG"):
            bus_type = "SLACK"
        elif raw_type in ("2", "PV", "MAY_PHAT"):
            bus_type = "PV"
        else:
            bus_type = "PQ"

        bus_data = {
            "id": bus_id,
            "type": bus_type,
            "vm_pu": _to_float(row_dict.get("vm_pu"), 1.0),
            "va_deg": _to_float(row_dict.get("va_deg"), 0.0),
            "pd_mw": _to_float(row_dict.get("pd_mw"), 0.0),
            "qd_mvar": _to_float(row_dict.get("qd_mvar"), 0.0),
            "pg_mw": _to_float(row_dict.get("pg_mw"), 0.0),
            "qg_mvar": _to_float(row_dict.get("qg_mvar"), 0.0),
        }

        for opt in ("qmin_mvar", "qmax_mvar", "pmin_mw", "pmax_mw", "vmin_pu", "vmax_pu", "base_kv", "g_shunt_pu", "b_shunt_pu"):
            if opt in row_dict and row_dict[opt] is not None:
                val = _to_float(row_dict[opt], None)
                if val is not None:
                    bus_data[opt] = val

        buses_list.append(bus_data)

    # Đọc Bảng Nhánh
    branches_list = []
    if sheet_branches is not None:
        b_rows = list(sheet_branches.iter_rows(values_only=True))
        b_header_idx = -1
        b_col_map = {}
        for idx, row in enumerate(b_rows):
            matched = {}
            for col_i, val in enumerate(row):
                if val is not None:
                    canonical = _match_column(str(val), BRANCH_SYNONYMS)
                    if canonical:
                        matched[col_i] = canonical
            if "from_bus" in matched.values() and "to_bus" in matched.values():
                b_header_idx = idx
                b_col_map = matched
                break

        if b_header_idx != -1:
            for row in b_rows[b_header_idx + 1:]:
                if not any(row):
                    continue
                row_dict = {}
                for col_i, canonical in b_col_map.items():
                    if col_i < len(row):
                        row_dict[canonical] = row[col_i]

                f_bus = _clean_id(row_dict.get("from_bus"))
                t_bus = _clean_id(row_dict.get("to_bus"))
                if not f_bus or not t_bus or f_bus.lower() == "none" or t_bus.lower() == "none":
                    continue

                raw_br_id = row_dict.get("id")
                br_id = _clean_id(raw_br_id) if raw_br_id is not None and str(raw_br_id).strip() else f"L{f_bus}_{t_bus}"
                branch_data = {
                    "id": br_id,
                    "from_bus": f_bus,
                    "to_bus": t_bus,
                    "r_pu": _to_float(row_dict.get("r_pu"), 0.0),
                    "x_pu": _to_float(row_dict.get("x_pu"), 0.1),
                    "b_pu": _to_float(row_dict.get("b_pu"), 0.0),
                    "tap": _to_float(row_dict.get("tap"), 1.0),
                    "shift_deg": _to_float(row_dict.get("shift_deg"), 0.0),
                    "status": _to_bool(row_dict.get("status"), True),
                }
                if "rate_mva" in row_dict and row_dict["rate_mva"] is not None:
                    rate = _to_float(row_dict["rate_mva"], None)
                    if rate and rate > 0:
                        branch_data["rate_mva"] = rate

                branches_list.append(branch_data)

    return {
        "name": case_name,
        "base_mva": base_mva,
        "buses": buses_list,
        "branches": branches_list
    }


def export_case_to_excel(case: Dict[str, Any], path: Union[str, Path]) -> None:
    """Xuất đối tượng dữ liệu lưới điện ra file Excel .xlsx 2 sheet định dạng chuẩn."""
    if not HAS_OPENPYXL:
        raise CaseError("Cần thư viện openpyxl để xuất file Excel. Vui lòng cài đặt: pip install openpyxl")

    wb = openpyxl.Workbook()
    ws_buses = wb.active
    ws_buses.title = "Buses"
    ws_branches = wb.create_sheet(title="Branches")

    header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="147D73", end_color="147D73", fill_type="solid")
    border_thin = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0")
    )
    align_center = Alignment(horizontal="center", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    # Sheet Buses
    bus_headers = [
        ("id", "Mã nút (id)"),
        ("type", "Loại nút (type)"),
        ("vm_pu", "Điện áp (vm_pu)"),
        ("va_deg", "Góc áp (va_deg)"),
        ("pd_mw", "Tải P (pd_mw)"),
        ("qd_mvar", "Tải Q (qd_mvar)"),
        ("pg_mw", "Phát P (pg_mw)"),
        ("qg_mvar", "Phát Q (qg_mvar)"),
        ("qmin_mvar", "Qmin (qmin_mvar)"),
        ("qmax_mvar", "Qmax (qmax_mvar)"),
        ("vmin_pu", "Umin (vmin_pu)"),
        ("vmax_pu", "Umax (vmax_pu)"),
        ("base_kv", "U cơ sở (base_kv)")
    ]

    for col_i, (_key, label) in enumerate(bus_headers, start=1):
        cell = ws_buses.cell(row=1, column=col_i, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center

    for row_i, bus in enumerate(case.get("buses", []), start=2):
        for col_i, (key, _) in enumerate(bus_headers, start=1):
            val = bus.get(key)
            cell = ws_buses.cell(row=row_i, column=col_i, value=val)
            cell.border = border_thin
            if key in ("id", "type"):
                cell.alignment = align_center
            else:
                cell.alignment = align_right

    # Sheet Branches
    branch_headers = [
        ("id", "Mã nhánh (id)"),
        ("from_bus", "Nút đầu (from_bus)"),
        ("to_bus", "Nút cuối (to_bus)"),
        ("r_pu", "Điện trở R (r_pu)"),
        ("x_pu", "Điện kháng X (x_pu)"),
        ("b_pu", "Dung dẫn B (b_pu)"),
        ("tap", "Tỷ số MBA (tap)"),
        ("shift_deg", "Góc lệch pha (shift_deg)"),
        ("rate_mva", "Định mức (rate_mva)"),
        ("status", "Đóng/Cắt (status)")
    ]

    for col_i, (_key, label) in enumerate(branch_headers, start=1):
        cell = ws_branches.cell(row=1, column=col_i, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center

    for row_i, br in enumerate(case.get("branches", []), start=2):
        for col_i, (key, _) in enumerate(branch_headers, start=1):
            if key == "status":
                val = 1 if br.get("status", True) else 0
            else:
                val = br.get(key)
            cell = ws_branches.cell(row=row_i, column=col_i, value=val)
            cell.border = border_thin
            if key in ("id", "from_bus", "to_bus", "status"):
                cell.alignment = align_center
            else:
                cell.alignment = align_right

    # Sheet Thông tin chung
    ws_info = wb.create_sheet(title="Info")
    ws_info.cell(row=1, column=1, value="Tên lưới (name)")
    ws_info.cell(row=1, column=2, value=str(case.get("name", "Lưới điện")))
    ws_info.cell(row=2, column=1, value="Công suất cơ sở MVA (base_mva)")
    ws_info.cell(row=2, column=2, value=float(case.get("base_mva", 100.0)))
    ws_info.cell(row=1, column=1).font = Font(name="Segoe UI", size=10, bold=True)
    ws_info.cell(row=2, column=1).font = Font(name="Segoe UI", size=10, bold=True)
    ws_info.column_dimensions["A"].width = 30
    ws_info.column_dimensions["B"].width = 30

    for ws in (ws_buses, ws_branches):
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(14, max_len + 3)

    wb.save(path)


def create_sample_excel_template(path: Union[str, Path]) -> None:
    """Tạo một file mẫu Excel chuẩn có sẵn chú thích và dữ liệu mẫu 3 nút."""
    sample_case = {
        "name": "Lưới điện mẫu chuẩn Excel",
        "base_mva": 100,
        "buses": [
            {"id": "1", "type": "SLACK", "vm_pu": 1.05, "va_deg": 0.0, "pd_mw": 0, "qd_mvar": 0, "pg_mw": 0, "qg_mvar": 0, "vmin_pu": 0.9, "vmax_pu": 1.1, "base_kv": 110},
            {"id": "2", "type": "PV", "vm_pu": 1.04, "va_deg": 0.0, "pd_mw": 20, "qd_mvar": 10, "pg_mw": 40, "qg_mvar": 0, "qmin_mvar": -30, "qmax_mvar": 50, "vmin_pu": 0.9, "vmax_pu": 1.1, "base_kv": 110},
            {"id": "3", "type": "PQ", "vm_pu": 1.0, "va_deg": 0.0, "pd_mw": 50, "qd_mvar": 25, "pg_mw": 0, "qg_mvar": 0, "vmin_pu": 0.9, "vmax_pu": 1.1, "base_kv": 110},
        ],
        "branches": [
            {"id": "L12", "from_bus": "1", "to_bus": "2", "r_pu": 0.02, "x_pu": 0.08, "b_pu": 0.04, "tap": 1.0, "shift_deg": 0.0, "rate_mva": 100, "status": 1},
            {"id": "L13", "from_bus": "1", "to_bus": "3", "r_pu": 0.03, "x_pu": 0.12, "b_pu": 0.05, "tap": 1.0, "shift_deg": 0.0, "rate_mva": 100, "status": 1},
            {"id": "L23", "from_bus": "2", "to_bus": "3", "r_pu": 0.025, "x_pu": 0.10, "b_pu": 0.04, "tap": 1.0, "shift_deg": 0.0, "rate_mva": 100, "status": 1},
        ]
    }
    export_case_to_excel(sample_case, path)


def load_from_csv(path: Union[str, Path]) -> Dict[str, Any]:
    """Đọc dữ liệu từ file CSV chứa các khối dữ liệu Nút và Nhánh."""
    file_path = Path(path)
    if not file_path.exists():
        raise CaseError(f"Không tìm thấy file CSV: {file_path}")

    content = file_path.read_text(encoding="utf-8-sig")
    lines = content.splitlines()

    buses = []
    branches = []
    mode = "BUSES"
    bus_map = {}
    branch_map = {}

    for line in lines:
        line_str = line.strip()
        if not line_str or line_str.startswith("#"):
            c_line = _clean_str(line_str)
            if "nhanh" in c_line or "branch" in c_line:
                mode = "BRANCHES"
            continue

        parts = [p.strip() for p in (line_str.split(";") if ";" in line_str else line_str.split(","))]
        if not any(parts):
            continue

        matched_bus = {i: _match_column(p, BUS_SYNONYMS) for i, p in enumerate(parts) if _match_column(p, BUS_SYNONYMS)}
        matched_branch = {i: _match_column(p, BRANCH_SYNONYMS) for i, p in enumerate(parts) if _match_column(p, BRANCH_SYNONYMS)}

        if "from_bus" in matched_branch.values() and "to_bus" in matched_branch.values():
            mode = "BRANCHES"
            branch_map = matched_branch
            continue
        elif "id" in matched_bus.values() and ("type" in matched_bus.values() or len(matched_bus) >= 3):
            mode = "BUSES"
            bus_map = matched_bus
            continue

        if mode == "BUSES" and bus_map:
            row_dict = {col: parts[i] for i, col in bus_map.items() if i < len(parts)}
            b_id = _clean_id(row_dict.get("id"))
            if b_id:
                raw_type = str(row_dict.get("type") or "PQ").strip().upper()
                bus_type = "SLACK" if raw_type in ("1", "SLACK") else ("PV" if raw_type in ("2", "PV") else "PQ")
                buses.append({
                    "id": b_id,
                    "type": bus_type,
                    "vm_pu": _to_float(row_dict.get("vm_pu"), 1.0),
                    "va_deg": _to_float(row_dict.get("va_deg"), 0.0),
                    "pd_mw": _to_float(row_dict.get("pd_mw"), 0.0),
                    "qd_mvar": _to_float(row_dict.get("qd_mvar"), 0.0),
                    "pg_mw": _to_float(row_dict.get("pg_mw"), 0.0),
                    "qg_mvar": _to_float(row_dict.get("qg_mvar"), 0.0),
                })
        elif mode == "BRANCHES" and branch_map:
            row_dict = {col: parts[i] for i, col in branch_map.items() if i < len(parts)}
            f_b = _clean_id(row_dict.get("from_bus"))
            t_b = _clean_id(row_dict.get("to_bus"))
            if f_b and t_b:
                raw_br_id = row_dict.get("id")
                br_id = _clean_id(raw_br_id) if raw_br_id is not None and str(raw_br_id).strip() else f"L{f_b}_{t_b}"
                branches.append({
                    "id": br_id,
                    "from_bus": f_b,
                    "to_bus": t_b,
                    "r_pu": _to_float(row_dict.get("r_pu"), 0.0),
                    "x_pu": _to_float(row_dict.get("x_pu"), 0.1),
                    "b_pu": _to_float(row_dict.get("b_pu"), 0.0),
                    "tap": _to_float(row_dict.get("tap"), 1.0),
                    "shift_deg": _to_float(row_dict.get("shift_deg"), 0.0),
                    "status": _to_bool(row_dict.get("status"), True),
                })

    return {
        "name": file_path.stem,
        "base_mva": 100.0,
        "buses": buses,
        "branches": branches
    }


def export_full_results_to_excel(result: Dict[str, Any], path: Union[str, Path]) -> None:
    """Xuất toàn bộ kết quả tính toán trào lưu công suất ra file Excel 4 sheet chuyên nghiệp."""
    if not HAS_OPENPYXL:
        raise CaseError("Cần thư viện openpyxl để xuất file Excel. Vui lòng cài đặt: pip install openpyxl")

    wb = openpyxl.Workbook()
    ws_summary = wb.active
    ws_summary.title = "Tổng quan & KPIs"
    ws_buses = wb.create_sheet(title="Điện áp nút")
    ws_branches = wb.create_sheet(title="Công suất nhánh")
    ws_warnings = wb.create_sheet(title="Cảnh báo & Vi phạm")

    # Font và Style chuẩn
    font_title = Font(name="Segoe UI", size=13, bold=True, color="0D9488")
    font_section = Font(name="Segoe UI", size=11, bold=True, color="0F172A")
    font_header = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    font_bold = Font(name="Segoe UI", size=10, bold=True)
    font_regular = Font(name="Segoe UI", size=10)
    font_alert = Font(name="Segoe UI", size=10, bold=True, color="DC2626")

    fill_teal = PatternFill(start_color="0D9488", end_color="0D9488", fill_type="solid")
    fill_slate = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
    fill_warn = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    fill_crit = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")

    border_thin = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0")
    )
    align_center = Alignment(horizontal="center", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")

    # ==================== SHEET 1: TỔNG QUAN & KPIS ====================
    ws_summary.cell(row=1, column=1, value="BÁO CÁO PHÂN TÍCH CHẾ ĐỘ XÁC LẬP LƯỚI ĐIỆN").font = font_title
    ws_summary.cell(row=2, column=1, value=f"Tên hệ thống: {result.get('name', 'Lưới điện')}").font = font_regular

    meta_items = [
        ("Trạng thái hội tụ:", "Hội tụ thành công" if result.get("converged") else "Không hội tụ"),
        ("Số bước lặp Newton:", f"{result.get('iterations', 0)} bước ({result.get('passes', 1)} lượt giải)"),
        ("Sai lệch cực đại:", f"{result.get('max_mismatch_pu', 0):.3e} p.u."),
        ("Công suất cơ sở (Sbase):", f"{result.get('base_mva', 100):g} MVA"),
        ("Số lượng nút:", len(result.get("buses", []))),
        ("Số lượng nhánh:", len(result.get("branches", [])))
    ]
    for r_idx, (lbl, val) in enumerate(meta_items, start=4):
        ws_summary.cell(row=r_idx, column=1, value=lbl).font = font_bold
        ws_summary.cell(row=r_idx, column=2, value=str(val)).font = font_regular

    # Bảng chỉ số KPI
    ws_summary.cell(row=11, column=1, value="CHỈ SỐ CÂN BẰNG CÔNG SUẤT TOÀN HỆ THỐNG").font = font_section
    kpi_headers = ["Chỉ số", "Công suất tác dụng P (MW)", "Công suất phản kháng Q (Mvar)", "Ghi chú"]
    for c_idx, h in enumerate(kpi_headers, start=1):
        cell = ws_summary.cell(row=12, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_teal
        cell.alignment = align_center

    s = result.get("summary", {})
    pg_tot = s.get("pg_total_mw", 0.0)
    qg_tot = s.get("qg_total_mvar", 0.0)
    pd_tot = s.get("pd_total_mw", 0.0)
    qd_tot = s.get("qd_total_mvar", 0.0)
    p_loss = s.get("p_total_loss_mw", 0.0)
    q_loss = s.get("q_network_net_mvar", 0.0)
    loss_pct = (p_loss / pg_tot * 100.0) if pg_tot > 0 else 0.0
    s_tot = math.hypot(pg_tot, qg_tot)
    cos_phi = (pg_tot / s_tot) if s_tot > 0 else 1.0

    kpi_rows = [
        ("Tổng công suất phát:", pg_tot, qg_tot, "Tổng từ tất cả các nút SLACK và PV"),
        ("Tổng phụ tải tiêu thụ:", pd_tot, qd_tot, "Tổng công suất tải P, Q"),
        ("Tổng tổn thất lưới điện:", p_loss, q_loss, f"Tỷ lệ tổn thất: {loss_pct:.2f}% tổng công suất phát"),
        ("Hệ số công suất hệ thống (cosφ):", round(cos_phi, 4), "—", "Hệ số công suất phát tổng thể"),
        ("Sai số cân bằng (Balance Error):", s.get("p_balance_error_mw", 0.0), s.get("q_balance_error_mvar", 0.0), "Sai số kiểm chứng định luật Kirchhoff")
    ]

    for r_idx, (title, p_val, q_val, note) in enumerate(kpi_rows, start=13):
        ws_summary.cell(row=r_idx, column=1, value=title).font = font_bold
        c_p = ws_summary.cell(row=r_idx, column=2, value=p_val)
        c_q = ws_summary.cell(row=r_idx, column=3, value=q_val)
        c_n = ws_summary.cell(row=r_idx, column=4, value=note)
        for c in (c_p, c_q, c_n):
            c.font = font_regular
            c.border = border_thin
        ws_summary.cell(row=r_idx, column=1).border = border_thin
        c_p.alignment = align_right
        c_q.alignment = align_right

    # ==================== SHEET 2: ĐIỆN ÁP NÚT ====================
    bus_cols = [
        ("id", "Mã nút"), ("type_final", "Loại nút"),
        ("vm_pu", "Điện áp (p.u.)"), ("va_deg", "Góc pha (độ)"),
        ("voltage_kv", "Điện áp dây (kV)"), ("pg_mw", "Phát P (MW)"),
        ("qg_mvar", "Phát Q (Mvar)"), ("pd_mw", "Tải P (MW)"),
        ("qd_mvar", "Tải Q (Mvar)")
    ]
    for c_idx, (_k, label) in enumerate(bus_cols, start=1):
        cell = ws_buses.cell(row=1, column=c_idx, value=label)
        cell.font = font_header
        cell.fill = fill_teal
        cell.alignment = align_center

    for r_idx, b in enumerate(result.get("buses", []), start=2):
        for c_idx, (key, _) in enumerate(bus_cols, start=1):
            val = b.get(key)
            cell = ws_buses.cell(row=r_idx, column=c_idx, value=val)
            cell.border = border_thin
            if key in ("id", "type_final"):
                cell.alignment = align_center
                cell.font = font_bold if key == "id" else font_regular
            else:
                cell.alignment = align_right
                cell.font = font_regular

            # Cảnh báo điện áp ngoài dải an toàn [0.95, 1.05]
            if key == "vm_pu" and val is not None:
                if val < 0.95 or val > 1.05:
                    cell.fill = fill_warn
                    cell.font = font_alert

    # ==================== SHEET 3: CÔNG SUẤT NHÁNH ====================
    branch_cols = [
        ("id", "Mã nhánh"), ("from_bus", "Nút đầu"), ("to_bus", "Nút cuối"),
        ("status", "Đóng/Cắt"), ("p_from_mw", "Pf (MW)"), ("q_from_mvar", "Qf (Mvar)"),
        ("p_to_mw", "Pt (MW)"), ("q_to_mvar", "Qt (Mvar)"), ("p_loss_mw", "ΔP (MW)"),
        ("i_from_ka", "If (kA)"), ("i_to_ka", "It (kA)"), ("loading_percent", "Mang tải (%)")
    ]
    for c_idx, (_k, label) in enumerate(branch_cols, start=1):
        cell = ws_branches.cell(row=1, column=c_idx, value=label)
        cell.font = font_header
        cell.fill = fill_slate
        cell.alignment = align_center

    for r_idx, br in enumerate(result.get("branches", []), start=2):
        for c_idx, (key, _) in enumerate(branch_cols, start=1):
            val = br.get(key)
            if key == "status":
                val = "Đóng" if val else "Cắt"
            cell = ws_branches.cell(row=r_idx, column=c_idx, value=val)
            cell.border = border_thin
            if key in ("id", "from_bus", "to_bus", "status"):
                cell.alignment = align_center
                cell.font = font_bold if key == "id" else font_regular
            else:
                cell.alignment = align_right
                cell.font = font_regular

            # Tô màu cảnh báo mức mang tải
            if key == "loading_percent" and val is not None:
                if val >= 100.0:
                    cell.fill = fill_crit
                    cell.font = font_alert
                elif val >= 80.0:
                    cell.fill = fill_warn

    # ==================== SHEET 4: CẢNH BÁO & VI PHẠM ====================
    ws_warnings.cell(row=1, column=1, value="DANH SÁCH CẢNH BÁO VẬN HÀNH & VI PHẠM").font = font_section
    warn_headers = ["STT", "Phân loại", "Phần tử", "Nội dung cảnh báo"]
    for c_idx, h in enumerate(warn_headers, start=1):
        cell = ws_warnings.cell(row=2, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_teal
        cell.alignment = align_center

    warn_rows = []
    w_idx = 1

    # Quá tải đường dây
    for br in result.get("branches", []):
        load_pct = br.get("loading_percent")
        if load_pct is not None and load_pct >= 80.0:
            status_desc = "QUÁ TẢI NGUY CẤP (>100%)" if load_pct >= 100.0 else "MANG TẢI CAO (80-100%)"
            warn_rows.append((w_idx, status_desc, f"Nhánh {br.get('id')}", f"Mức mang tải đạt {load_pct:.1f}% định mức"))
            w_idx += 1

    # Vi phạm điện áp
    for b in result.get("buses", []):
        vm = b.get("vm_pu")
        if vm is not None and (vm < 0.95 or vm > 1.05):
            desc = "SỤT ÁP (<0.95 pu)" if vm < 0.95 else "QUÁ ÁP (>1.05 pu)"
            warn_rows.append((w_idx, desc, f"Nút {b.get('id')}", f"Điện áp U = {vm:.4f} p.u. (ngoài khoảng an toàn)"))
            w_idx += 1

    # Cảnh báo từ bộ giải
    for w in result.get("warnings", []):
        warn_rows.append((w_idx, "Bộ giải / Chuyển nút", "Hệ thống", str(w)))
        w_idx += 1

    if not warn_rows:
        ws_warnings.cell(row=3, column=1, value="1")
        ws_warnings.cell(row=3, column=2, value="An toàn")
        ws_warnings.cell(row=3, column=3, value="Toàn hệ thống")
        ws_warnings.cell(row=3, column=4, value="Không có vi phạm điện áp hay quá tải đường dây.")
    else:
        for r_idx, (stt, cat, comp, msg) in enumerate(warn_rows, start=3):
            c1 = ws_warnings.cell(row=r_idx, column=1, value=stt)
            c2 = ws_warnings.cell(row=r_idx, column=2, value=cat)
            c3 = ws_warnings.cell(row=r_idx, column=3, value=comp)
            c4 = ws_warnings.cell(row=r_idx, column=4, value=msg)
            for c in (c1, c2, c3, c4):
                c.border = border_thin
                c.font = font_regular
            c1.alignment = align_center
            c2.alignment = align_center
            if "QUÁ TẢI" in cat or "SỤT ÁP" in cat:
                c2.fill = fill_warn
                c2.font = font_bold

    # Tự động căn chỉnh độ rộng các cột
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(13, min(50, max_len + 3))

    wb.save(path)

