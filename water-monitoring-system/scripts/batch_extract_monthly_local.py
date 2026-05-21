"""
官厅水库 - 月度水体提取批处理脚本 (Sentinel-2 MNDWI + Otsu)
直接在本机 Python 环境运行

数据: Sentinel-2 L2A B3(10m) + B11(20m)
方法: MNDWI = (B3 - B11) / (B3 + B11), Otsu自动阈值
源数据CRS: EPSG:32650 (UTM Zone 50N)
"""

import os
import json
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from rasterio.features import shapes
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform as shapely_transform

# ============================================================
# 配置
# ============================================================
INPUT_DIR = "/Users/tls/code/水利信息/EXP3/raw_sentinel2"
OUTPUT_DIR = "/Users/tls/code/水利信息/EXP3/water-monitoring-system/public/data/water_layers/monthly"
TIMESERIES_OUTPUT = "/Users/tls/code/水利信息/EXP3/water-monitoring-system/public/data/area_timeseries_monthly.json"

# 官厅水库 ROI (EPSG:4326)
ROI_WGS84 = {
    "west": 115.43,
    "east": 115.93,
    "south": 40.18,
    "north": 40.40
}

# 碎斑剔除阈值 (m²)
MIN_AREA_M2 = 5000

# ============================================================
# 坐标转换
# ============================================================
to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)
to_wgs = Transformer.from_crs("EPSG:32650", "EPSG:4326", always_xy=True)

ROI_UTM_XMIN, ROI_UTM_YMIN = to_utm.transform(ROI_WGS84["west"], ROI_WGS84["south"])
ROI_UTM_XMAX, ROI_UTM_YMAX = to_utm.transform(ROI_WGS84["east"], ROI_WGS84["north"])


def otsu_threshold(data):
    """Otsu 自动阈值 (适用于浮点MNDWI值)"""
    valid = data[~np.isnan(data)].flatten()
    if len(valid) == 0:
        return 0.0

    # 将数据量化为256个bin
    hist_min, hist_max = valid.min(), valid.max()
    if hist_max - hist_min < 1e-6:
        return 0.0

    nbins = 256
    hist, bin_edges = np.histogram(valid, bins=nbins, range=(hist_min, hist_max))
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

    # Otsu 方法
    total = hist.sum()
    sum_total = (hist * bin_centers).sum()

    best_thresh = 0.0
    best_var = 0.0
    w0 = 0
    sum0 = 0.0

    for i in range(nbins):
        w0 += hist[i]
        if w0 == 0:
            continue
        w1 = total - w0
        if w1 == 0:
            break

        sum0 += hist[i] * bin_centers[i]
        mean0 = sum0 / w0
        mean1 = (sum_total - sum0) / w1

        var_between = w0 * w1 * (mean0 - mean1) ** 2
        if var_between > best_var:
            best_var = var_between
            best_thresh = bin_centers[i]

    return best_thresh


def transform_polygon_to_wgs84(poly):
    """UTM多边形转WGS84"""
    def utm_to_wgs(x, y):
        lng, lat = to_wgs.transform(x, y)
        return lng, lat

    wgs_poly = shapely_transform(utm_to_wgs, poly)
    return mapping(wgs_poly)


