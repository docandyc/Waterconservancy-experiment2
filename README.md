# Waterconservancy Experiment 2

官厅水库水体动态监测实验项目仓库。这个仓库包含实验说明文档、成果文档、前端数字孪生展示系统，以及用于生成水体边界和时间序列资产的脚本。

## 项目内容

- `water-monitoring-system/`：Vue 3 + Vite 构建的水体动态监测数字孪生大屏
- `实验2-学号-姓名.md` / `.docx`：实验报告
- `遥感水体动态监测实验任务书.md` / `.docx`：实验任务书
- `raw_sentinel2/`：Sentinel-2 原始影像目录
- `raw_tif/`：年度土地覆盖原始栅格目录

## 仓库结构

```text
EXP3/
├── README.md
├── water-monitoring-system/
│   ├── public/data/               # 已处理的水体 GeoJSON 与面积时间序列
│   ├── scripts/                   # 年度/月度提取与校验脚本
│   ├── src/                       # 前端页面与组件
│   └── README.md                  # 前端子项目说明
├── 实验2-学号-姓名.md
├── 实验2-学号-姓名.docx
├── 遥感水体动态监测实验任务书.md
└── 遥感水体动态监测实验任务书.docx
```

## 前端系统运行

进入前端目录后执行：

```bash
cd water-monitoring-system
npm install
npm run dev
```

生产构建：

```bash
cd water-monitoring-system
npm run build
```

## 数据说明

- 仓库中保留了前端演示所需的处理结果，包括年度和月度水体边界 GeoJSON、面积时间序列、ROI 边界等。
- `raw_sentinel2/` 和 `raw_tif/` 为原始遥感数据目录，体积较大，默认不随 GitHub 仓库上传。
- 如果需要完整复现实验流程，可结合 `water-monitoring-system/scripts/` 下的脚本，在本地补齐原始数据后重新生成结果资产。

## 技术路线

1. 获取年度土地覆盖数据与 Sentinel-2 多光谱影像。
2. 基于 ROI 对研究区进行裁剪与水体提取。
3. 使用 MNDWI、Otsu 阈值分割、碎斑剔除和面积统计生成标准化结果。
4. 将结果组织为前端可直接消费的 GeoJSON 和时间序列 JSON。
5. 在 Vue + Leaflet + ECharts 前端中完成地图、图表和指标联动展示。

## 说明

- 仓库根目录 `README.md` 用于 GitHub 首页快速说明。
- 更具体的前端实现、数据资产规范和处理流程见 [water-monitoring-system/README.md](water-monitoring-system/README.md)。
