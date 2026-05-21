"""
官厅水库 - 年度水体提取批处理脚本 (rasterio版)
直接在本机 Python 环境运行，无需 QGIS

数据: ArcGIS Living Atlas / ESRI 10m Land Cover
水体类别值: 2 (ESRI Land Cover 编码)
源数据CRS: EPSG:32650 (UTM Zone 50N)
"""

import os
import json
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.features import shapes
from rasterio.transform import from_bounds as transform_from_bounds
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
import fiona

# ============================================================
# 配置
# ============================================================
INPUT_DIR = "/Users/tls/code/水利信息/EXP3/raw_tif"
OUTPUT_DIR = "/Users/tls/code/水利信息/EXP3/water-monitoring-system/public/data/water_layers/annual"
ROI_OUTPUT = "/Users/tls/code/水利信息/EXP3/water-monitoring-system/public/data/reservoir_roi.geojson"
TIMESERIES_OUTPUT = "/Users/tls/code/水利信息/EXP3/water-monitoring-system/public/data/area_timeseries.json"

# ESRI Land Cover 水体类别值: 1=Water, 4=Flooded Vegetation
WATER_CLASS_VALUES = [1, 4]

# 官厅水库 ROI (EPSG:4326)
ROI_WGS84 = {
    "west": 115.43,
    "east": 115.93,
    "south": 40.18,
    "north": 40.40
}

# 碎斑剔除: 50像元 × 100m² = 5000m²
MIN_AREA_M2 = 5000

# ============================================================
# 坐标转换准备
# ============================================================
to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)
to_wgs = Transformer.from_crs("EPSG:32650", "EPSG:4326", always_xy=True)

ROI_UTM_XMIN, ROI_UTM_YMIN = to_utm.transform(ROI_WGS84["west"], ROI_WGS84["south"])
ROI_UTM_XMAX, ROI_UTM_YMAX = to_utm.transform(ROI_WGS84["east"], ROI_WGS84["north"])


def extract_year_from_filename(filename):
    """从文件名提取年份: 50T_20170101-20180101.tif → 2017"""
    for y in range(2017, 2026):
        if str(y) in filename:
            # 取文件名中出现的第一个年份
            idx = filename.index(str(y))
            return y
    return None


def create_roi_geojson():
    """生成 ROI GeoJSON"""
    roi = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "官厅水库分析框", "name_en": "Guanting Reservoir ROI"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [ROI_WGS84["west"], ROI_WGS84["south"]],
                    [ROI_WGS84["east"], ROI_WGS84["south"]],
                    [ROI_WGS84["east"], ROI_WGS84["north"]],
                    [ROI_WGS84["west"], ROI_WGS84["north"]],
                    [ROI_WGS84["west"], ROI_WGS84["south"]]
                ]]
            }
        }]
    }
    os.makedirs(os.path.dirname(ROI_OUTPUT), exist_ok=True)
    with open(ROI_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(roi, f, ensure_ascii=False, indent=2)
    print(f"[OK] ROI 导出: {ROI_OUTPUT}")


def process_single_year(tif_path, year):
    """处理单年数据: 裁剪 → 提取水体 → 矢量化 → 碎斑剔除 → 面积计算 → 导出GeoJSON"""

    print(f"\n{'='*50}")
    print(f"处理年份: {year}")
    print(f"{'='*50}")

    # 1. 读取 ROI 窗口
    print("  1. 裁剪到 ROI...")
    with rasterio.open(tif_path) as ds:
        window = from_bounds(ROI_UTM_XMIN, ROI_UTM_YMIN, ROI_UTM_XMAX, ROI_UTM_YMAX, ds.transform)
        roi_arr = ds.read(1, window=window)
        roi_transform = ds.window_transform(window)
        print(f"     ROI尺寸: {roi_arr.shape}, 像元数: {roi_arr.size}")

    # 2. 水体提取 (值1=Water, 值4=Flooded Vegetation)
    print(f"  2. 水体提取 (类别值={WATER_CLASS_VALUES})...")
    water_mask = np.isin(roi_arr, WATER_CLASS_VALUES).astype(np.uint8)
    water_pixels = water_mask.sum()
    print(f"     水体像元数: {water_pixels} ({water_pixels/roi_arr.size*100:.1f}%)")

    if water_pixels == 0:
        print("     [WARNING] 未检测到水体!")
        return 0.0

    # 3. 栅格转矢量
    print("  3. 栅格转矢量...")
    polygons_utm = []
    for geom, value in shapes(water_mask, mask=water_mask == 1, transform=roi_transform):
        if value == 1:
            poly = shape(geom)
            polygons_utm.append(poly)
    print(f"     原始多边形数: {len(polygons_utm)}")

    # 4. 碎斑剔除 (UTM下面积 < 5000m²)
    print(f"  4. 碎斑剔除 (阈值={MIN_AREA_M2}m²)...")
    kept = []
    removed = 0
    for poly in polygons_utm:
        if poly.area >= MIN_AREA_M2:
            kept.append(poly)
        else:
            removed += 1
    print(f"     保留: {len(kept)}, 剔除: {removed}")

    if not kept:
        print("     [WARNING] 剔除后无多边形!")
        return 0.0

    # 5. 计算总面积 (UTM投影下, m² → km²)
    total_area_m2 = sum(p.area for p in kept)
    total_area_km2 = round(total_area_m2 / 1_000_000, 2)
    print(f"  5. 面积计算 (UTM Zone 50N): {total_area_km2} km²")

    # 6. 转换到 WGS84 并导出 GeoJSON
    print("  6. 转换到 EPSG:4326 导出 GeoJSON...")
    features = []
    for poly in kept:
        # UTM → WGS84 坐标转换
        wgs_coords = transform_polygon_to_wgs84(poly)
        features.append({
            "type": "Feature",
            "properties": {
                "year": year,
                "water_area_km2": round(poly.area / 1_000_000, 4)
            },
            "geometry": wgs_coords
        })

    geojson = {"type": "FeatureCollection", "features": features}
    output_path = os.path.join(OUTPUT_DIR, f"water_{year}.geojson")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, ensure_ascii=False)

    file_size = os.path.getsize(output_path)
    print(f"     导出: {output_path} ({file_size/1024:.0f} KB)")
    print(f"  [完成] {year}: {total_area_km2} km², {len(kept)} 个多边形")

    return total_area_km2


