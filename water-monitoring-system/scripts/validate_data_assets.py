"""
数据资产自查验证脚本
在交付前端联调前运行，确保数据规范性

检查项:
1. 时间序列标识对齐 - date字段与GeoJSON文件名一致性
2. 坐标顺序验证 - 确认 [Lng, Lat] 范围合理性
3. 属性字段规范 - water_area_km2 字段存在性
4. 文件完整性 - 9年数据无缺失
5. ROI分析框验证
6. 月度数据验证 - 时序对齐、坐标、属性
"""

import os
import json

BASE_DIR = "/Users/tls/code/水利信息/EXP3/water-monitoring-system/public/data"
ANNUAL_DIR = os.path.join(BASE_DIR, "water_layers/annual")
MONTHLY_DIR = os.path.join(BASE_DIR, "water_layers/monthly")
TIMESERIES_FILE = os.path.join(BASE_DIR, "area_timeseries.json")
TIMESERIES_MONTHLY_FILE = os.path.join(BASE_DIR, "area_timeseries_monthly.json")
ROI_FILE = os.path.join(BASE_DIR, "reservoir_roi.geojson")

EXPECTED_YEARS = [str(y) for y in range(2017, 2026)]
EXPECTED_MONTHS = ["2024_05", "2024_06", "2024_07", "2024_08", "2024_09", "2024_10"]
GUANTING_BOUNDS = {"lng": (115.0, 116.5), "lat": (39.8, 40.8)}

errors = []
warnings = []


def check_file_exists(path, label):
    if not os.path.exists(path):
        errors.append(f"[缺失] {label}: {path}")
        return False
    return True


def check_timeseries_alignment():
    """检查时间序列date字段与GeoJSON文件名对齐"""
    print("\n[检查1] 时间序列标识对齐...")

    if not check_file_exists(TIMESERIES_FILE, "年度时间序列"):
        return

    with open(TIMESERIES_FILE, 'r') as f:
        ts = json.load(f)

    dates_in_json = [d["date"] for d in ts["data"]]

    for date_str in dates_in_json:
        geojson_path = os.path.join(ANNUAL_DIR, f"water_{date_str}.geojson")
        if not os.path.exists(geojson_path):
            errors.append(f"[对齐错误] 时序JSON中有 date='{date_str}', 但文件 water_{date_str}.geojson 不存在")
        else:
            print(f"  ✓ {date_str} → water_{date_str}.geojson")

    geojson_files = [f for f in os.listdir(ANNUAL_DIR) if f.endswith('.geojson')]
    for gf in geojson_files:
        date_part = gf.replace("water_", "").replace(".geojson", "")
        if date_part not in dates_in_json:
            warnings.append(f"[孤立文件] {gf} 存在但不在时序JSON的date列表中")


def check_coordinate_order():
    """验证GeoJSON坐标顺序为 [Lng, Lat]"""
    print("\n[检查2] 坐标顺序验证 (应为 [Lng, Lat])...")

    geojson_files = [os.path.join(ANNUAL_DIR, f) for f in os.listdir(ANNUAL_DIR) if f.endswith('.geojson')]

    for gf in geojson_files:
        with open(gf, 'r') as f:
            data = json.load(f)

        for feature in data.get("features", []):
            coords = feature["geometry"]["coordinates"]
            flat_coords = flatten_coords(coords)
            if flat_coords:
                first = flat_coords[0]
                lng, lat = first[0], first[1]
                if GUANTING_BOUNDS["lat"][0] <= lng <= GUANTING_BOUNDS["lat"][1]:
                    errors.append(f"[坐标倒置] {os.path.basename(gf)}: 首坐标 [{lng},{lat}] 疑似 [Lat,Lng] 顺序错误")
                elif GUANTING_BOUNDS["lng"][0] <= lng <= GUANTING_BOUNDS["lng"][1]:
                    print(f"  ✓ {os.path.basename(gf)}: 坐标顺序正确 [Lng, Lat]")
                else:
                    warnings.append(f"[坐标异常] {os.path.basename(gf)}: 首坐标 [{lng},{lat}] 超出官厅水库范围")
                break


