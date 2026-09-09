"""Kiểm chứng số học và các tình huống sai dữ liệu; python -m unittest discover -s tests -v."""
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from powerflow import (CaseError, PowerFlowError, build_ybus, jacobian, load_case,
                       parse_case, power_injections, solve_power_flow, validate_case)

ROOT = Path(__file__).resolve().parents[1]


def sample(name="luoi_3_nut.json"):
    return load_case(ROOT / "examples" / name)


def independent_injections(data, voltage):
    """Tính từ dòng qua tổng trở và biến áp lý tưởng, không gọi build_ybus."""
    index = {str(bus["id"]): i for i, bus in enumerate(data["buses"])}
    currents = np.zeros(len(voltage), dtype=complex)
    for branch in data["branches"]:
        if not branch.get("status", True):
            continue
        f, t = index[str(branch["from_bus"])], index[str(branch["to_bus"])]
        ratio = branch.get("tap", 1.0) * np.exp(1j * np.deg2rad(branch.get("shift_deg", 0.0)))
        referred_voltage = voltage[f] / ratio
        series_current = (referred_voltage - voltage[t]) / complex(branch["r_pu"], branch["x_pu"])
        charging = 0.5j * branch.get("b_pu", 0.0)
        currents[f] += (series_current + charging * referred_voltage) / ratio.conjugate()
        currents[t] += -series_current + charging * voltage[t]
    for i, bus in enumerate(data["buses"]):
        currents[i] += complex(bus.get("g_shunt_pu", 0.0), bus.get("b_shunt_pu", 0.0)) * voltage[i]
    return voltage * np.conj(currents)


def rectangular_reference(data):
    """Bộ giải đối chiếu: tọa độ chữ nhật, Jacobian sai phân trung tâm."""
    buses, base = data["buses"], data["base_mva"]
    variable = np.array([i for i, b in enumerate(buses) if b["type"] != "SLACK"])
    pq = np.array([i for i, b in enumerate(buses) if b["type"] == "PQ"])
    pv = np.array([i for i, b in enumerate(buses) if b["type"] == "PV"])
    count = len(variable)
    fixed = np.array([b.get("vm_pu", 1.0) * np.exp(1j * np.deg2rad(b.get("va_deg", 0.0))) for b in buses])
    spec = np.array([complex(b.get("pg_mw", 0) - b.get("pd_mw", 0),
                             b.get("qg_mvar", 0) - b.get("qd_mvar", 0)) / base for b in buses])
    def voltage(x):
        v = fixed.copy()
        v[variable] = x[:count] + 1j * x[count:]
        return v
    def residual(x):
        v = voltage(x)
        diff = independent_injections(data, v) - spec
        voltage_constraint = np.array([abs(v[i])**2 - buses[i]["vm_pu"]**2 for i in pv])
        return np.r_[diff.real[variable], diff.imag[pq], voltage_constraint]
    x = np.r_[fixed[variable].real, fixed[variable].imag]
    h = 1e-6
    for _ in range(25):
        f = residual(x)
        if max(abs(f)) < 1e-11:
            return voltage(x)
        j = np.empty((len(x), len(x)))
        for k in range(len(x)):
            step = np.zeros_like(x)
            step[k] = h
            j[:, k] = (residual(x + step) - residual(x - step)) / (2 * h)
        x -= np.linalg.solve(j, f)
    raise AssertionError("Bộ giải đối chiếu không hội tụ")


