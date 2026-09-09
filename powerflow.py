"""Trào lưu công suất AC ba pha cân bằng bằng Newton–Raphson.

Công suất MW/Mvar là tổng ba pha; thông số mạng dùng cùng cơ sở p.u.
Chỉ cần NumPy. Có thể dùng qua CLI hoặc gọi solve_power_flow(case).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


class CaseError(ValueError):
    """Dữ liệu lưới không hợp lệ."""


class PowerFlowError(RuntimeError):
    """Không tìm được nghiệm đạt dung sai; không xuất nghiệm là hội tụ."""

    def __init__(self, message: str, history: list[dict] | None = None):
        super().__init__(message)
        self.history = history or []


@dataclass(frozen=True)
class Bus:
    id: str
    type: str
    vm_pu: float = 1.0
    va_deg: float = 0.0
    pg_mw: float = 0.0
    qg_mvar: float = 0.0
    pd_mw: float = 0.0
    qd_mvar: float = 0.0
    g_shunt_pu: float = 0.0
    b_shunt_pu: float = 0.0
    base_kv: float | None = None
    qmin_mvar: float | None = None
    qmax_mvar: float | None = None
    pmin_mw: float | None = None
    pmax_mw: float | None = None
    vmin_pu: float = 0.9
    vmax_pu: float = 1.1


@dataclass(frozen=True)
class Branch:
    id: str
    from_bus: str
    to_bus: str
    r_pu: float
    x_pu: float
    b_pu: float = 0.0
    tap: float = 1.0
    shift_deg: float = 0.0
    rate_mva: float | None = None
    status: bool = True


@dataclass(frozen=True)
class Network:
    name: str
    base_mva: float
    buses: tuple[Bus, ...]
    branches: tuple[Branch, ...]


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CaseError(f"{label}: phải là số, dùng dấu chấm thập phân.")
    try:
        answer = float(value)
    except (OverflowError, ValueError) as exc:
        raise CaseError(f"{label}: số ngoài phạm vi biểu diễn.") from exc
    if not math.isfinite(answer):
        raise CaseError(f"{label}: không nhận NaN hoặc vô cùng.")
    return answer


def _identifier(value: Any, label: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise CaseError(f"{label}: mã phải là chuỗi hoặc số nguyên.")
    if not str(value).strip():
        raise CaseError(f"{label}: mã không được rỗng.")
    return str(value).strip()


def _keys(row: dict, allowed: set[str], label: str) -> None:
    if not isinstance(row, dict):
        raise CaseError(f"{label}: phải là một đối tượng JSON.")
    extra = set(row) - allowed
    if extra:
        raise CaseError(f"{label}: trường không được hỗ trợ: {', '.join(sorted(map(str, extra)))}.")


def validate_case(data: dict) -> Network:
    """Chuẩn hóa dữ liệu và kiểm tra mỗi đảo điện có đúng một nút SLACK."""
    _keys(data, {"name", "description", "source", "base_mva", "buses", "branches"}, "Lưới")
    base = _number(data.get("base_mva", 100.0), "base_mva")
    if base <= 0:
        raise CaseError("base_mva phải lớn hơn 0.")
    if not isinstance(data.get("buses"), list) or not data["buses"]:
        raise CaseError("buses phải là danh sách nút không rỗng.")
    if not isinstance(data.get("branches"), list):
        raise CaseError("branches phải là danh sách, có thể rỗng cho một nút SLACK.")

    buses, ids = [], set()
    optional = {"base_kv", "qmin_mvar", "qmax_mvar", "pmin_mw", "pmax_mw"}
    defaults = Bus("", "PQ")
    for pos, row in enumerate(data["buses"], 1):
        label = f"Nút dòng {pos}"
        _keys(row, set(Bus.__dataclass_fields__), label)
        if "id" not in row or "type" not in row:
            raise CaseError(f"{label}: cần id và type.")
        key = _identifier(row["id"], label)
        if key in ids:
            raise CaseError(f"Trùng mã nút {key}.")
        ids.add(key)
        kind = str(row["type"]).strip().upper()
        if kind not in {"SLACK", "PV", "PQ"}:
            raise CaseError(f"Nút {key}: type phải là SLACK, PV hoặc PQ.")
        args = {"id": key, "type": kind}
        for field in set(Bus.__dataclass_fields__) - {"id", "type"}:
            value = row.get(field, getattr(defaults, field))
            args[field] = None if field in optional and value is None else _number(value, f"Nút {key}/{field}")
        bus = Bus(**args)
        if bus.vm_pu <= 0 or bus.vmin_pu <= 0 or bus.vmax_pu < bus.vmin_pu:
            raise CaseError(f"Nút {key}: cần vm_pu > 0 và 0 < vmin_pu <= vmax_pu.")
        if bus.base_kv is not None and bus.base_kv <= 0:
            raise CaseError(f"Nút {key}: base_kv phải lớn hơn 0.")
        if bus.g_shunt_pu < 0:
            raise CaseError(f"Nút {key}: g_shunt_pu không được âm.")
        for lo, hi in ((bus.qmin_mvar, bus.qmax_mvar), (bus.pmin_mw, bus.pmax_mw)):
            if lo is not None and hi is not None and lo > hi:
                raise CaseError(f"Nút {key}: giới hạn dưới lớn hơn giới hạn trên.")
        buses.append(bus)

    branches, branch_ids = [], set()
    defaults_branch = Branch("", "", "", 0.0, 0.0)
    adjacency = {key: set() for key in ids}
    for pos, row in enumerate(data["branches"], 1):
        label = f"Nhánh dòng {pos}"
        _keys(row, set(Branch.__dataclass_fields__), label)
        if not {"from_bus", "to_bus", "r_pu", "x_pu"} <= set(row):
            raise CaseError(f"{label}: cần from_bus, to_bus, r_pu, x_pu.")
        key = _identifier(row.get("id", f"L{pos}"), label)
        if key in branch_ids:
            raise CaseError(f"Trùng mã nhánh {key}.")
        branch_ids.add(key)
        f = _identifier(row["from_bus"], label)
        t = _identifier(row["to_bus"], label)
        if f not in ids or t not in ids or f == t:
            raise CaseError(f"Nhánh {key}: hai đầu phải là hai nút khác nhau, đã khai báo.")
        status = row.get("status", True)
        if not isinstance(status, (bool, int)) or status not in (0, 1):
            raise CaseError(f"Nhánh {key}: status phải là true/false hoặc 1/0.")
        args = {"id": key, "from_bus": f, "to_bus": t, "status": bool(status)}
        for field in set(Branch.__dataclass_fields__) - set(args):
            value = row.get(field, getattr(defaults_branch, field))
            args[field] = None if field == "rate_mva" and value is None else _number(value, f"Nhánh {key}/{field}")
        branch = Branch(**args)
        if branch.r_pu < 0 or branch.tap <= 0:
            raise CaseError(f"Nhánh {key}: cần r_pu >= 0 và tap > 0 (mặc định 1).")
        if branch.status and abs(complex(branch.r_pu, branch.x_pu)) <= 1e-12:
            raise CaseError(f"Nhánh {key}: tổng trở bằng hoặc quá gần 0; hãy gộp nút nối tắt.")
        if branch.rate_mva is not None and branch.rate_mva <= 0:
            raise CaseError(f"Nhánh {key}: rate_mva phải lớn hơn 0 hoặc null.")
        if branch.status:
            adjacency[f].add(t)
            adjacency[t].add(f)
        branches.append(branch)

    by_id = {bus.id: bus for bus in buses}
    remaining = set(ids)
    while remaining:
        start = min(remaining)
        island, pending = set(), [start]
        while pending:
            key = pending.pop()
            if key in island:
                continue
            island.add(key)
            pending.extend(adjacency[key] - island)
        remaining -= island
        slack_count = sum(by_id[key].type == "SLACK" for key in island)
        if slack_count != 1:
            raise CaseError(f"Đảo điện [{', '.join(sorted(island))}] có {slack_count} nút SLACK; cần đúng 1.")
    return Network(str(data.get("name", "Lưới điện")), base, tuple(buses), tuple(branches))


def build_ybus(network: Network) -> tuple[np.ndarray, list[tuple]]:
    """Mô hình π; biến áp lý tưởng t=tap*exp(j*shift) đặt ở đầu from_bus."""
    n = len(network.buses)
    index = {bus.id: i for i, bus in enumerate(network.buses)}
    ybus = np.zeros((n, n), dtype=complex)
    primitives = []
    for branch in network.branches:
        f, t = index[branch.from_bus], index[branch.to_bus]
        if branch.status:
            y = 1.0 / complex(branch.r_pu, branch.x_pu)
            ratio = branch.tap * np.exp(1j * np.deg2rad(branch.shift_deg))
            ytt = y + 0.5j * branch.b_pu
            yff = ytt / branch.tap**2
            yft, ytf = -y / ratio.conjugate(), -y / ratio
        else:
            yff = yft = ytf = ytt = 0j
        ybus[f, f] += yff
        ybus[f, t] += yft
        ybus[t, f] += ytf
        ybus[t, t] += ytt
        primitives.append((f, t, yff, yft, ytf, ytt))
    for i, bus in enumerate(network.buses):
        ybus[i, i] += complex(bus.g_shunt_pu, bus.b_shunt_pu)
    if not np.all(np.isfinite(ybus)):
        raise CaseError("Thông số tạo ra Ybus ngoài phạm vi số; kiểm tra cơ sở p.u.")
    return ybus, primitives


def power_injections(ybus: np.ndarray, vm: np.ndarray, va: np.ndarray) -> np.ndarray:
    voltage = vm * np.exp(1j * va)
    return voltage * np.conj(ybus @ voltage)


def jacobian(ybus: np.ndarray, vm: np.ndarray, va: np.ndarray,
             angle_idx: np.ndarray, pq_idx: np.ndarray) -> np.ndarray:
    """Đạo hàm [P(non-slack), Q(PQ)] theo [góc(non-slack), |V|(PQ)]."""
    g, b = ybus.real, ybus.imag
    delta = va[:, None] - va[None, :]
    c, s = np.cos(delta), np.sin(delta)
    vprod = vm[:, None] * vm[None, :]
    power = power_injections(ybus, vm, va)
    # Các phần tử ngoài đường chéo; góc tính bằng radian.
    h = vprod * (g * s - b * c)
    n = vm[:, None] * (g * c + b * s)
    m = -vprod * (g * c + b * s)
    ell = vm[:, None] * (g * s - b * c)
    np.fill_diagonal(h, -power.imag - np.diag(b) * vm**2)
    np.fill_diagonal(n, power.real / vm + np.diag(g) * vm)
    np.fill_diagonal(m, power.real - np.diag(g) * vm**2)
    np.fill_diagonal(ell, power.imag / vm - np.diag(b) * vm)
    return np.block([[h[np.ix_(angle_idx, angle_idx)], n[np.ix_(angle_idx, pq_idx)]],
                     [m[np.ix_(pq_idx, angle_idx)], ell[np.ix_(pq_idx, pq_idx)]]])


def _mismatch(ybus, vm, va, specified, angle_idx, pq_idx):
    difference = specified - power_injections(ybus, vm, va)
    return np.r_[difference.real[angle_idx], difference.imag[pq_idx]]


def _norm(vector) -> float:
    return float(np.max(np.abs(vector))) if vector.size else 0.0


def _newton(ybus, specified, kinds, vm, va, tolerance, max_iterations, pass_no, history):
    angle_idx = np.flatnonzero(kinds != "SLACK")
    pq_idx = np.flatnonzero(kinds == "PQ")
    for iteration in range(max_iterations + 1):
        mismatch = _mismatch(ybus, vm, va, specified, angle_idx, pq_idx)
        error = _norm(mismatch)
        history.append({"pass": pass_no, "iteration": iteration, "max_mismatch_pu": error})
        if not math.isfinite(error):
            raise PowerFlowError("Sai lệch không hữu hạn; kiểm tra số liệu và điểm khởi tạo.", history)
        if error <= tolerance:
            return vm, va, iteration, error
        if iteration == max_iterations:
            raise PowerFlowError(f"Chưa hội tụ sau {max_iterations} bước ở lượt {pass_no}; sai lệch {error:.3e} p.u.", history)
        try:
            step = np.linalg.solve(jacobian(ybus, vm, va, angle_idx, pq_idx), mismatch)
        except np.linalg.LinAlgError as exc:
            raise PowerFlowError("Jacobian suy biến; kiểm tra mô hình lưới, phụ tải và điểm khởi tạo.", history) from exc
        if not np.all(np.isfinite(step)):
            raise PowerFlowError("Bước Newton không hữu hạn.", history)
        # Giảm bước để sai lệch giảm và biên độ điện áp luôn dương.
        accepted = False
        for backtrack in range(21):
            alpha = 0.5**backtrack
            va_trial, vm_trial = va.copy(), vm.copy()
            va_trial[angle_idx] += alpha * step[:len(angle_idx)]
            vm_trial[pq_idx] += alpha * step[len(angle_idx):]
            if np.any(vm_trial <= 1e-8):
                continue
            with np.errstate(over="ignore", invalid="ignore"):
                next_error = _norm(_mismatch(ybus, vm_trial, va_trial, specified, angle_idx, pq_idx))
            if math.isfinite(next_error) and (next_error <= tolerance or next_error < error * (1 - 1e-4 * alpha)):
                vm, va = vm_trial, va_trial
                history[-1]["step_scale"] = alpha
                accepted = True
                break
        if not accepted:
            raise PowerFlowError(f"Không tìm được bước giảm sai lệch ở lượt {pass_no}, bước {iteration}; sai lệch {error:.3e} p.u.", history)


def solve_power_flow(data: dict, *, method: str = "NR", tolerance: float = 1e-8,
                     max_iterations: int = 50, enforce_q_limits: bool = True,
                     q_limit_tolerance_mvar: float = 1e-5) -> dict:
    """Trả về kết quả JSON-serializable; chỉ trả kết quả khi đã hội tụ.

    Hỗ trợ 4 phương pháp tính toán trào lưu công suất:
    - "NR" / "Newton": Newton-Raphson (chuẩn công nghiệp)
    - "FDPF" / "Fast_Decoupled": Phân tách nhanh Stott-Alsac (XB)
    - "GS" / "Gauss_Seidel": Gauss-Seidel lặp điện áp phức
    - "DC" / "DCPF": Trào lưu một chiều tuyến tính hóa
    """
    tolerance = _number(tolerance, "tolerance")
    q_limit_tolerance_mvar = _number(q_limit_tolerance_mvar, "q_limit_tolerance_mvar")
    if tolerance <= 0 or q_limit_tolerance_mvar < 0:
        raise CaseError("Cần tolerance > 0 và q_limit_tolerance_mvar >= 0.")
    if isinstance(max_iterations, bool) or not isinstance(max_iterations, int) or max_iterations < 1:
        raise CaseError("max_iterations phải là số nguyên >= 1.")
    if not isinstance(enforce_q_limits, bool):
        raise CaseError("enforce_q_limits phải là bool.")

    method_key = str(method).strip().upper()
    if method_key in ("FDPF", "FAST_DECOUPLED", "FAST DECOUPLED"):
        from solvers import solve_fdpf_engine
        network = validate_case(data)
        ybus, primitives = build_ybus(network)
        return solve_fdpf_engine(network, ybus, primitives, tolerance=tolerance,
                                 max_iterations=max_iterations, enforce_q_limits=enforce_q_limits,
                                 q_limit_tolerance_mvar=q_limit_tolerance_mvar)
    elif method_key in ("GS", "GAUSS_SEIDEL", "GAUSS-SEIDEL", "GAUSS"):
        from solvers import solve_gauss_seidel_engine
        network = validate_case(data)
        ybus, primitives = build_ybus(network)
        return solve_gauss_seidel_engine(network, ybus, primitives, tolerance=tolerance,
                                         max_iterations=max_iterations, enforce_q_limits=enforce_q_limits,
                                         q_limit_tolerance_mvar=q_limit_tolerance_mvar)
    elif method_key in ("DC", "DCPF", "DC_FLOW", "DC POWER FLOW"):
        from solvers import solve_dc_engine
        network = validate_case(data)
        _, primitives = build_ybus(network)
        return solve_dc_engine(network, primitives)
    elif method_key in ("NR", "NEWTON", "NEWTON_RAPHSON", "NEWTON-RAPHSON"):
        pass
    else:
        raise CaseError(f"Phương pháp trào lưu công suất không hợp lệ: '{method}'. Hỗ trợ: 'NR', 'FDPF', 'GS', 'DC'.")

    network = validate_case(data)
    ybus, primitives = build_ybus(network)
    buses, base = network.buses, network.base_mva
    kinds = np.array([bus.type for bus in buses], dtype="U5")
    vm = np.array([bus.vm_pu for bus in buses])
    va = np.deg2rad([bus.va_deg for bus in buses])
    specified = np.array([complex(bus.pg_mw - bus.pd_mw, bus.qg_mvar - bus.qd_mvar) / base for bus in buses])
    history, switches = [], []
    total_iterations = 0
    # Tối đa số nút PV lần chuyển cộng một lần giải cuối.
    for pass_no in range(1, int(np.sum(kinds == "PV")) + 2):
        vm, va, count, error = _newton(ybus, specified, kinds, vm, va, tolerance,
                                      max_iterations, pass_no, history)
        total_iterations += count
        injections = power_injections(ybus, vm, va) * base
        violations = []
        if enforce_q_limits:
            for i in np.flatnonzero(kinds == "PV"):
                bus = buses[i]
                qg = injections[i].imag + bus.qd_mvar
                if bus.qmax_mvar is not None and qg > bus.qmax_mvar + q_limit_tolerance_mvar:
                    violations.append((qg - bus.qmax_mvar, int(i), bus.qmax_mvar, "Qmax", float(qg)))
                elif bus.qmin_mvar is not None and qg < bus.qmin_mvar - q_limit_tolerance_mvar:
                    violations.append((bus.qmin_mvar - qg, int(i), bus.qmin_mvar, "Qmin", float(qg)))
        if not violations:
            break
        _, i, limit, bound, q_before = max(violations, key=lambda item: item[0])
        kinds[i] = "PQ"
        specified[i] = complex(specified[i].real, (limit - buses[i].qd_mvar) / base)
        switches.append({"bus": buses[i].id, "after_pass": pass_no, "bound": bound,
                         "q_before_mvar": q_before, "q_fixed_mvar": limit})
    else:
        raise PowerFlowError("Không hoàn tất vòng xử lý giới hạn Q.", history)
    res = _results(network, ybus, primitives, vm, va, kinds, specified, error,
                   total_iterations, pass_no, history, switches, tolerance,
                   enforce_q_limits, q_limit_tolerance_mvar)
    res["solver_method"] = "Newton-Raphson (NR)"
    return res


def _results(network, ybus, primitives, vm, va, kinds, specified, error,
             total_iterations, passes, history, switches, tolerance, enforce_q, q_tol):
    base = network.base_mva
    voltage = vm * np.exp(1j * va)
    injections = voltage * np.conj(ybus @ voltage) * base
    bus_rows, branch_rows, warnings = [], [], []
    switched = {event["bus"]: event for event in switches}
    limit_epsilon = max(q_tol, 2 * tolerance * base)
    shunt_total, branch_total = 0j, 0j
    for i, bus in enumerate(network.buses):
        pg = float(injections[i].real + bus.pd_mw) if bus.type == "SLACK" else bus.pg_mw
        if bus.id in switched:
            qg = switched[bus.id]["q_fixed_mvar"]
        elif bus.type in {"SLACK", "PV"}:
            qg = float(injections[i].imag + bus.qd_mvar)
        else:
            qg = bus.qg_mvar
        shunt = vm[i]**2 * complex(bus.g_shunt_pu, -bus.b_shunt_pu) * base
        shunt_total += shunt
        bus_rows.append({"id": bus.id, "type_input": bus.type, "type_final": str(kinds[i]),
                         "vm_pu": float(vm[i]), "va_deg": float(np.rad2deg(va[i])),
                         "voltage_kv": None if bus.base_kv is None else float(vm[i] * bus.base_kv),
                         "pg_mw": pg, "qg_mvar": qg, "pd_mw": bus.pd_mw, "qd_mvar": bus.qd_mvar,
                         "p_injection_mw": float(injections[i].real), "q_injection_mvar": float(injections[i].imag),
                         "p_shunt_mw": float(shunt.real), "q_shunt_mvar": float(shunt.imag),
                         "p_balance_error_mw": float(pg - bus.pd_mw - injections[i].real),
                         "q_balance_error_mvar": float(qg - bus.qd_mvar - injections[i].imag)})
        if vm[i] < bus.vmin_pu - 1e-8 or vm[i] > bus.vmax_pu + 1e-8:
            warnings.append(f"Nút {bus.id}: U={vm[i]:.5f} p.u. ngoài [{bus.vmin_pu:g}, {bus.vmax_pu:g}].")
        for value, lo, hi, label in ((pg, bus.pmin_mw, bus.pmax_mw, "Pg (MW)"),
                                     (qg, bus.qmin_mvar, bus.qmax_mvar, "Qg (Mvar)")):
            if lo is not None and value < lo - limit_epsilon:
                warnings.append(f"Nút {bus.id}: {label}={value:.5f} thấp hơn giới hạn {lo:g}.")
            if hi is not None and value > hi + limit_epsilon:
                warnings.append(f"Nút {bus.id}: {label}={value:.5f} cao hơn giới hạn {hi:g}.")
    for branch, primitive in zip(network.branches, primitives):
        f, t, yff, yft, ytf, ytt = primitive
        i_from = yff * voltage[f] + yft * voltage[t]
        i_to = ytf * voltage[f] + ytt * voltage[t]
        sf, st = voltage[f] * i_from.conjugate() * base, voltage[t] * i_to.conjugate() * base
        net = sf + st
        branch_total += net
        loading = None if branch.rate_mva is None else float(100 * max(abs(sf), abs(st)) / branch.rate_mva)
        def current_ka(current, bus_idx):
            kv = network.buses[bus_idx].base_kv
            return None if kv is None else float(abs(current) * base / (math.sqrt(3) * kv))
        branch_rows.append({"id": branch.id, "from_bus": branch.from_bus, "to_bus": branch.to_bus,
                            "status": branch.status, "p_from_mw": float(sf.real), "q_from_mvar": float(sf.imag),
                            "p_to_mw": float(st.real), "q_to_mvar": float(st.imag),
                            "p_loss_mw": float(net.real), "q_net_mvar": float(net.imag),
                            "i_from_ka": current_ka(i_from, f), "i_to_ka": current_ka(i_to, t),
                            "loading_percent": loading})
        if loading is not None and loading > 100 + 1e-6:
            warnings.append(f"Nhánh {branch.id}: tải {loading:.2f}% vượt định mức {branch.rate_mva:g} MVA.")
    for event in switches:
        warnings.append(f"Nút {event['bus']}: PV → PQ tại {event['bound']}={event['q_fixed_mvar']:g} Mvar; điện áp được phép thay đổi.")
    pg_total = sum(row["pg_mw"] for row in bus_rows)
    qg_total = sum(row["qg_mvar"] for row in bus_rows)
    pd_total = sum(bus.pd_mw for bus in network.buses)
    qd_total = sum(bus.qd_mvar for bus in network.buses)
    return {"name": network.name, "converged": True, "method": "Newton-Raphson polar with backtracking",
            "base_mva": base, "tolerance_pu": tolerance, "enforce_q_limits": enforce_q,
            "iterations": total_iterations, "passes": passes, "max_mismatch_pu": error,
            "buses": bus_rows, "branches": branch_rows, "q_limit_switches": switches,
            "summary": {"pg_total_mw": pg_total, "qg_total_mvar": qg_total,
                        "pd_total_mw": pd_total, "qd_total_mvar": qd_total,
                        "p_branch_loss_mw": float(branch_total.real), "q_branch_net_mvar": float(branch_total.imag),
                        "p_shunt_mw": float(shunt_total.real), "q_shunt_mvar": float(shunt_total.imag),
                        "p_total_loss_mw": float((branch_total + shunt_total).real),
                        "q_network_net_mvar": float((branch_total + shunt_total).imag),
                        "p_balance_error_mw": float(pg_total - pd_total - (branch_total + shunt_total).real),
                        "q_balance_error_mvar": float(qg_total - qd_total - (branch_total + shunt_total).imag)},
            "history": history, "warnings": warnings}


def _no_duplicate_keys(pairs):
    answer = {}
    for key, value in pairs:
        if key in answer:
            raise CaseError(f"JSON chứa trường lặp: {key}.")
        answer[key] = value
    return answer


def parse_case(text: str) -> dict:
    def reject_constant(value):
        raise CaseError(f"JSON không nhận {value}.")
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=reject_constant)
    except json.JSONDecodeError as exc:
        raise CaseError(f"JSON lỗi ở dòng {exc.lineno}, cột {exc.colno}: {exc.msg}") from exc
    validate_case(data)
    return data


def load_case(path: str | Path) -> dict:
    return parse_case(Path(path).read_text(encoding="utf-8-sig"))


def format_report(result: dict) -> str:
    s = result["summary"]
    lines = [f"CHẾ ĐỘ XÁC LẬP — {result['name']}",
             f"Hội tụ: {result['iterations']} bước Newton, {result['passes']} lượt giải; sai lệch {result['max_mismatch_pu']:.3e} p.u.",
             f"Cơ sở: {result['base_mva']:g} MVA | Công suất tổng ba pha | Góc: độ",
             "", "KẾT QUẢ NÚT", "Nút          Loại       U (pu)   Góc (độ)     Pg (MW)   Qg (Mvar)"]
    for row in result["buses"]:
        kind = row["type_final"] if row["type_input"] == row["type_final"] else row["type_input"] + "→" + row["type_final"]
        lines.append(f"{row['id']:<12} {kind:<8} {row['vm_pu']:10.6f} {row['va_deg']:10.5f} {row['pg_mw']:11.5f} {row['qg_mvar']:11.5f}")
    lines.extend(["", "KẾT QUẢ NHÁNH (công suất dương: từ nút đi vào nhánh)",
                  "Nhánh         Đầu/cuối         Pf (MW)  Qf (Mvar)    Pt (MW)  Qt (Mvar)   ΔP (MW)    Tải (%)"])
    for row in result["branches"]:
        endpoints = f"{row['from_bus']}→{row['to_bus']}" + (" [cắt]" if not row["status"] else "")
        loading = "—" if row["loading_percent"] is None else f"{row['loading_percent']:.2f}"
        lines.append(f"{row['id']:<13} {endpoints:<15} {row['p_from_mw']:9.4f} {row['q_from_mvar']:10.4f} {row['p_to_mw']:10.4f} {row['q_to_mvar']:10.4f} {row['p_loss_mw']:9.5f} {loading:>10}")
    lines.extend(["", f"Tổng phát: {s['pg_total_mw']:.6f} MW; {s['qg_total_mvar']:.6f} Mvar.",
                  f"Tổng phụ tải: {s['pd_total_mw']:.6f} MW; {s['qd_total_mvar']:.6f} Mvar.",
                  f"Tổn thất P trên nhánh: {s['p_branch_loss_mw']:.6f} MW; shunt nút: {s['p_shunt_mw']:.6f} MW.",
                  f"Tổng tổn thất P: {s['p_total_loss_mw']:.6f} MW.",
                  f"Q thuần của mạng: {s['q_network_net_mvar']:.6f} Mvar (âm nghĩa là mạng phát Q).",
                  f"Sai số cân bằng P/Q: {s['p_balance_error_mw']:.3e} MW / {s['q_balance_error_mvar']:.3e} Mvar."])
    if result["warnings"]:
        lines.extend(["", "CẢNH BÁO / THAY ĐỔI LOẠI NÚT", *[f"• {warning}" for warning in result["warnings"]]])
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Tính trào lưu công suất AC cân bằng bằng 4 phương pháp (NR, FDPF, GS, DC).")
    parser.add_argument("case", nargs="?", type=Path, default=Path(__file__).parent / "examples" / "luoi_3_nut.json", help="Tệp dữ liệu JSON; mặc định ví dụ 3 nút.")
    parser.add_argument("--method", choices=["nr", "fdpf", "gs", "dc"], default="nr", help="Phương pháp giải: nr (Newton-Raphson), fdpf (Fast Decoupled), gs (Gauss-Seidel), dc (DC Flow). Mặc định 'nr'.")
    parser.add_argument("--benchmark", action="store_true", help="Chạy đối chuẩn cả 4 phương pháp trên tệp lưới và in bảng so sánh.")
    parser.add_argument("--tol", type=float, default=1e-8, help="Dung sai sai lệch công suất p.u. (mặc định 1e-8).")
    parser.add_argument("--max-iter", type=int, default=50, help="Số bước tối đa mỗi lượt giải.")
    parser.add_argument("--no-q-limits", action="store_true", help="Tắt chuyển PV sang PQ theo giới hạn Q.")
    parser.add_argument("--output", type=Path, help="Xuất kết quả chi tiết JSON.")
    parser.add_argument("--report", type=Path, help="Xuất báo cáo văn bản UTF-8.")
    args = parser.parse_args(argv)
    # Console Windows hiện đại hỗ trợ UTF-8; không phụ thuộc code page cũ.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        if args.benchmark:
            from solvers import benchmark_all_solvers
            bench = benchmark_all_solvers(load_case(args.case), tolerance=args.tol, max_iterations=args.max_iter,
                                          enforce_q_limits=not args.no_q_limits)
            print(f"\n=== SO SÁNH ĐỐI CHUẨN 4 PHƯƠNG PHÁP TRÀO LƯU: {bench['case_name']} ===")
            print(f"{'Phương pháp':<25} {'Trạng thái':<14} {'Số bước':<9} {'Thời gian':<12} {'Max |ΔP| (pu)':<16} {'ΔPloss (MW)':<12}")
            print("-" * 90)
            for kpi in bench["kpi_summary"]:
                mis_str = f"{kpi['max_mismatch_pu']:.2e}" if kpi['max_mismatch_pu'] is not None else "—"
                loss_str = f"{kpi['p_loss_mw']:.3f}" if kpi['p_loss_mw'] is not None else "—"
                print(f"{kpi['name']:<25} {kpi['status']:<14} {kpi['iterations']:<9} {kpi['time_ms']:>6.2f} ms   {mis_str:<16} {loss_str:<12}")
            print()
            return 0

        outputs = [path for path in (args.output, args.report) if path is not None]
        resolved = [path.resolve() for path in outputs]
        if args.case.resolve() in resolved or len(set(resolved)) != len(resolved):
            raise CaseError("Tệp đầu vào, kết quả JSON và báo cáo phải có đường dẫn khác nhau.")
        result = solve_power_flow(load_case(args.case), method=args.method.upper(), tolerance=args.tol, max_iterations=args.max_iter,
                                  enforce_q_limits=not args.no_q_limits)
        report = format_report(result)
        print(report, end="")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(report, encoding="utf-8")
    except (CaseError, PowerFlowError, OSError, UnicodeError) as exc:
        print(f"LỖI: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