def transform_polygon_to_wgs84(poly):
    """将 UTM 多边形坐标转换为 WGS84 GeoJSON geometry"""
    from shapely.ops import transform as shapely_transform

    def utm_to_wgs(x, y):
        lng, lat = to_wgs.transform(x, y)
        return lng, lat

    wgs_poly = shapely_transform(utm_to_wgs, poly)
    return mapping(wgs_poly)


def main():
    print("=" * 60)
    print("官厅水库 年度水体提取 批处理脚本")
    print("数据源: ESRI 10m Land Cover (ArcGIS Living Atlas)")
    print(f"水体类别: {WATER_CLASS_VALUES} | 投影: EPSG:32650")
    print(f"碎斑阈值: {MIN_AREA_M2} m² (50像元×100m²)")
    print("=" * 60)

    # 生成 ROI
    create_roi_geojson()

    # 查找 tif 文件
    tif_files = sorted([f for f in os.listdir(INPUT_DIR) if f.endswith('.tif')])
    print(f"\n找到 {len(tif_files)} 个 .tif 文件")

    timeseries_data = []

    for tif_name in tif_files:
        year = extract_year_from_filename(tif_name)
        if year is None:
            print(f"  [SKIP] 无法识别年份: {tif_name}")
            continue

        tif_path = os.path.join(INPUT_DIR, tif_name)
        area_km2 = process_single_year(tif_path, year)
        timeseries_data.append({
            "date": str(year),
            "water_area_km2": area_km2
        })

    # 导出时间序列
    timeseries_data.sort(key=lambda x: x["date"])
    ts_json = {
        "reservoir": "官厅水库",
        "reservoir_en": "Guanting Reservoir",
        "unit": "km2",
        "data": timeseries_data
    }
    with open(TIMESERIES_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(ts_json, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 时间序列: {TIMESERIES_OUTPUT}")

    # 波动率验证
    if len(timeseries_data) >= 5:
        areas = [d["water_area_km2"] for d in timeseries_data[-5:]]
        a_max, a_min = max(areas), min(areas)
        a_mean = np.mean(areas)
        delta_a = (a_max - a_min) / a_mean * 100
        print(f"\n[验证] 近5年数据:")
        for d in timeseries_data[-5:]:
            print(f"  {d['date']}: {d['water_area_km2']} km²")
        print(f"  ΔA = ({a_max}-{a_min})/{a_mean:.1f} = {delta_a:.1f}%", end="")
        print(f" {'✓ 满足≥15%' if delta_a >= 15 else '✗ 不足15%'}")

    print("\n" + "=" * 60)
    print("全部处理完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