class PowerFlowTests(unittest.TestCase):
    def test_two_bus_exact_solution(self):
        # Không tổn thất R, không shunt: nghiệm điện áp có công thức bậc hai.
        p, q, x = 0.5, 0.2, 0.1
        case = {"base_mva": 100, "buses": [
            {"id": "S", "type": "SLACK"},
            {"id": "D", "type": "PQ", "pd_mw": 100*p, "qd_mvar": 100*q}],
            "branches": [{"from_bus": "S", "to_bus": "D", "r_pu": 0, "x_pu": x}]}
        answer = solve_power_flow(case, tolerance=1e-11)
        imag = -p*x
        real = (1 + math.sqrt(1 - 4*(imag**2 + q*x))) / 2
        expected = complex(real, imag)
        self.assertAlmostEqual(answer["buses"][1]["vm_pu"], abs(expected), places=10)
        self.assertAlmostEqual(answer["buses"][1]["va_deg"], math.degrees(np.angle(expected)), places=9)
        self.assertAlmostEqual(answer["summary"]["p_total_loss_mw"], 0, places=10)

    def test_nine_bus_independent_rectangular_solution(self):
        case = sample("luoi_9_nut.json")
        answer = solve_power_flow(case, tolerance=1e-11)
        reference = rectangular_reference(case)
        actual = np.array([r["vm_pu"] * np.exp(1j*np.deg2rad(r["va_deg"])) for r in answer["buses"]])
        np.testing.assert_allclose(actual, reference, rtol=0, atol=1e-10)
        self.assertAlmostEqual(answer["summary"]["pd_total_mw"], 315)
        self.assertLess(abs(answer["summary"]["p_balance_error_mw"]), 1e-8)
        self.assertLess(abs(answer["summary"]["q_balance_error_mvar"]), 1e-8)

    def test_jacobian_with_transformer_against_finite_difference(self):
        case = sample()
        case["branches"][0].update(tap=1.07, shift_deg=8.0)
        case["buses"][2].update(g_shunt_pu=0.02, b_shunt_pu=0.04)
        ybus, _ = build_ybus(validate_case(case))
        vm, va = np.array([1.06, 1.04, 0.97]), np.array([0.02, -0.04, -0.1])
        a, q = np.array([1, 2]), np.array([2])
        j = jacobian(ybus, vm, va, a, q)
        def f(x):
            vma, vaa = vm.copy(), va.copy()
            vaa[a], vma[q] = x[:2], x[2:]
            power = power_injections(ybus, vma, vaa)
            return np.r_[power.real[a], power.imag[q]]
        state, numeric = np.r_[va[a], vm[q]], np.empty_like(j)
        for k in range(3):
            step = np.zeros(3)
            step[k] = 1e-6
            numeric[:, k] = (f(state + step) - f(state - step)) / 2e-6
        np.testing.assert_allclose(j, numeric, atol=2e-8, rtol=2e-8)

    def test_transformer_shunt_parallel_and_open_branch(self):
        case = sample()
        case["branches"][0].update(tap=1.04, shift_deg=4)
        case["buses"][2].update(g_shunt_pu=0.015, b_shunt_pu=0.05)
        case["branches"].append(dict(case["branches"][1], id="parallel", r_pu=0.15, x_pu=0.4))
        case["branches"].append({"id": "open", "from_bus": "1", "to_bus": "3", "r_pu": 0, "x_pu": 0, "status": False})
        answer = solve_power_flow(case, tolerance=1e-11, enforce_q_limits=False)
        voltage = np.array([r["vm_pu"] * np.exp(1j*np.deg2rad(r["va_deg"])) for r in answer["buses"]])
        exact = independent_injections(case, voltage) * case["base_mva"]
        actual = np.array([complex(r["p_injection_mw"], r["q_injection_mvar"]) for r in answer["buses"]])
        np.testing.assert_allclose(actual, exact, atol=1e-10, rtol=0)
        self.assertEqual(answer["branches"][-1]["p_from_mw"], 0)
        self.assertEqual(answer["branches"][-1]["q_to_mvar"], 0)
        self.assertGreater(answer["summary"]["p_shunt_mw"], 0)
        self.assertLess(answer["summary"]["q_shunt_mvar"], 0)
        self.assertLess(abs(answer["summary"]["p_balance_error_mw"]), 1e-8)
        self.assertLess(abs(answer["summary"]["q_balance_error_mvar"]), 1e-8)
        for b, r in zip(case["branches"], answer["branches"]):
            if not b.get("status", True):
                continue
            f, t = int(b["from_bus"])-1, int(b["to_bus"])-1
            ratio = b.get("tap", 1)*np.exp(1j*np.deg2rad(b.get("shift_deg", 0)))
            current = (voltage[f]/ratio - voltage[t])/complex(b["r_pu"], b["x_pu"])
            self.assertAlmostEqual(r["p_loss_mw"], 100*b["r_pu"]*abs(current)**2, places=9)
            apparent = abs(complex(r["p_from_mw"], r["q_from_mvar"]))
            expected_ka = apparent/(math.sqrt(3)*110*abs(voltage[f]))
            self.assertAlmostEqual(r["i_from_ka"], expected_ka, places=10)

    def test_qmax_switch_preserves_generator_limit_with_local_load(self):
        case = sample("luoi_3_nut_gioi_han_q.json")
        answer = solve_power_flow(case, tolerance=1e-11)
        bus = answer["buses"][1]
        self.assertEqual(bus["type_final"], "PQ")
        self.assertEqual(bus["qg_mvar"], 10.0)
        self.assertLess(bus["vm_pu"], case["buses"][1]["vm_pu"])
        self.assertAlmostEqual(bus["q_injection_mvar"], 0.0, places=8)
        self.assertEqual(answer["q_limit_switches"][0]["bound"], "Qmax")

    def test_qmin_switch_and_disabled_enforcement(self):
        case = sample()
        case["buses"][1].update(qmin_mvar=0.0, qmax_mvar=50.0)
        limited = solve_power_flow(case, tolerance=1e-11)
        unlimited = solve_power_flow(case, tolerance=1e-11, enforce_q_limits=False)
        self.assertEqual(limited["q_limit_switches"][0]["bound"], "Qmin")
        self.assertEqual(limited["buses"][1]["qg_mvar"], 0)
        self.assertEqual(unlimited["buses"][1]["type_final"], "PV")
        self.assertAlmostEqual(unlimited["buses"][1]["vm_pu"], 1.04)
        self.assertLess(unlimited["buses"][1]["qg_mvar"], 0)
        self.assertTrue(any("Qg" in w for w in unlimited["warnings"]))

    def test_multiple_q_switches(self):
        case = sample("luoi_9_nut.json")
        # Giữ Q của cả hai nguồn tại 0 để sau lần chuyển đầu vẫn cần giải lại
        # cho nguồn kia; chỉ giới hạn một phía có thể hết vi phạm nhờ nguồn kia.
        for bus in case["buses"][1:3]:
            bus.update(qmin_mvar=0, qmax_mvar=0)
        answer = solve_power_flow(case, tolerance=1e-11)
        self.assertEqual(len(answer["q_limit_switches"]), 2)
        self.assertEqual(answer["passes"], 3)
        for row in answer["buses"][1:3]:
            self.assertEqual(row["type_final"], "PQ")
            self.assertEqual(row["qg_mvar"], 0)

    def test_slack_q_limit_is_warning_and_voltage_stays_fixed(self):
        case = sample()
        case["buses"][0]["qmax_mvar"] = 0.0
        answer = solve_power_flow(case)
        self.assertEqual(answer["buses"][0]["type_final"], "SLACK")
        self.assertEqual(answer["buses"][0]["vm_pu"], 1.06)
        self.assertTrue(any("Nút 1" in w and "Qg" in w for w in answer["warnings"]))

    def test_no_pq_and_single_slack(self):
        case = {"base_mva": 100, "buses": [{"id": 1, "type": "SLACK", "pd_mw": 5,
                "qd_mvar": 2, "g_shunt_pu": 0.01, "b_shunt_pu": 0.02}], "branches": []}
        answer = solve_power_flow(case)
        self.assertEqual(answer["iterations"], 0)
        self.assertAlmostEqual(answer["buses"][0]["pg_mw"], 6)
        self.assertAlmostEqual(answer["buses"][0]["qg_mvar"], 0)
        case["buses"].append({"id": 2, "type": "PV", "pg_mw": 20, "vm_pu": 1.01})
        case["branches"].append({"from_bus": 1, "to_bus": 2, "r_pu": 0.01, "x_pu": 0.1})
        answer = solve_power_flow(case)
        self.assertEqual(answer["buses"][1]["vm_pu"], 1.01)
        self.assertLess(answer["max_mismatch_pu"], 1e-8)

    def test_two_islands_each_with_one_slack(self):
        case = sample()
        expected = solve_power_flow(case)
        second = copy.deepcopy(case)
        for bus in second["buses"]:
            bus["id"] = "B" + bus["id"]
        for branch in second["branches"]:
            for field in ("id", "from_bus", "to_bus"):
                branch[field] = "B" + branch[field]
        case["buses"] += second["buses"]
        case["branches"] += second["branches"]
        answer = solve_power_flow(case)
        self.assertAlmostEqual(answer["summary"]["p_total_loss_mw"], 2*expected["summary"]["p_total_loss_mw"], places=9)

    def test_islands_require_exactly_one_slack(self):
        for bus in [{"id": "X", "type": "PQ"}, {"id": "X", "type": "PV"}]:
            case = sample()
            case["buses"].append(bus)
            with self.assertRaises(CaseError):
                solve_power_flow(case)
        case = sample()
        case["buses"][1]["type"] = "SLACK"
        with self.assertRaises(CaseError):
            solve_power_flow(case)

    def test_warnings_do_not_change_power_flow_constraints(self):
        case = sample()
        case["branches"][0]["rate_mva"] = 1
        case["buses"][2]["vmin_pu"] = 1.0
        answer = solve_power_flow(case)
        self.assertTrue(any("Nhánh L12" in w for w in answer["warnings"]))
        self.assertTrue(any("Nút 3" in w for w in answer["warnings"]))
        self.assertEqual(answer["buses"][2]["pg_mw"], 0)

    def test_bad_data_and_options_are_rejected(self):
        changes = [("base_mva", 0), ("base_mva", "100"), ("base_mva", float("nan")), ("buses", []), ("branches", {})]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                case = sample()
                case[key] = value
                with self.assertRaises(CaseError):
                    solve_power_flow(case)
        for values in [{"tap": 0}, {"r_pu": 0, "x_pu": 0}, {"status": "false"},
                       {"from_bus": "missing"}, {"unknown": 1}, {"rate_mva": 0}]:
            case = sample()
            case["branches"][0].update(values)
            with self.assertRaises(CaseError):
                solve_power_flow(case)
        for values in [{"vm_pu": 0}, {"id": "1"}, {"qmin_mvar": 60, "qmax_mvar": 50}, {"type": "PP"}]:
            case = sample()
            case["buses"][1].update(values)
            with self.assertRaises(CaseError):
                solve_power_flow(case)
        for options in [{"tolerance": 0}, {"tolerance": float("nan")}, {"max_iterations": 0},
                        {"max_iterations": 2.5}, {"enforce_q_limits": "true"}]:
            with self.assertRaises(CaseError):
                solve_power_flow(sample(), **options)

    def test_malformed_json_and_duplicate_keys(self):
        for text in ["{", '{"buses": [], "buses": []}', '{"base_mva": NaN}', '[]']:
            with self.assertRaises(CaseError):
                parse_case(text)

    def test_nonconvergence_never_returns_success(self):
        with self.assertRaises(PowerFlowError) as caught:
            solve_power_flow(sample(), max_iterations=1)
        self.assertGreater(caught.exception.history[-1]["max_mismatch_pu"], 1e-8)
        case = {"base_mva": 100, "buses": [{"id": 1, "type": "SLACK"},
                {"id": 2, "type": "PQ", "pd_mw": 500}],
                "branches": [{"from_bus": 1, "to_bus": 2, "r_pu": 0, "x_pu": 0.5}]}
        with self.assertRaises(PowerFlowError):
            solve_power_flow(case)

    def test_input_is_not_modified(self):
        case = sample("luoi_3_nut_gioi_han_q.json")
        before = copy.deepcopy(case)
        solve_power_flow(case)
        self.assertEqual(case, before)

    def test_cli_exports_and_failure_exit_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, report = Path(tmp)/"result.json", Path(tmp)/"report.txt"
            command = [sys.executable, str(ROOT/"powerflow.py"), str(ROOT/"examples/luoi_3_nut.json"),
                       "--output", str(output), "--report", str(report)]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["converged"])
            self.assertIn("Tổng tổn thất P", report.read_text(encoding="utf-8"))
            failed_output = Path(tmp)/"failed.json"
            result = subprocess.run(command[:3] + ["--max-iter", "1", "--output", str(failed_output)],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 2)
            self.assertFalse(failed_output.exists())


if __name__ == "__main__":
    unittest.main()
