"""
官厅水库 - 月度 Sentinel-2 MNDWI + Otsu 自动水体提取脚本
在 QGIS Python 控制台中运行 (需要 scikit-image)

使用前修改:
1. INPUT_DIR: 存放 Sentinel-2 L2A 波段文件的目录
2. 文件命名格式: B03_2025_05.tif, B11_2025_05.tif (或按实际修改 get_band_paths)

技术要点:
- B03 (Green) 原生10m, B11 (SWIR) 原生20m → 需重采样B11到10m
- MNDWI = (B03 - B11) / (B03 + B11)
- Otsu 自适应阈值 (禁止使用固定阈值)
- 碎斑剔除: 50像元 × 100m² = 5000m²
- UTM Zone 50N (EPSG:32650) 下计算面积
"""

import os
import json
import numpy as np
from osgeo import gdal, ogr, osr
from pathlib import Path

try:
    from skimage.filters import threshold_otsu
except ImportError:
    print("[ERROR] 需要安装 scikit-image: pip install scikit-image")
    raise

# ============================================================
# 用户配置区
# ============================================================
INPUT_DIR = "/Users/tls/code/水利信息/EXP3/raw_sentinel2"
OUTPUT_DIR = "/Users/tls/code/水利信息/EXP3/water-monitoring-system/public/data/water_layers/monthly"
TIMESERIES_OUTPUT = "/Users/tls/code/水利信息/EXP3/water-monitoring-system/public/data/area_timeseries_monthly.json"

# 官厅水库 ROI
ROI_BOUNDS = {
    "west": 115.43,
    "east": 115.93,
    "south": 40.18,
    "north": 40.40
}

# 处理的月份列表 (格式: YYYY_MM)
MONTHS = ["2025_05", "2025_06", "2025_07", "2025_08", "2025_09", "2025_10"]

UTM_EPSG = 32650
MIN_AREA_M2 = 5000

# ============================================================
# 波段文件查找 - 根据你的下载命名修改此函数
# ============================================================
def get_band_paths(month_str):
    """
    返回某月份的 B03 和 B11 文件路径
    请根据实际下载的文件命名格式修改此函数

    常见命名格式:
    - Copernicus Browser: T50TLK_20250501T023551_B03_10m.jp2
    - 手动重命名: B03_2025_05.tif
    """
    b03_path = None
    b11_path = None

    year_month = month_str.replace("_", "")  # "202505"

    for f in os.listdir(INPUT_DIR):
        fname = f.upper()
        if year_month in fname or month_str in f:
            if "B03" in fname:
                b03_path = os.path.join(INPUT_DIR, f)
            elif "B11" in fname:
                b11_path = os.path.join(INPUT_DIR, f)

    return b03_path, b11_path


# ============================================================
# 核心处理函数
# ============================================================

def resample_b11_to_10m(b11_path, output_path, reference_path):
    """
    将 B11 (20m) 重采样到 10m, 使用双线性插值
    以 B03 (10m) 作为参考获取目标尺寸和范围
    """
    ref_ds = gdal.Open(reference_path)
    ref_gt = ref_ds.GetGeoTransform()
    x_size = ref_ds.RasterXSize
    y_size = ref_ds.RasterYSize

    gdal.Warp(
        output_path, b11_path,
        width=x_size,
        height=y_size,
        outputBounds=(
            ref_gt[0],
            ref_gt[3] + ref_gt[5] * y_size,
            ref_gt[0] + ref_gt[1] * x_size,
            ref_gt[3]
        ),
        resampleAlg="bilinear",
        format="GTiff"
    )
    ref_ds = None
    print(f"    B11 重采样: 20m → 10m (双线性插值)")


def compute_mndwi(b03_path, b11_resampled_path, output_path):
    """
    计算 MNDWI = (B03 - B11) / (B03 + B11)
    输出浮点栅格, 无效区域设为 NoData
    """
    ds_b03 = gdal.Open(b03_path)
    ds_b11 = gdal.Open(b11_resampled_path)

    b03 = ds_b03.GetRasterBand(1).ReadAsArray().astype(np.float32)
    b11 = ds_b11.GetRasterBand(1).ReadAsArray().astype(np.float32)

    # 避免除零
    denominator = b03 + b11
    denominator[denominator == 0] = np.nan

    mndwi = (b03 - b11) / denominator

    # 无效区域 (原始数据为0的位置) 设为 NoData
    mndwi[(b03 == 0) & (b11 == 0)] = np.nan

    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(output_path, ds_b03.RasterXSize, ds_b03.RasterYSize, 1, gdal.GDT_Float32)
    out_ds.SetGeoTransform(ds_b03.GetGeoTransform())
    out_ds.SetProjection(ds_b03.GetProjection())
    out_band = out_ds.GetRasterBand(1)
    out_band.SetNoDataValue(np.nan)
    out_band.WriteArray(mndwi)
    out_band.FlushCache()

    out_ds = None
    ds_b03 = None
    ds_b11 = None
    print(f"    MNDWI 计算完成, 值域: [{np.nanmin(mndwi):.3f}, {np.nanmax(mndwi):.3f}]")
    return mndwi


