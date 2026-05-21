"""
官厅水库 - 年度土地覆盖水体提取全自动批处理脚本
在 QGIS Python 控制台中运行

使用前修改:
1. INPUT_DIR: 存放 2017-2025 年度 .tif 文件的目录
2. OUTPUT_DIR: 输出 GeoJSON 的目标目录 (即前端 public/data/water_layers/annual/)
3. ROI_OUTPUT: 输出 reservoir_roi.geojson 的路径

数据来源: ArcGIS Living Atlas (Sentinel-2 10m Land Cover)
水体类别值: 1 (Water) + 4 (Flooded Vegetation)
"""

import os
import json
import numpy as np
from osgeo import gdal, ogr, osr
from pathlib import Path

# ============================================================
# 用户配置区 - 请根据实际路径修改
# ============================================================
INPUT_DIR = "/Users/tls/code/水利信息/EXP3/raw_tif"  # 存放下载的 .tif 文件
OUTPUT_DIR = "/Users/tls/code/水利信息/EXP3/water-monitoring-system/public/data/water_layers/annual"
ROI_OUTPUT = "/Users/tls/code/水利信息/EXP3/water-monitoring-system/public/data/reservoir_roi.geojson"
TIMESERIES_OUTPUT = "/Users/tls/code/水利信息/EXP3/water-monitoring-system/public/data/area_timeseries.json"

# 官厅水库 ROI 边界 (经度, 纬度) - EPSG:4326
# 根据实际水库范围可微调
ROI_BOUNDS = {
    "west": 115.43,
    "east": 115.93,
    "south": 40.18,
    "north": 40.40
}

# Living Atlas 土地覆盖中水体的像元值: 1=Water, 4=Flooded Vegetation
WATER_CLASS_VALUES = [1, 4]

# UTM 投影: 官厅水库经度115.6 → Zone 50N → EPSG:32650
UTM_EPSG = 32650

# 碎斑剔除阈值: 10m分辨率, 50像元 = 5000 m²
MIN_AREA_M2 = 5000

# ============================================================
# 主处理流程
# ============================================================