def flatten_coords(coords):
    """递归展平坐标数组"""
    if not coords:
        return []
    if isinstance(coords[0], (int, float)):
        return [coords]
    result = []
    for c in coords:
        result.extend(flatten_coords(c))
    return result


def check_properties():
    """验证属性字段规范性"""
    print("\n[检查3] 属性字段规范验证...")

    geojson_files = [os.path.join(ANNUAL_DIR, f) for f in os.listdir(ANNUAL_DIR) if f.endswith('.geojson')]

    for gf in geojson_files:
        with open(gf, 'r') as f:
            data = json.load(f)

        for feature in data.get("features", []):
            props = feature.get("properties", {})
            if "water_area_km2" not in props:
                errors.append(f"[字段缺失] {os.path.basename(gf)}: 缺少 water_area_km2 属性")
                break
            if "AREA" in props or "Water_Area" in props:
                warnings.append(f"[命名不规范] {os.path.basename(gf)}: 发现非标准字段名")
                break
        else:
            print(f"  ✓ {os.path.basename(gf)}: 属性字段规范")


def check_completeness():
    """检查9年数据完整性"""
    print("\n[检查4] 数据完整性 (2017-2025)...")

    for year in EXPECTED_YEARS:
        path = os.path.join(ANNUAL_DIR, f"water_{year}.geojson")
        if os.path.exists(path):
            size = os.path.getsize(path)
            print(f"  ✓ {year}: water_{year}.geojson ({size} bytes)")
        else:
            errors.append(f"[年份缺失] {year} 年数据文件不存在")


def check_roi():
    """验证ROI文件"""
    print("\n[检查5] ROI 分析框验证...")

    if not check_file_exists(ROI_FILE, "ROI GeoJSON"):
        return

    with open(ROI_FILE, 'r') as f:
        roi = json.load(f)

    features = roi.get("features", [])
    if not features:
        errors.append("[ROI] 无要素")
        return

    coords = flatten_coords(features[0]["geometry"]["coordinates"])
    lngs = [c[0] for c in coords]
    lats = [c[1] for c in coords]

    if min(lngs) >= 115 and max(lngs) <= 116 and min(lats) >= 40 and max(lats) <= 41:
        print(f"  ✓ ROI范围合理: Lng[{min(lngs)}, {max(lngs)}] Lat[{min(lats)}, {max(lats)}]")
    else:
        warnings.append(f"[ROI] 范围可能偏大: Lng[{min(lngs)}, {max(lngs)}] Lat[{min(lats)}, {max(lats)}]")


def check_monthly_timeseries_alignment():
    """检查月度时间序列date字段与GeoJSON文件名对齐"""
    print("\n[检查6] 月度时间序列标识对齐...")

    if not check_file_exists(TIMESERIES_MONTHLY_FILE, "月度时间序列"):
        return

    with open(TIMESERIES_MONTHLY_FILE, 'r') as f:
        ts = json.load(f)

    dates_in_json = [d["date"] for d in ts["data"]]

    for date_str in dates_in_json:
        geojson_path = os.path.join(MONTHLY_DIR, f"water_{date_str}.geojson")
        if not os.path.exists(geojson_path):
            errors.append(f"[月度对齐错误] 时序JSON中有 date='{date_str}', 但文件 water_{date_str}.geojson 不存在")
        else:
            print(f"  ✓ {date_str} → water_{date_str}.geojson")

    geojson_files = [f for f in os.listdir(MONTHLY_DIR) if f.endswith('.geojson')]
    for gf in geojson_files:
        date_part = gf.replace("water_", "").replace(".geojson", "")
        if date_part not in dates_in_json:
            warnings.append(f"[月度孤立文件] {gf} 存在但不在月度时序JSON的date列表中")


def check_monthly_completeness():
    """检查月度数据完整性 (2024_05 ~ 2024_10)"""
    print("\n[检查7] 月度数据完整性 (2024_05-2024_10)...")

    for month in EXPECTED_MONTHS:
        path = os.path.join(MONTHLY_DIR, f"water_{month}.geojson")
        if os.path.exists(path):
            size = os.path.getsize(path)
            print(f"  ✓ {month}: water_{month}.geojson ({size} bytes)")
        else:
            errors.append(f"[月份缺失] {month} 月度数据文件不存在")


