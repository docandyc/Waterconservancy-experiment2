# 技术白皮书：远期孪生演进设计

## 1. 流式可复现性（Processing Modeler）

### 1.1 当前实现

本项目已将 QGIS 离线处理的全部步骤封装为两种可复现格式：

- **QGIS 图形建模器流程** (`scripts/water_extraction_pipeline.model3`)：可在 QGIS Processing Modeler 中直接导入并可视化运行，支持参数化输入。
- **PyQGIS 批处理脚本** (`scripts/batch_extract_annual.py`, `scripts/batch_extract_monthly.py`)：在 QGIS Python 控制台或独立 Python 环境中执行，实现无人工干预的全自动遥感流水线。

### 1.2 自动化流水线步骤

```
输入 .tif → ROI裁剪 → 水体像元提取(NoData) → 栅格转矢量
         → UTM重投影 → 面积计算 → 碎斑剔除(5000m²)
         → 回投EPSG:4326 → 导出标准GeoJSON + 时序JSON
```

### 1.3 可扩展性设计

- 支持通过修改 `ROI_BOUNDS` 参数适配任意水库
- UTM 分带号自动计算，无需手动指定
- 年度/月度双模式独立运行，互不干扰

---

## 2. 异构空间数据库与动态 API 设计

### 2.1 架构概述

将当前静态 GeoJSON 文件重构为基于 PostgreSQL + PostGIS 的动态空间数据库存取方案，通过 FastAPI 提供 RESTful 接口，支持前端动态参数查询。

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────────┐
│   Vue 前端   │────▶│   FastAPI    │────▶│ PostgreSQL + PostGIS │
│ Leaflet/ECharts│◀────│   后端路由    │◀────│    空间数据库         │
└─────────────┘     └──────────────┘     └─────────────────────┘
```

### 2.2 数据库表结构设计

```sql
-- 水库元数据表
CREATE TABLE reservoirs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    name_en VARCHAR(100),
    center_point GEOMETRY(Point, 4326),
    roi_boundary GEOMETRY(Polygon, 4326),
    utm_epsg INTEGER NOT NULL
);