def create_roi_geojson():
    """生成 ROI 分析框 GeoJSON"""
    roi = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "name": "官厅水库分析框",
                "name_en": "Guanting Reservoir ROI"
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [ROI_BOUNDS["west"], ROI_BOUNDS["south"]],
                    [ROI_BOUNDS["east"], ROI_BOUNDS["south"]],
                    [ROI_BOUNDS["east"], ROI_BOUNDS["north"]],
                    [ROI_BOUNDS["west"], ROI_BOUNDS["north"]],
                    [ROI_BOUNDS["west"], ROI_BOUNDS["south"]]
                ]]
            }
        }]
    }
    os.makedirs(os.path.dirname(ROI_OUTPUT), exist_ok=True)
    with open(ROI_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(roi, f, ensure_ascii=False, indent=2)
    print(f"[OK] ROI 已导出: {ROI_OUTPUT}")


def clip_raster_to_roi(input_path, output_path):
    """裁剪栅格到 ROI 范围"""
    gdal.Warp(
        output_path, input_path,
        outputBounds=(ROI_BOUNDS["west"], ROI_BOUNDS["south"],
                      ROI_BOUNDS["east"], ROI_BOUNDS["north"]),
        outputBoundsSRS="EPSG:4326",
        dstSRS="EPSG:4326",
        resampleAlg="near",
        format="GTiff"
    )


def extract_water_binary(input_path, output_path):
    """
    提取水体: 将水体像元(值=1,4)设为1, 非水区设为NoData
    严格遵循任务要求: 非水区域赋NoData, 不设为0
    """
    ds = gdal.Open(input_path)
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray()

    water_mask = np.isin(arr, WATER_CLASS_VALUES)
    water = np.where(water_mask, 1, 0).astype(np.float32)
    water[~water_mask] = np.nan

    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(output_path, ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Float32)
    out_ds.SetGeoTransform(ds.GetGeoTransform())
    out_ds.SetProjection(ds.GetProjection())
    out_band = out_ds.GetRasterBand(1)
    out_band.SetNoDataValue(np.nan)
    out_band.WriteArray(water)
    out_band.FlushCache()
    out_ds = None
    ds = None


def polygonize_water(raster_path, vector_path):
    """栅格转矢量 (Polygonize), 只对有效像元(值=1)生成多边形"""
    ds = gdal.Open(raster_path)
    band = ds.GetRasterBand(1)

    driver = ogr.GetDriverByName("ESRI Shapefile")
    if os.path.exists(vector_path):
        driver.DeleteDataSource(vector_path)
    out_ds = driver.CreateDataSource(vector_path)
    srs = osr.SpatialReference()
    srs.ImportFromWkt(ds.GetProjection())
    layer = out_ds.CreateLayer("water", srs, ogr.wkbPolygon)
    field = ogr.FieldDefn("DN", ogr.OFTInteger)
    layer.CreateField(field)

    gdal.Polygonize(band, band, layer, 0, [], callback=None)
    out_ds = None
    ds = None


def reproject_to_utm(input_shp, output_shp):
    """重投影矢量到 UTM 用于面积计算"""
    in_ds = ogr.Open(input_shp)
    in_layer = in_ds.GetLayer()

    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(UTM_EPSG)

    driver = ogr.GetDriverByName("ESRI Shapefile")
    if os.path.exists(output_shp):
        driver.DeleteDataSource(output_shp)
    out_ds = driver.CreateDataSource(output_shp)
    out_layer = out_ds.CreateLayer("water_utm", target_srs, ogr.wkbPolygon)

    field = ogr.FieldDefn("area_m2", ogr.OFTReal)
    out_layer.CreateField(field)

    source_srs = in_layer.GetSpatialRef()
    transform = osr.CoordinateTransformation(source_srs, target_srs)

    for feature in in_layer:
        geom = feature.GetGeometryRef()
        geom.Transform(transform)
        new_feature = ogr.Feature(out_layer.GetLayerDefn())
        new_feature.SetGeometry(geom)
        new_feature.SetField("area_m2", geom.GetArea())
        out_layer.CreateFeature(new_feature)

    out_ds = None
    in_ds = None


def filter_small_polygons_and_export(utm_shp, output_geojson, year):
    """
    自适应碎斑剔除 + 导出标准 GeoJSON (EPSG:4326, [Lng, Lat])
    剔除面积 < 5000 m² 的碎片
    """
    in_ds = ogr.Open(utm_shp)
    in_layer = in_ds.GetLayer()

    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(4326)

    source_srs = in_layer.GetSpatialRef()
    transform = osr.CoordinateTransformation(source_srs, target_srs)

    features = []
    total_area_m2 = 0.0
    kept_count = 0
    removed_count = 0

    for feature in in_layer:
        area = feature.GetField("area_m2")
        if area < MIN_AREA_M2:
            removed_count += 1
            continue
        kept_count += 1
        total_area_m2 += area

        geom = feature.GetGeometryRef().Clone()
        geom.Transform(transform)
        geojson_geom = json.loads(geom.ExportToJson())

        features.append({
            "type": "Feature",
            "properties": {
                "year": year,
                "water_area_km2": round(area / 1_000_000, 4)
            },
            "geometry": geojson_geom
        })

    total_area_km2 = round(total_area_m2 / 1_000_000, 2)

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    os.makedirs(os.path.dirname(output_geojson), exist_ok=True)
    with open(output_geojson, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, ensure_ascii=False)

    in_ds = None
    print(f"  [年份 {year}] 保留 {kept_count} 个面, 剔除 {removed_count} 个碎斑, 总水面面积: {total_area_km2} km²")
    return total_area_km2


def process_all():
    """主入口: 批处理所有年份"""
    print("=" * 60)
    print("官厅水库 遥感水体提取 全自动批处理")
    print(f"UTM 投影: EPSG:{UTM_EPSG} (Zone 50N)")
    print(f"碎斑剔除阈值: {MIN_AREA_M2} m² (50像元 × 100m²)")
    print("=" * 60)

    # 创建临时目录
    temp_dir = os.path.join(INPUT_DIR, "_temp_processing")
    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Step 0: 生成 ROI
    create_roi_geojson()

    # 收集年度面积数据
    timeseries_data = []

    # 查找所有 tif 文件
    tif_files = sorted([f for f in os.listdir(INPUT_DIR) if f.endswith('.tif')])
    if not tif_files:
        print(f"[ERROR] 在 {INPUT_DIR} 中未找到 .tif 文件!")
        print("请先从 ArcGIS Living Atlas 下载 2017-2025 的土地覆盖 .tif")
        return

    for tif_name in tif_files:
        # 从文件名中提取年份 (兼容多种命名格式)
        year = None
        for y in range(2017, 2026):
            if str(y) in tif_name:
                year = y
                break
        if year is None:
            print(f"  [SKIP] 无法识别年份: {tif_name}")
            continue

        print(f"\n>>> 处理 {year} ({tif_name})")
        input_path = os.path.join(INPUT_DIR, tif_name)

        # 中间文件路径
        clipped_tif = os.path.join(temp_dir, f"clipped_{year}.tif")
        water_tif = os.path.join(temp_dir, f"water_{year}.tif")
        water_shp = os.path.join(temp_dir, f"water_{year}.shp")
        water_utm_shp = os.path.join(temp_dir, f"water_utm_{year}.shp")
        output_geojson = os.path.join(OUTPUT_DIR, f"water_{year}.geojson")

        # Step 1: 裁剪到 ROI
        print(f"  1. 裁剪到 ROI...")
        clip_raster_to_roi(input_path, clipped_tif)

        # Step 2: 水体二值化提取 (NoData优化)
        print(f"  2. 水体提取 (类别值={WATER_CLASS_VALUES}, 非水=NoData)...")
        extract_water_binary(clipped_tif, water_tif)

        # Step 3: 栅格转矢量
        print(f"  3. 栅格转矢量...")
        polygonize_water(water_tif, water_shp)

        # Step 4: 重投影到 UTM 并计算面积
        print(f"  4. 重投影到 UTM Zone 50N 计算面积...")
        reproject_to_utm(water_shp, water_utm_shp)

        # Step 5: 碎斑剔除 + 导出 GeoJSON
        print(f"  5. 碎斑剔除 + 导出 GeoJSON...")
        area_km2 = filter_small_polygons_and_export(water_utm_shp, output_geojson, year)

        timeseries_data.append({
            "date": str(year),
            "water_area_km2": area_km2
        })

    # Step 6: 导出时间序列 JSON
    timeseries_data.sort(key=lambda x: x["date"])
    timeseries_json = {
        "reservoir": "官厅水库",
        "reservoir_en": "Guanting Reservoir",
        "unit": "km2",
        "data": timeseries_data
    }
    with open(TIMESERIES_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(timeseries_json, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 时间序列已导出: {TIMESERIES_OUTPUT}")

    # 计算波动率验证
    if len(timeseries_data) >= 5:
        areas = [d["water_area_km2"] for d in timeseries_data[-5:]]
        a_max, a_min, a_mean = max(areas), min(areas), np.mean(areas)
        delta_a = (a_max - a_min) / a_mean * 100
        print(f"\n[验证] 近5年波动率 ΔA = ({a_max}-{a_min})/{a_mean:.1f} = {delta_a:.1f}%")
        if delta_a >= 15:
            print(f"  ✓ 满足 ≥15% 水文波动约束")
        else:
            print(f"  ✗ 警告: 波动率不足15%, 请检查数据或重新选点")

    print("\n" + "=" * 60)
    print("全部处理完成!")
    print(f"GeoJSON 输出目录: {OUTPUT_DIR}")
    print(f"时间序列: {TIMESERIES_OUTPUT}")
    print(f"ROI: {ROI_OUTPUT}")
    print("=" * 60)


# 执行
if __name__ == "__main__":
    process_all()
else:
    # 在 QGIS Python 控制台中直接运行
    process_all()