def check_monthly_coordinates_and_properties():
    """验证月度GeoJSON坐标顺序和属性字段"""
    print("\n[检查8] 月度坐标顺序与属性验证...")

    if not os.path.exists(MONTHLY_DIR):
        errors.append("[月度目录] monthly/ 目录不存在")
        return

    geojson_files = [os.path.join(MONTHLY_DIR, f) for f in os.listdir(MONTHLY_DIR) if f.endswith('.geojson')]

    for gf in geojson_files:
        with open(gf, 'r') as f:
            data = json.load(f)

        basename = os.path.basename(gf)

        # 坐标验证
        for feature in data.get("features", []):
            coords = feature["geometry"]["coordinates"]
            flat_coords = flatten_coords(coords)
            if flat_coords:
                first = flat_coords[0]
                lng, lat = first[0], first[1]
                if GUANTING_BOUNDS["lng"][0] <= lng <= GUANTING_BOUNDS["lng"][1]:
                    print(f"  ✓ {basename}: 坐标正确 [Lng, Lat]")
                elif GUANTING_BOUNDS["lat"][0] <= lng <= GUANTING_BOUNDS["lat"][1]:
                    errors.append(f"[月度坐标倒置] {basename}: 首坐标 [{lng},{lat}] 疑似 [Lat,Lng]")
                else:
                    warnings.append(f"[月度坐标异常] {basename}: 首坐标 [{lng},{lat}] 超出范围")
                break

        # 属性验证
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            if "water_area_km2" not in props:
                errors.append(f"[月度字段缺失] {basename}: 缺少 water_area_km2 属性")
                break
        else:
            print(f"  ✓ {basename}: 属性字段规范")


def check_delta_a():
    """验证水文波动约束 ΔA ≥ 15%"""
    print("\n[检查9] 水文波动约束验证 (ΔA ≥ 15%)...")

    if not os.path.exists(TIMESERIES_FILE):
        return

    with open(TIMESERIES_FILE, 'r') as f:
        ts = json.load(f)

    areas = [d["water_area_km2"] for d in ts["data"]]
    if len(areas) < 5:
        warnings.append("[波动率] 数据不足5年,无法验证")
        return

    recent_5 = areas[-5:]
    a_max = max(recent_5)
    a_min = min(recent_5)
    a_mean = sum(recent_5) / len(recent_5)
    delta_a = (a_max - a_min) / a_mean * 100

    print(f"  近5年: max={a_max}, min={a_min}, mean={a_mean:.2f}")
    print(f"  ΔA = ({a_max} - {a_min}) / {a_mean:.2f} × 100% = {delta_a:.1f}%")

    if delta_a >= 15:
        print(f"  ✓ ΔA = {delta_a:.1f}% ≥ 15%, 满足水文波动约束")
    else:
        warnings.append(f"[波动率] ΔA = {delta_a:.1f}% < 15%, 不满足约束")


def main():
    print("=" * 60)
    print("数据资产自查验证")
    print("官厅水库 水体动态监测系统")
    print("=" * 60)

    check_timeseries_alignment()
    check_coordinate_order()
    check_properties()
    check_completeness()
    check_roi()
    check_monthly_timeseries_alignment()
    check_monthly_completeness()
    check_monthly_coordinates_and_properties()
    check_delta_a()

    print("\n" + "=" * 60)
    print("验证结果汇总")
    print("=" * 60)

    if errors:
        print(f"\n❌ 错误 ({len(errors)}):")
        for e in errors:
            print(f"  {e}")
    else:
        print("\n✓ 无错误")

    if warnings:
        print(f"\n⚠ 警告 ({len(warnings)}):")
        for w in warnings:
            print(f"  {w}")
    else:
        print("✓ 无警告")

    if not errors:
        print("\n✅ 数据资产自查通过，可交付前端联调")
    else:
        print("\n❌ 存在错误，请修复后重新验证")

    return len(errors) == 0


if __name__ == "__main__":
    main()
