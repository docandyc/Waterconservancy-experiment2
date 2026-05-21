# 官厅水库 水体动态监测数字孪生大屏系统

## 项目概述

本系统是"遥感水体动态监测与数字孪生大屏原型开发"实验的前端集成工程。核心链路为：遥感空间资产离线生产 → 标准资产版本化交付 → 前端解耦型孪生大屏集成。

**研究对象**：官厅水库（中国，北京/河北），华北典型调蓄水库，面积约 50–130 km²，受流域调水和降雨影响，年际面积波动丰富。

**坐标信息**：115.6°E, 40.3°N | UTM Zone 50N (EPSG:32650)

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端框架 | Vue 3 + Vite |
| 地图引擎 | Leaflet (EPSG:4326) |
| 图表引擎 | ECharts 5 |
| 空间处理 | QGIS + PyQGIS + GDAL/OGR |
| 遥感指数 | MNDWI + Otsu 自适应阈值 |
| 数据源 | ArcGIS Living Atlas (年度) / Sentinel-2 L2A (月度) |

## 目录结构

```
water-monitoring-system/
├── public/data/
│   ├── reservoir_roi.geojson        # 水库分析框 ROI (红框)
│   ├── area_timeseries.json         # 年度面积时间序列
│   ├── area_timeseries_monthly.json # 月度面积时间序列
│   └── water_layers/
│       ├── annual/                  # 年度水面 GeoJSON (2017-2025)
│       │   ├── water_2017.geojson
│       │   └── ...
│       └── monthly/                 # 月度水面 GeoJSON (2024_05-2024_10)
│           ├── water_2024_05.geojson
│           └── ...
├── scripts/
│   ├── batch_extract_annual.py      # 年度批处理脚本 (PyQGIS)
│   ├── batch_extract_monthly.py     # 月度批处理脚本 (MNDWI+Otsu)
│   └── water_extraction_pipeline.model3  # QGIS 图形建模器流程
├── src/
│   ├── App.vue                      # 主页面
│   └── components/
│       ├── MapView.vue              # Leaflet 地图组件
│       ├── AreaChart.vue            # ECharts 折线图组件
│       └── StatsPanel.vue           # 监测指标统计面板
└── README.md
```

## 快速启动

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build
```

## 坐标顺序约定

| 场景 | 坐标顺序 |
|------|----------|
| GeoJSON 文件内部 (RFC 7946) | [Longitude, Latitude] |
| Leaflet setView / L.marker | [Latitude, Longitude] |
| L.geoJSON() 自动解析 | 无需手动转换 |

## 数据处理流程

### 常规方案（年尺度）

1. ArcGIS Living Atlas 下载 2017-2025 土地覆盖 .tif
2. ROI 裁剪 → 水体像元过滤 (类别值=1[Water]+4[Flooded Vegetation], 非水=NoData)
3. 栅格转矢量 (Polygonize)
4. 自适应碎斑剔除 (10m: 50像元 = 5000 m²)
5. UTM Zone 50N 重投影计算面积
6. 回投 EPSG:4326 导出标准 GeoJSON

### 进阶方案（月尺度）

1. Copernicus Browser 下载 Sentinel-2 L2A (B03 + B11)
2. B11 重采样 20m → 10m (双线性插值)
3. MNDWI = (B03 - B11) / (B03 + B11)
4. Otsu 自适应阈值标定 (禁止固定阈值)
5. 二值化 → 矢量化 → 碎斑剔除 → UTM面积
6. 导出月度 GeoJSON

### 水文波动验证

$$\Delta A = \frac{A_{max} - A_{min}}{\bar{A}} \geq 15\%$$

### UTM 分带计算

$$Zone = \lfloor(Lng + 180) / 6\rfloor + 1 = \lfloor(115.6 + 180) / 6\rfloor + 1 = 50$$

## 数据资产规范

- `area_timeseries.json` 中 `date` 字段与 `water_layers/` 文件名后缀严格对齐
- GeoJSON 属性字段统一使用 `water_area_km2` (小写+下划线)
- 所有面积在 UTM 投影下计算后转为 km²

## 版权与学术引用

- Esri, Impact Observatory, and Microsoft. (2025). 10m Annual Land Cover. ArcGIS Living Atlas of the World.
- Contains modified Copernicus Sentinel data [2024], processed by [团队名称].
- Pekel, J. F., Cottam, A., Gorelick, N., & Belward, A. S. (2016). High-resolution mapping of global surface water and its long-term changes. *Nature*, 540(7633), 418–422.