def process_single_month(month_dir, month_label):
    """处理单月数据: B3+B11 → MNDWI → Otsu → 矢量化 → 面积"""

    print(f"\n{'='*50}")
    print(f"处理月份: {month_label}")
    print(f"{'='*50}")

    # 查找B3和B11文件
    files = os.listdir(month_dir)
    b3_file = next((f for f in files if 'B03' in f and f.endswith('.jp2')), None)
    b11_file = next((f for f in files if 'B11' in f and f.endswith('.jp2')), None)

    if not b3_file or not b11_file:
        print(f"  [跳过] 缺少波段文件: B3={b3_file}, B11={b11_file}")
        return None

    b3_path = os.path.join(month_dir, b3_file)
    b11_path = os.path.join(month_dir, b11_file)

    # 检查B3文件大小是否合理
    if os.path.getsize(b3_path) < 1_000_000:
        print(f"  [跳过] B3文件异常小 ({os.path.getsize(b3_path)} bytes)")
        return None

    # 1. 读取 B3 (10m) ROI区域
    print("  1. 读取 B3 (10m)...")
    with rasterio.open(b3_path) as ds_b3:
        window_b3 = from_bounds(ROI_UTM_XMIN, ROI_UTM_YMIN, ROI_UTM_XMAX, ROI_UTM_YMAX, ds_b3.transform)
        b3_arr = ds_b3.read(1, window=window_b3).astype(np.float32)
        b3_transform = ds_b3.window_transform(window_b3)
        print(f"     B3 ROI尺寸: {b3_arr.shape}")

    # 2. 读取 B11 (20m) 并重采样到10m
    print("  2. 读取 B11 (20m → 重采样到10m)...")
    with rasterio.open(b11_path) as ds_b11:
        # 使用B3的窗口尺寸作为目标尺寸
        window_b11 = from_bounds(ROI_UTM_XMIN, ROI_UTM_YMIN, ROI_UTM_XMAX, ROI_UTM_YMAX, ds_b11.transform)
        b11_arr = ds_b11.read(
            1,
            window=window_b11,
            out_shape=b3_arr.shape,
            resampling=Resampling.bilinear
        ).astype(np.float32)
        print(f"     B11 重采样后尺寸: {b11_arr.shape}")

    # 3. 计算 MNDWI
    print("  3. 计算 MNDWI = (B3 - B11) / (B3 + B11)...")
    denom = b3_arr + b11_arr
    # 避免除以零，标记无效区域
    valid_mask = (denom > 0) & (b3_arr > 0)
    mndwi = np.where(valid_mask, (b3_arr - b11_arr) / denom, np.nan)

    valid_count = np.sum(valid_mask)
    print(f"     有效像元: {valid_count} ({valid_count/mndwi.size*100:.1f}%)")

    if valid_count == 0:
        print("  [WARNING] 无有效像元!")
        return None

    # 4. Otsu 自动阈值
    print("  4. Otsu 自动阈值...")
    threshold = otsu_threshold(mndwi[valid_mask])
    print(f"     阈值: {threshold:.4f}")

    # MNDWI > threshold → 水体
    water_mask = ((mndwi > threshold) & valid_mask).astype(np.uint8)
    water_pixels = water_mask.sum()
    print(f"     水体像元数: {water_pixels} ({water_pixels/valid_count*100:.1f}%)")

    if water_pixels == 0:
        print("  [WARNING] 未检测到水体!")
        return 0.0

    # 5. 栅格转矢量
    print("  5. 栅格转矢量...")
    polygons_utm = []
    for geom, value in shapes(water_mask, mask=water_mask == 1, transform=b3_transform):
        if value == 1:
            poly = shape(geom)
            polygons_utm.append(poly)
    print(f"     原始多边形数: {len(polygons_utm)}")

    # 6. 碎斑剔除
    print(f"  6. 碎斑剔除 (阈值={MIN_AREA_M2}m²)...")
    kept = [p for p in polygons_utm if p.area >= MIN_AREA_M2]
    removed = len(polygons_utm) - len(kept)
    print(f"     保留: {len(kept)}, 剔除: {removed}")

    if not kept:
        print("  [WARNING] 剔除后无多边形!")
        return 0.0

    # 7. 面积计算
    total_area_m2 = sum(p.area for p in kept)
    total_area_km2 = round(total_area_m2 / 1_000_000, 2)
    print(f"  7. 面积: {total_area_km2} km²")

    # 8. 导出 GeoJSON
    print("  8. 导出 GeoJSON...")
    features = []
    for poly in kept:
        wgs_geom = transform_polygon_to_wgs84(poly)
        features.append({
            "type": "Feature",
            "properties": {
                "month": month_label,
                "water_area_km2": round(poly.area / 1_000_000, 4)
            },
            "geometry": wgs_geom
        })

    geojson = {"type": "FeatureCollection", "features": features}
    output_path = os.path.join(OUTPUT_DIR, f"water_{month_label}.geojson")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, ensure_ascii=False)

    file_size = os.path.getsize(output_path)
    print(f"     导出: {output_path} ({file_size/1024:.0f} KB)")
    print(f"  [完成] {month_label}: {total_area_km2} km², {len(kept)} 个多边形")

    return total_area_km2


def main():
    print("=" * 60)
    print("官厅水库 月度水体提取 (Sentinel-2 MNDWI + Otsu)")
    print(f"输入目录: {INPUT_DIR}")
    print(f"碎斑阈值: {MIN_AREA_M2} m²")
    print("=" * 60)

    # 查找月度数据目录
    month_dirs = sorted([d for d in os.listdir(INPUT_DIR) if d.startswith("2024_") and os.path.isdir(os.path.join(INPUT_DIR, d))])
    print(f"\n找到 {len(month_dirs)} 个月度目录: {month_dirs}")

    timeseries_data = []

    for month_dir_name in month_dirs:
        month_path = os.path.join(INPUT_DIR, month_dir_name)
        area_km2 = process_single_month(month_path, month_dir_name)

        if area_km2 is not None:
            timeseries_data.append({
                "date": month_dir_name,
                "water_area_km2": area_km2
            })

    # 导出时间序列
    if timeseries_data:
        timeseries_data.sort(key=lambda x: x["date"])
        ts_json = {
            "reservoir": "官厅水库",
            "reservoir_en": "Guanting Reservoir",
            "unit": "km2",
            "scale": "monthly",
            "year": 2024,
            "data": timeseries_data
        }
        with open(TIMESERIES_OUTPUT, 'w', encoding='utf-8') as f:
            json.dump(ts_json, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] 月度时间序列: {TIMESERIES_OUTPUT}")

        # 月度变化统计
        areas = [d["water_area_km2"] for d in timeseries_data]
        print(f"\n[统计] {len(areas)} 个月:")
        for d in timeseries_data:
            print(f"  {d['date']}: {d['water_area_km2']} km²")
        print(f"  最大: {max(areas)} km² | 最小: {min(areas)} km² | 均值: {np.mean(areas):.2f} km²")

    print("\n" + "=" * 60)
    print("月度处理完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