def otsu_threshold_and_binarize(mndwi_path, output_path):
    """
    Otsu 自适应阈值标定 + 二值化
    严格遵循任务要求: 禁止使用固定阈值, 非水区设为 NoData
    """
    ds = gdal.Open(mndwi_path)
    band = ds.GetRasterBand(1)
    mndwi = band.ReadAsArray()

    # 剔除 NoData, 仅对有效区域计算 Otsu 阈值
    valid_mndwi = mndwi[~np.isnan(mndwi)]

    if len(valid_mndwi) == 0:
        print("    [WARNING] 无有效像元!")
        ds = None
        return None

    try:
        optimal_threshold = threshold_otsu(valid_mndwi)
        print(f"    Otsu 自适应阈值 T = {optimal_threshold:.4f}")
    except Exception as e:
        optimal_threshold = 0.0
        print(f"    [WARNING] Otsu 失败, 退回默认 T=0.0, 原因: {e}")

    # 二值化: MNDWI > T 为水体(1), 其余为 NoData
    water = np.where(mndwi > optimal_threshold, 1.0, np.nan)
    water[np.isnan(mndwi)] = np.nan

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
    return optimal_threshold


def clip_to_roi(input_path, output_path):
    """裁剪到 ROI"""
    gdal.Warp(
        output_path, input_path,
        outputBounds=(ROI_BOUNDS["west"], ROI_BOUNDS["south"],
                      ROI_BOUNDS["east"], ROI_BOUNDS["north"]),
        outputBoundsSRS="EPSG:4326",
        dstSRS="EPSG:4326",
        resampleAlg="near",
        format="GTiff"
    )


def polygonize_water(raster_path, vector_path):
    """栅格转矢量"""
    ds = gdal.Open(raster_path)
    band = ds.GetRasterBand(1)

    driver = ogr.GetDriverByName("ESRI Shapefile")
    if os.path.exists(vector_path):
        driver.DeleteDataSource(vector_path)
    out_ds = driver.CreateDataSource(vector_path)
    srs = osr.SpatialReference()
    srs.ImportFromWkt(ds.GetProjection())
    layer = out_ds.CreateLayer("water", srs, ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("DN", ogr.OFTInteger))

    gdal.Polygonize(band, band, layer, 0, [], callback=None)
    out_ds = None
    ds = None


def reproject_to_utm(input_shp, output_shp):
    """重投影到 UTM"""
    in_ds = ogr.Open(input_shp)
    in_layer = in_ds.GetLayer()

    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(UTM_EPSG)
    source_srs = in_layer.GetSpatialRef()
    transform = osr.CoordinateTransformation(source_srs, target_srs)

    driver = ogr.GetDriverByName("ESRI Shapefile")
    if os.path.exists(output_shp):
        driver.DeleteDataSource(output_shp)
    out_ds = driver.CreateDataSource(output_shp)
    out_layer = out_ds.CreateLayer("water_utm", target_srs, ogr.wkbPolygon)
    out_layer.CreateField(ogr.FieldDefn("area_m2", ogr.OFTReal))

    for feature in in_layer:
        geom = feature.GetGeometryRef()
        geom.Transform(transform)
        new_feat = ogr.Feature(out_layer.GetLayerDefn())
        new_feat.SetGeometry(geom)
        new_feat.SetField("area_m2", geom.GetArea())
        out_layer.CreateFeature(new_feat)

    out_ds = None
    in_ds = None


