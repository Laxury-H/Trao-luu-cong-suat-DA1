"""Các phương pháp tính toán trào lưu công suất:
1. Newton-Raphson (NR): Tiêu chuẩn công nghiệp, hội tụ bậc hai (quadratic).
2. Fast Decoupled Power Flow (FDPF): Phân tách nhanh Stott-Alsac (XB), ma trận B' và B'' hằng số.
3. Gauss-Seidel (GS): Lặp điện áp phức theo nút, yêu cầu bộ nhớ tối thiểu, hội tụ tuyến tính.
4. DC Power Flow (DCPF): Xấp xỉ tuyến tính hóa một chiều (R=0, V=1.0, Q=0), giải trực tiếp 1 bước.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from powerflow import (
    Branch,
    Bus,
    CaseError,
    Network,
    PowerFlowError,
    _mismatch,
    _norm,
    _results,
    build_ybus,
    jacobian,
    power_injections,
    validate_case,
)


def solve_nr_engine(
    network: Network,
    ybus: np.ndarray,
    primitives: list,
    tolerance: float = 1e-8,
    max_iterations: int = 50,
    enforce_q_limits: bool = True,
    q_limit_tolerance_mvar: float = 1e-5
) -> dict:
    """Bộ giải Newton-Raphson AC trong tọa độ cực có backtracking."""
    buses, base = network.buses, network.base_mva
    kinds = np.array([bus.type for bus in buses], dtype="U5")
    vm = np.array([bus.vm_pu for bus in buses])
    va = np.deg2rad([bus.va_deg for bus in buses])
    specified = np.array([complex(bus.pg_mw - bus.pd_mw, bus.qg_mvar - bus.qd_mvar) / base for bus in buses])
    history, switches = [], []
    total_iterations = 0

    angle_idx = np.flatnonzero(kinds != "SLACK")
    pq_idx = np.flatnonzero(kinds == "PQ")

    for pass_no in range(1, int(np.sum(kinds == "PV")) + 2):
        angle_idx = np.flatnonzero(kinds != "SLACK")
        pq_idx = np.flatnonzero(kinds == "PQ")
        pass_converged = False

        for iteration in range(max_iterations + 1):
            mismatch = _mismatch(ybus, vm, va, specified, angle_idx, pq_idx)
            error = _norm(mismatch)
            history.append({"pass": pass_no, "iteration": iteration, "max_mismatch_pu": error})
            if not math.isfinite(error):
                raise PowerFlowError("Sai lệch không hữu hạn; kiểm tra số liệu và điểm khởi tạo.", history)
            if error <= tolerance:
                total_iterations += iteration
                pass_converged = True
                break
            if iteration == max_iterations:
                raise PowerFlowError(f"NR chưa hội tụ sau {max_iterations} bước ở lượt {pass_no}; sai lệch {error:.3e} p.u.", history)

            try:
                step = np.linalg.solve(jacobian(ybus, vm, va, angle_idx, pq_idx), mismatch)
            except np.linalg.LinAlgError as exc:
                raise PowerFlowError("Jacobian suy biến; kiểm tra mô hình lưới và điểm khởi tạo.", history) from exc

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


def build_fdpf_matrices(network: Network) -> Tuple[np.ndarray, np.ndarray]:
    """Xây dựng ma trận B' và B'' cho thuật toán Fast Decoupled (phương bản XB Stott-Alsac).
    
    - B' (cho P-theta): Bỏ qua điện trở đường dây, shunts và nấc biến áp lệch pha.
    - B'' (cho Q-V): Bao gồm điện kháng nối tiếp và shunts tích điện đường dây/tụ bù.
    """
    n = len(network.buses)
    index = {bus.id: i for i, bus in enumerate(network.buses)}

    b_prime = np.zeros((n, n), dtype=float)
    b_double_prime = np.zeros((n, n), dtype=float)

    for br in network.branches:
        if not br.status:
            continue
        f, t = index[br.from_bus], index[br.to_bus]
        r, x = br.r_pu, br.x_pu
        tap = br.tap if br.tap > 0 else 1.0

        # B' series reactance only: 1 / x
        bp = 1.0 / x
        b_prime[f, t] -= bp
        b_prime[t, f] -= bp
        b_prime[f, f] += bp
        b_prime[t, t] += bp

        # B'' imaginary part of admittance: x / (r^2 + x^2) + b_charging
        denom = r * r + x * x
        b_series = x / denom if denom > 1e-12 else 1.0 / x
        b_double_prime[f, t] -= b_series / tap
        b_double_prime[t, f] -= b_series / tap
        b_double_prime[f, f] += (b_series + 0.5 * br.b_pu) / (tap * tap)
        b_double_prime[t, t] += b_series + 0.5 * br.b_pu

    for i, bus in enumerate(network.buses):
        b_double_prime[i, i] += bus.b_shunt_pu

    return b_prime, b_double_prime


def solve_fdpf_engine(
    network: Network,
    ybus: np.ndarray,
    primitives: list,
    tolerance: float = 1e-6,
    max_iterations: int = 100,
    enforce_q_limits: bool = True,
    q_limit_tolerance_mvar: float = 1e-5
) -> dict:
    """Bộ giải Fast Decoupled Power Flow (FDPF - XB Stott-Alsac)."""
    buses, base = network.buses, network.base_mva
    n = len(buses)
    kinds = np.array([bus.type for bus in buses], dtype="U5")
    vm = np.array([bus.vm_pu for bus in buses], dtype=float)
    va = np.deg2rad([bus.va_deg for bus in buses], dtype=float)
    specified = np.array([complex(bus.pg_mw - bus.pd_mw, bus.qg_mvar - bus.qd_mvar) / base for bus in buses])

    b_prime_full, b_double_prime_full = build_fdpf_matrices(network)
    history, switches = [], []
    total_iterations = 0

    for pass_no in range(1, int(np.sum(kinds == "PV")) + 2):
        angle_idx = np.flatnonzero(kinds != "SLACK")
        pq_idx = np.flatnonzero(kinds == "PQ")

        if len(angle_idx) == 0:
            break

        # Trích xuất ma trận B' và B'' cho pass hiện tại
        bp = b_prime_full[np.ix_(angle_idx, angle_idx)]
        bpp = b_double_prime_full[np.ix_(pq_idx, pq_idx)] if len(pq_idx) > 0 else None

        pass_converged = False
        last_error = 1.0

        for iteration in range(1, max_iterations + 1):
            # Tính sai lệch công suất
            injections = power_injections(ybus, vm, va)
            dp = (specified.real - injections.real)[angle_idx]
            dq = (specified.imag - injections.imag)[pq_idx] if len(pq_idx) > 0 else np.array([])

            error_p = np.max(np.abs(dp)) if dp.size else 0.0
            error_q = np.max(np.abs(dq)) if dq.size else 0.0
            error = max(error_p, error_q)
            last_error = error

            history.append({"pass": pass_no, "iteration": iteration, "max_mismatch_pu": float(error)})

            if error <= tolerance:
                total_iterations += iteration
                pass_converged = True
                break

            # 1. P-theta step: B' * dtheta = dP / V
            rhs_p = dp / vm[angle_idx]
            try:
                dtheta = np.linalg.solve(bp, rhs_p)
            except np.linalg.LinAlgError as exc:
                raise PowerFlowError("Ma trận B' của FDPF suy biến.", history) from exc
            va[angle_idx] += dtheta

            # 2. Q-V step: B'' * dV = dQ / V
            if len(pq_idx) > 0 and bpp is not None:
                inj_half = power_injections(ybus, vm, va)
                dq_half = (specified.imag - inj_half.imag)[pq_idx]
                rhs_q = dq_half / vm[pq_idx]
                try:
                    dvm = np.linalg.solve(bpp, rhs_q)
                except np.linalg.LinAlgError as exc:
                    raise PowerFlowError("Ma trận B'' của FDPF suy biến.", history) from exc
                vm[pq_idx] += dvm
                vm[pq_idx] = np.maximum(vm[pq_idx], 0.1)

        if not pass_converged:
            raise PowerFlowError(
                f"FDPF chưa hội tụ sau {max_iterations} bước ở lượt {pass_no}; sai lệch {last_error:.3e} p.u. (Lưới có thể có tỷ số R/X cao).",
                history
            )

        # Kiểm tra giới hạn Q tại nút PV
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
        raise PowerFlowError("FDPF: Không hoàn tất vòng xử lý giới hạn Q.", history)

    res = _results(network, ybus, primitives, vm, va, kinds, specified, last_error,
                   total_iterations, pass_no, history, switches, tolerance,
                   enforce_q_limits, q_limit_tolerance_mvar)
    res["solver_method"] = "Fast Decoupled (FDPF XB)"
    return res


def solve_gauss_seidel_engine(
    network: Network,
    ybus: np.ndarray,
    primitives: list,
    tolerance: float = 1e-5,
    max_iterations: int = 500,
    enforce_q_limits: bool = True,
    acceleration_factor: float = 1.0,
    q_limit_tolerance_mvar: float = 1e-5
) -> dict:
    """Bộ giải Gauss-Seidel lặp điện áp phức từng nút."""
    buses, base = network.buses, network.base_mva
    n = len(buses)
    kinds = np.array([bus.type for bus in buses], dtype="U5")
    v_spec_mag = np.array([bus.vm_pu for bus in buses], dtype=float)
    v_complex = v_spec_mag * np.exp(1j * np.deg2rad([bus.va_deg for bus in buses]))
    history, switches = [], []

    p_spec = np.array([(bus.pg_mw - bus.pd_mw) / base for bus in buses], dtype=float)
    q_spec = np.array([(bus.qg_mvar - bus.qd_mvar) / base for bus in buses], dtype=float)

    diag_y = np.diag(ybus)
    if np.any(np.abs(diag_y) < 1e-12):
        raise PowerFlowError("Ma trận Ybus có phần tử đường chéo gần bằng 0 trong Gauss-Seidel.", history)

    last_error = 1.0
    converged = False

    for iteration in range(1, max_iterations + 1):
        max_v_diff = 0.0

        for i in range(n):
            if kinds[i] == "SLACK":
                continue

            # Nút PV: Cần tính lại Q phát trước khi tính V
            if kinds[i] == "PV":
                i_inj = np.dot(ybus[i, :], v_complex)
                q_calc = -float((np.conj(v_complex[i]) * i_inj).imag)
                qg_mw = q_calc * base + buses[i].qd_mvar

                # Kiểm tra giới hạn Q
                if enforce_q_limits:
                    bus = buses[i]
                    if bus.qmax_mvar is not None and qg_mw > bus.qmax_mvar + q_limit_tolerance_mvar:
                        kinds[i] = "PQ"
                        q_spec[i] = (bus.qmax_mvar - bus.qd_mvar) / base
                        switches.append({"bus": bus.id, "iteration": iteration, "bound": "Qmax",
                                         "q_before_mvar": qg_mw, "q_fixed_mvar": bus.qmax_mvar})
                    elif bus.qmin_mvar is not None and qg_mw < bus.qmin_mvar - q_limit_tolerance_mvar:
                        kinds[i] = "PQ"
                        q_spec[i] = (bus.qmin_mvar - bus.qd_mvar) / base
                        switches.append({"bus": bus.id, "iteration": iteration, "bound": "Qmin",
                                         "q_before_mvar": qg_mw, "q_fixed_mvar": bus.qmin_mvar})
                    else:
                        q_spec[i] = q_calc
                else:
                    q_spec[i] = q_calc

            # Tính điện áp Gauss-Seidel mới
            s_conj = complex(p_spec[i], -q_spec[i])
            sum_yv = np.dot(ybus[i, :], v_complex) - ybus[i, i] * v_complex[i]
            v_new = (s_conj / np.conj(v_complex[i]) - sum_yv) / ybus[i, i]

            # Với nút PV: Chuẩn hóa lại biên độ theo đúng V_spec
            if kinds[i] == "PV":
                ang = np.angle(v_new)
                v_new = v_spec_mag[i] * np.exp(1j * ang)

            # Hệ số gia tốc (acceleration factor)
            if acceleration_factor != 1.0:
                v_new = v_complex[i] + acceleration_factor * (v_new - v_complex[i])

            diff = abs(v_new - v_complex[i])
            if diff > max_v_diff:
                max_v_diff = diff

            v_complex[i] = v_new

        # Tính sai lệch công suất
        vm_cur = np.abs(v_complex)
        va_cur = np.angle(v_complex)
        inj_cur = power_injections(ybus, vm_cur, va_cur)
        angle_idx = np.flatnonzero(kinds != "SLACK")
        pq_idx = np.flatnonzero(kinds == "PQ")

        dp = (p_spec - inj_cur.real)[angle_idx]
        dq = (q_spec - inj_cur.imag)[pq_idx] if len(pq_idx) > 0 else np.array([])
        mismatch_p = np.max(np.abs(dp)) if dp.size else 0.0
        mismatch_q = np.max(np.abs(dq)) if dq.size else 0.0
        mismatch = max(mismatch_p, mismatch_q)
        last_error = mismatch

        history.append({"pass": 1, "iteration": iteration, "max_mismatch_pu": float(mismatch), "max_v_diff": float(max_v_diff)})

        if mismatch <= tolerance or max_v_diff <= tolerance * 0.1:
            converged = True
            break

    if not converged:
        raise PowerFlowError(
            f"Gauss-Seidel không hội tụ sau {max_iterations} bước; sai lệch {last_error:.3e} p.u. (GS hội tụ tuyến tính, cần nhiều bước lặp hơn).",
            history
        )

    vm_final = np.abs(v_complex)
    va_final = np.angle(v_complex)
    specified_final = np.array([complex(p_spec[i], q_spec[i]) for i in range(n)])

    res = _results(network, ybus, primitives, vm_final, va_final, kinds, specified_final, last_error,
                   iteration, 1, history, switches, tolerance,
                   enforce_q_limits, q_limit_tolerance_mvar)
    res["solver_method"] = "Gauss-Seidel (GS)"
    return res


def solve_dc_engine(network: Network, primitives: list) -> dict:
    """Bộ giải DC Power Flow (Trào lưu công suất một chiều tuyến tính hóa).
    
    Giả thiết: R=0, V=1.0 pu, góc lệch nhỏ, bỏ qua Q và shunts.
    Phương trình: B_bus * theta = P_inj - P_shift
    """
    buses, base = network.buses, network.base_mva
    n = len(buses)
    index = {bus.id: i for i, bus in enumerate(buses)}
    kinds = np.array([bus.type for bus in buses], dtype="U5")

    b_bus = np.zeros((n, n), dtype=float)
    p_shift = np.zeros(n, dtype=float)

    for br in network.branches:
        if not br.status:
            continue
        f, t = index[br.from_bus], index[br.to_bus]
        x = br.x_pu
        if abs(x) < 1e-12:
            x = 1e-4
        b = 1.0 / x
        shift = np.deg2rad(br.shift_deg)

        b_bus[f, t] -= b
        b_bus[t, f] -= b
        b_bus[f, f] += b
        b_bus[t, t] += b

        if shift != 0.0:
            p_shift[f] -= b * shift
            p_shift[t] += b * shift

    p_inj = np.array([(bus.pg_mw - bus.pd_mw) / base for bus in buses], dtype=float)
    p_target = p_inj - p_shift

    slack_idx = np.flatnonzero(kinds == "SLACK")
    non_slack_idx = np.flatnonzero(kinds != "SLACK")

    theta = np.zeros(n, dtype=float)
    for s in slack_idx:
        theta[s] = np.deg2rad(buses[s].va_deg)

    b_red = b_bus[np.ix_(non_slack_idx, non_slack_idx)]
    rhs = p_target[non_slack_idx] - b_bus[non_slack_idx, :][:, slack_idx] @ theta[slack_idx]

    try:
        theta[non_slack_idx] = np.linalg.solve(b_red, rhs)
    except np.linalg.LinAlgError as exc:
        raise PowerFlowError("Ma trận B trong DC Power Flow suy biến; hệ thống bị cô lập hoặc thiếu nút SLACK.", []) from exc

    vm = np.array([bus.vm_pu if bus.type in ("SLACK", "PV") else 1.0 for bus in buses], dtype=float)
    va = theta

    branch_rows = []
    for br in network.branches:
        f, t = index[br.from_bus], index[br.to_bus]
        if br.status:
            x = br.x_pu if abs(br.x_pu) > 1e-12 else 1e-4
            shift = np.deg2rad(br.shift_deg)
            p_flow = (theta[f] - theta[t] - shift) / x * base
        else:
            p_flow = 0.0

        loading = None if br.rate_mva is None else float(100.0 * abs(p_flow) / br.rate_mva)
        kv_f = buses[f].base_kv
        i_ka = None if kv_f is None else float(abs(p_flow) / (math.sqrt(3) * kv_f))

        branch_rows.append({
            "id": br.id, "from_bus": br.from_bus, "to_bus": br.to_bus,
            "status": br.status, "p_from_mw": float(p_flow), "q_from_mvar": 0.0,
            "p_to_mw": float(-p_flow), "q_to_mvar": 0.0,
            "p_loss_mw": 0.0, "q_net_mvar": 0.0,
            "i_from_ka": i_ka, "i_to_ka": i_ka,
            "loading_percent": loading
        })

    p_calc = (b_bus @ theta + p_shift) * base
    bus_rows = []
    pg_total = 0.0
    pd_total = sum(b.pd_mw for b in buses)

    for i, bus in enumerate(buses):
        if bus.type == "SLACK":
            pg = float(p_calc[i] + bus.pd_mw)
        else:
            pg = bus.pg_mw
        pg_total += pg

        bus_rows.append({
            "id": bus.id, "type_input": bus.type, "type_final": bus.type,
            "vm_pu": float(vm[i]), "va_deg": float(np.rad2deg(va[i])),
            "voltage_kv": None if bus.base_kv is None else float(vm[i] * bus.base_kv),
            "pg_mw": pg, "qg_mvar": 0.0, "pd_mw": bus.pd_mw, "qd_mvar": bus.qd_mvar,
            "p_injection_mw": float(pg - bus.pd_mw), "q_injection_mvar": 0.0,
            "p_shunt_mw": 0.0, "q_shunt_mvar": 0.0,
            "p_balance_error_mw": 0.0, "q_balance_error_mvar": 0.0
        })

    history = [{"pass": 1, "iteration": 1, "max_mismatch_pu": 0.0}]

    return {
        "name": network.name, "converged": True, "method": "DC Power Flow (Linear Approximation)",
        "solver_method": "DC Power Flow (DCPF)",
        "base_mva": base, "tolerance_pu": 0.0, "enforce_q_limits": False,
        "iterations": 1, "passes": 1, "max_mismatch_pu": 0.0,
        "buses": bus_rows, "branches": branch_rows, "q_limit_switches": [],
        "summary": {
            "pg_total_mw": pg_total, "qg_total_mvar": 0.0,
            "pd_total_mw": pd_total, "qd_total_mvar": 0.0,
            "p_branch_loss_mw": 0.0, "q_branch_net_mvar": 0.0,
            "p_shunt_mw": 0.0, "q_shunt_mvar": 0.0,
            "p_total_loss_mw": 0.0, "q_network_net_mvar": 0.0,
            "p_balance_error_mw": 0.0, "q_balance_error_mvar": 0.0
        },
        "history": history,
        "warnings": ["DC Power Flow: Giả định R=0, V=1.0 pu, bỏ qua tổn thất và công suất phản kháng Q."]
    }


SOLVER_DESCRIPTIONS = {
    "NR": {
        "name": "Newton-Raphson (NR)",
        "convergence": "Bậc hai (Quadratic)",
        "speed": "Chuẩn xác (Jacobian O(N³))",
        "memory": "Trung bình (Lưu Jacobian 2N×2N)",
        "suitability": "Tiêu chuẩn vàng công nghiệp, lưới truyền tải và phân phối tổng quát, độ chính xác cao nhất."
    },
    "FDPF": {
        "name": "Fast Decoupled (FDPF XB)",
        "convergence": "Hình học (Geometric)",
        "speed": "Rất nhanh (B', B'' tính 1 lần)",
        "memory": "Thấp (Tách 2 ma trận B', B'')",
        "suitability": "Phân tích sự cố (Contingency N-1), giám sát thời gian thực EMS, lưới truyền tải tỷ số X/R cao."
    },
    "GS": {
        "name": "Gauss-Seidel (GS)",
        "convergence": "Tuyến tính (Linear, chậm)",
        "speed": "Chậm trên lưới lớn (nhiều bước lặp)",
        "memory": "Cực thấp (Không ma trận đảo)",
        "suitability": "Mục đích học tập, minh họa thuật toán lặp số học, lưới nhỏ hình tia không có tụ bù."
    },
    "DC": {
        "name": "DC Power Flow (DCPF)",
        "convergence": "Giải trực tiếp 1 lần (Không lặp)",
        "speed": "Tuyệt đối (<1 ms)",
        "memory": "Rất thấp (1 ma trận B duy nhất)",
        "suitability": "Thị trường điện, quy hoạch dài hạn, lọc nhanh sự cố (Screening), không dùng cho điện áp/tổn thất."
    }
}


def benchmark_all_solvers(
    data: dict,
    *,
    tolerance: float = 1e-6,
    max_iterations: int = 200,
    enforce_q_limits: bool = True
) -> dict:
    """Chạy đồng thời cả 4 phương pháp trên cùng một lưới điện và so sánh đối chuẩn toàn diện."""
    network = validate_case(data)
    ybus, primitives = build_ybus(network)

    solvers_config = [
        ("NR", "Newton-Raphson", lambda: solve_nr_engine(
            network, ybus, primitives, tolerance=tolerance, max_iterations=min(max_iterations, 50),
            enforce_q_limits=enforce_q_limits
        )),
        ("FDPF", "Fast Decoupled", lambda: solve_fdpf_engine(
            network, ybus, primitives, tolerance=tolerance, max_iterations=max_iterations,
            enforce_q_limits=enforce_q_limits
        )),
        ("GS", "Gauss-Seidel", lambda: solve_gauss_seidel_engine(
            network, ybus, primitives, tolerance=tolerance, max_iterations=max(max_iterations, 400),
            enforce_q_limits=enforce_q_limits
        )),
        ("DC", "DC Power Flow", lambda: solve_dc_engine(network, primitives)),
    ]

    results: Dict[str, Any] = {}
    timings: Dict[str, float] = {}
    errors: Dict[str, Optional[str]] = {}

    for code, _name, solver_fn in solvers_config:
        t0 = time.perf_counter()
        try:
            res = solver_fn()
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            results[code] = res
            timings[code] = elapsed_ms
            errors[code] = None
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            results[code] = None
            timings[code] = elapsed_ms
            errors[code] = str(exc)

    nr_res = results.get("NR")
    nr_buses = {str(b["id"]): b for b in nr_res["buses"]} if nr_res else {}
    nr_branches = {str(br["id"]): br for br in nr_res["branches"]} if nr_res else {}

    kpi_summary = []
    for code, name, _ in solvers_config:
        res = results.get(code)
        err = errors.get(code)
        info = SOLVER_DESCRIPTIONS.get(code, {})

        if res is not None:
            iters = res.get("iterations", 1)
            p_loss = res["summary"].get("p_total_loss_mw", 0.0)
            max_mis = res.get("max_mismatch_pu", 0.0)

            max_v_diff = 0.0
            max_ang_diff = 0.0
            if nr_res:
                for b in res["buses"]:
                    b_id = str(b["id"])
                    if b_id in nr_buses:
                        v_diff = abs(b["vm_pu"] - nr_buses[b_id]["vm_pu"])
                        a_diff = abs(b["va_deg"] - nr_buses[b_id]["va_deg"])
                        if v_diff > max_v_diff:
                            max_v_diff = v_diff
                        if a_diff > max_ang_diff:
                            max_ang_diff = a_diff

            kpi_summary.append({
                "code": code,
                "name": info.get("name", name),
                "status": "Hội tụ" if code != "DC" else "Xấp xỉ tuyến tính",
                "converged": True,
                "iterations": iters,
                "time_ms": round(timings.get(code, 0.0), 2),
                "max_mismatch_pu": max_mis,
                "max_v_diff_pu": round(max_v_diff, 5) if code != "NR" else 0.0,
                "max_ang_diff_deg": round(max_ang_diff, 3) if code != "NR" else 0.0,
                "p_loss_mw": round(p_loss, 3),
                "convergence_type": info.get("convergence", "—"),
                "speed_assessment": info.get("speed", "—"),
                "suitability": info.get("suitability", "—")
            })
        else:
            kpi_summary.append({
                "code": code,
                "name": info.get("name", name),
                "status": f"Lỗi: {err}",
                "converged": False,
                "iterations": 0,
                "time_ms": round(timings.get(code, 0.0), 2),
                "max_mismatch_pu": None,
                "max_v_diff_pu": None,
                "max_ang_diff_deg": None,
                "p_loss_mw": None,
                "convergence_type": info.get("convergence", "—"),
                "speed_assessment": info.get("speed", "—"),
                "suitability": info.get("suitability", "—")
            })

    bus_comparison = []
    for bus in network.buses:
        b_id = str(bus.id)
        row_data = {
            "id": b_id,
            "type": bus.type,
            "v_nr": round(nr_buses[b_id]["vm_pu"], 4) if b_id in nr_buses else "—",
            "ang_nr": round(nr_buses[b_id]["va_deg"], 2) if b_id in nr_buses else "—",
        }
        for code in ("FDPF", "GS", "DC"):
            res = results.get(code)
            if res:
                b_map = {str(b["id"]): b for b in res["buses"]}
                if b_id in b_map:
                    row_data[f"v_{code.lower()}"] = round(b_map[b_id]["vm_pu"], 4)
                    row_data[f"ang_{code.lower()}"] = round(b_map[b_id]["va_deg"], 2)
                else:
                    row_data[f"v_{code.lower()}"] = "—"
                    row_data[f"ang_{code.lower()}"] = "—"
            else:
                row_data[f"v_{code.lower()}"] = "—"
                row_data[f"ang_{code.lower()}"] = "—"
        bus_comparison.append(row_data)

    branch_comparison = []
    for br in network.branches:
        br_id = str(br.id)
        row_data = {
            "id": br_id,
            "from_to": f"{br.from_bus}➔{br.to_bus}",
            "p_nr": round(nr_branches[br_id]["p_from_mw"], 2) if br_id in nr_branches else "—",
        }
        for code in ("FDPF", "GS", "DC"):
            res = results.get(code)
            if res:
                br_map = {str(b["id"]): b for b in res["branches"]}
                if br_id in br_map:
                    row_data[f"p_{code.lower()}"] = round(br_map[br_id]["p_from_mw"], 2)
                else:
                    row_data[f"p_{code.lower()}"] = "—"
            else:
                row_data[f"p_{code.lower()}"] = "—"
        branch_comparison.append(row_data)

    return {
        "case_name": network.name,
        "kpi_summary": kpi_summary,
        "bus_comparison": bus_comparison,
        "branch_comparison": branch_comparison,
        "results": results
    }