-- 水体多时相空间要素表
CREATE TABLE water_features (
    id SERIAL PRIMARY KEY,
    reservoir_id INTEGER REFERENCES reservoirs(id),
    observation_date DATE NOT NULL,
    time_scale VARCHAR(10) CHECK (time_scale IN ('annual', 'monthly')),
    water_area_km2 DOUBLE PRECISION,
    geom GEOMETRY(MultiPolygon, 4326),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 空间索引
CREATE INDEX idx_water_features_geom ON water_features USING GIST(geom);
CREATE INDEX idx_water_features_date ON water_features(reservoir_id, observation_date);

-- 面积时间序列视图
CREATE VIEW area_timeseries AS
SELECT
    r.name AS reservoir,
    wf.observation_date AS date,
    wf.time_scale,
    wf.water_area_km2
FROM water_features wf
JOIN reservoirs r ON wf.reservoir_id = r.id
ORDER BY wf.observation_date;
```

### 2.3 FastAPI 路由设计

```python
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import geopandas as gpd
from sqlalchemy import create_engine

app = FastAPI(title="水体动态监测 API", version="1.0")

@app.get("/api/water/spatial")
async def get_water_spatial(
    reservoir: str = Query(..., description="水库名称"),
    year: int = Query(None, description="年份"),
    month: str = Query(None, description="月份, 格式: YYYY_MM"),
    format: str = Query("geojson", enum=["geojson", "wkt"])
):
    """
    动态空间切片查询
    示例: GET /api/water/spatial?reservoir=Guanting&year=2023
    """
    sql = """
        SELECT ST_AsGeoJSON(geom) as geometry, water_area_km2, observation_date
        FROM water_features wf
        JOIN reservoirs r ON wf.reservoir_id = r.id
        WHERE r.name_en ILIKE :reservoir
    """
    if year:
        sql += " AND EXTRACT(YEAR FROM observation_date) = :year"
    if month:
        sql += " AND TO_CHAR(observation_date, 'YYYY_MM') = :month"

    # 执行空间SQL并返回标准GeoJSON
    # ...
    return JSONResponse(content=geojson_result)


@app.get("/api/water/timeseries")
async def get_timeseries(
    reservoir: str = Query(...),
    scale: str = Query("annual", enum=["annual", "monthly"]),
    start_year: int = Query(2017),
    end_year: int = Query(2025)
):
    """
    时间序列查询
    示例: GET /api/water/timeseries?reservoir=Guanting&scale=annual
    """
    sql = """
        SELECT observation_date as date, water_area_km2
        FROM water_features wf
        JOIN reservoirs r ON wf.reservoir_id = r.id
        WHERE r.name_en ILIKE :reservoir
          AND wf.time_scale = :scale
          AND EXTRACT(YEAR FROM observation_date) BETWEEN :start AND :end
        ORDER BY observation_date
    """
    # ...
    return JSONResponse(content={"reservoir": reservoir, "data": results})


@app.get("/api/water/roi")
async def get_roi(reservoir: str = Query(...)):
    """获取水库 ROI 边界"""
    sql = """
        SELECT ST_AsGeoJSON(roi_boundary) as geometry, name, name_en
        FROM reservoirs WHERE name_en ILIKE :reservoir
    """
    # ...
    return JSONResponse(content=geojson_result)


@app.get("/api/water/stats")
async def get_stats(reservoir: str = Query(...)):
    """
    获取水库统计指标 (最大/最小/均值/波动率)
    """
    sql = """
        SELECT
            MAX(water_area_km2) as max_area,
            MIN(water_area_km2) as min_area,
            AVG(water_area_km2) as mean_area,
            (MAX(water_area_km2) - MIN(water_area_km2)) / AVG(water_area_km2) * 100 as delta_a
        FROM water_features wf
        JOIN reservoirs r ON wf.reservoir_id = r.id
        WHERE r.name_en ILIKE :reservoir
    """
    # ...
    return JSONResponse(content=stats)
```

### 2.4 前端对接改造

当后端就绪后，前端仅需将 `fetch('/data/...')` 替换为 API 调用：

```javascript
// 替换前 (静态文件)
const res = await fetch('/data/water_layers/annual/water_2023.geojson')

// 替换后 (动态API)
const res = await fetch('/api/water/spatial?reservoir=Guanting&year=2023')
```

---

## 3. 从表象面积到机理库容的数字孪生跃迁

### 3.1 问题定义

当前系统仅实现了二维水面面积的时序监测。然而，水库管理的核心指标是**库容**（Volume），而非面积。面积只是水位在二维平面上的投影，真正的蓄水量需要结合水库底部的三维地形才能推算。

### 3.2 DEM 数据引入

引入 ALOS PALSAR DEM（12.5m 分辨率）作为水库盆地的三维基底：

- 数据源：ASF (Alaska Satellite Facility) 免费下载
- 分辨率：12.5 m（优于 SRTM 30m）
- 覆盖范围：全球 ±60° 纬度

### 3.3 三维积分物理模型

**水位-面积-库容三元机理曲线 (Stage-Area-Volume Curve)**

原理：将 DEM 视为水库的"碗"，水面 GeoJSON 的边界为"碗中水的边缘"。通过逐层高程切片积分，反演出任意水位下的库容。

```
          水面 (GeoJSON边界)
    ═══════════════════════════  ← 水位高程 H
    ╲                        ╱
     ╲      水体体积V       ╱
      ╲                    ╱
       ╲                  ╱
        ╲________________╱      ← DEM 基底
```

**数学模型**：

对于水位高程 $H$，库容 $V(H)$ 由以下积分给出：

$$V(H) = \int_{h_{min}}^{H} A(h) \, dh$$

其中 $A(h)$ 为高程 $h$ 处的水面面积（DEM 上等高线围合的面积）。

**离散化实现**：

$$V(H) \approx \sum_{i=1}^{N} \frac{A(h_i) + A(h_{i-1})}{2} \cdot \Delta h$$

### 3.4 实现路径

```python
import numpy as np
from osgeo import gdal

def compute_stage_area_volume(dem_path, water_boundary_geojson, h_step=0.5):
    """
    计算水位-面积-库容曲线

    参数:
        dem_path: DEM 栅格路径
        water_boundary_geojson: 水面边界 GeoJSON (用于确定分析范围)
        h_step: 高程切片步长 (米)

    返回:
        [(水位H, 面积A, 库容V), ...]
    """
    # 1. 用水面边界裁剪 DEM
    dem_ds = gdal.Open(dem_path)
    dem_array = dem_ds.GetRasterBand(1).ReadAsArray()
    gt = dem_ds.GetGeoTransform()
    pixel_area = abs(gt[1] * gt[5])  # 单像元面积 (m²)

    # 2. 确定高程范围
    h_min = np.nanmin(dem_array)  # 库底最低高程
    h_max = np.nanmax(dem_array)  # 库区最高高程 (坝顶)

    # 3. 逐层切片积分
    stages = np.arange(h_min, h_max, h_step)
    curve = []
    cumulative_volume = 0.0

    for i, h in enumerate(stages):
        # 当前水位下被淹没的像元数
        submerged = dem_array <= h
        area_m2 = np.sum(submerged) * pixel_area
        area_km2 = area_m2 / 1_000_000

        # 梯形积分计算增量体积
        if i > 0:
            prev_area = curve[-1][1] * 1_000_000  # 上一层面积 (m²)
            delta_v = (prev_area + area_m2) / 2 * h_step
            cumulative_volume += delta_v

        volume_million_m3 = cumulative_volume / 1_000_000  # 百万立方米
        curve.append((float(h), area_km2, volume_million_m3))

    return curve
```

### 3.5 应用场景

1. **实时库容反演**：已知当期水面面积 → 查表反推水位 H → 得出库容 V
2. **防洪预警**：设定汛限水位，当面积超过对应阈值时触发告警
3. **调度优化**：结合入库流量预报，模拟水位变化与库容消落过程

### 3.6 前端可视化扩展

未来可在大屏中增加：
- 三维地形渲染（基于 Three.js + DEM）
- 水位-面积-库容联动曲线图
- 库容百分比仪表盘
- 蓄水/泄水动态模拟动画