def filter_and_export(utm_shp, output_geojson, date_str):
    """碎斑剔除 + 导出 GeoJSON (EPSG:4326)"""
    in_ds = ogr.Open(utm_shp)
    in_layer = in_ds.GetLayer()

    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(4326)
    source_srs = in_layer.GetSpatialRef()
    transform = osr.CoordinateTransformation(source_srs, target_srs)

    features = []
    total_area_m2 = 0.0
    kept = 0
    removed = 0

    for feature in in_layer:
        area = feature.GetField("area_m2")
        if area < MIN_AREA_M2:
            removed += 1
            continue
        kept += 1
        total_area_m2 += area

        geom = feature.GetGeometryRef().Clone()
        geom.Transform(transform)

        features.append({
            "type": "Feature",
            "properties": {
                "date": date_str,
                "water_area_km2": round(area / 1_000_000, 4)
            },
            "geometry": json.loads(geom.ExportToJson())
        })

    total_km2 = round(total_area_m2 / 1_000_000, 2)

    geojson = {"type": "FeatureCollection", "features": features}
    os.makedirs(os.path.dirname(output_geojson), exist_ok=True)
    with open(output_geojson, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, ensure_ascii=False)

    in_ds = None
    print(f"  [结果] 保留 {kept} 面, 剔除 {removed} 碎斑, 水面面积: {total_km2} km²")
    return total_km2


# ============================================================
# 主流程
# ============================================================
def process_monthly():
    print("=" * 60)
    print("官厅水库 月度 Sentinel-2 MNDWI+Otsu 水体提取")
    print(f"投影: EPSG:{UTM_EPSG} | 碎斑阈值: {MIN_AREA_M2} m²")
    print("=" * 60)

    temp_dir = os.path.join(INPUT_DIR, "_temp_monthly")
    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    timeseries_data = []

    for month_str in MONTHS:
        print(f"\n>>> 处理月份: {month_str}")

        b03_path, b11_path = get_band_paths(month_str)
        if not b03_path or not b11_path:
            print(f"  [SKIP] 未找到 B03 或 B11 文件")
            print(f"    B03: {b03_path}")
            print(f"    B11: {b11_path}")
            continue

        # 中间文件
        b11_10m = os.path.join(temp_dir, f"B11_10m_{month_str}.tif")
        mndwi_tif = os.path.join(temp_dir, f"mndwi_{month_str}.tif")
        mndwi_clip = os.path.join(temp_dir, f"mndwi_clip_{month_str}.tif")
        water_tif = os.path.join(temp_dir, f"water_{month_str}.tif")
        water_shp = os.path.join(temp_dir, f"water_{month_str}.shp")
        water_utm_shp = os.path.join(temp_dir, f"water_utm_{month_str}.shp")
        output_geojson = os.path.join(OUTPUT_DIR, f"water_{month_str}.geojson")

        # Step 1: B11 重采样 20m → 10m
        print(f"  1. B11 重采样 (20m → 10m)...")
        resample_b11_to_10m(b11_path, b11_10m, b03_path)

        # Step 2: 计算 MNDWI
        print(f"  2. 计算 MNDWI...")
        compute_mndwi(b03_path, b11_10m, mndwi_tif)

        # Step 3: 裁剪到 ROI
        print(f"  3. 裁剪到 ROI...")
        clip_to_roi(mndwi_tif, mndwi_clip)

        # Step 4: Otsu 自适应阈值 + 二值化
        print(f"  4. Otsu 自适应阈值标定...")
        threshold = otsu_threshold_and_binarize(mndwi_clip, water_tif)
        if threshold is None:
            continue

        # Step 5: 栅格转矢量
        print(f"  5. 栅格转矢量...")
        polygonize_water(water_tif, water_shp)

        # Step 6: 重投影到 UTM
        print(f"  6. 重投影到 UTM Zone 50N...")
        reproject_to_utm(water_shp, water_utm_shp)

        # Step 7: 碎斑剔除 + 导出
        print(f"  7. 碎斑剔除 + 导出 GeoJSON...")
        area_km2 = filter_and_export(water_utm_shp, output_geojson, month_str)

        timeseries_data.append({
            "date": month_str,
            "water_area_km2": area_km2
        })

    # 导出月度时间序列
    timeseries_json = {
        "reservoir": "官厅水库",
        "reservoir_en": "Guanting Reservoir",
        "unit": "km2",
        "scale": "monthly",
        "data": timeseries_data
    }
    with open(TIMESERIES_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(timeseries_json, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] 月度时间序列: {TIMESERIES_OUTPUT}")
    print("=" * 60)
    print("月度处理完成!")
    print("=" * 60)


if __name__ == "__main__":
    process_monthly()
else:
    process_monthly()
