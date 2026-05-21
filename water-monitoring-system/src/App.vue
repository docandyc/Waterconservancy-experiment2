<template>
  <div id="app">
    <header class="app-header">
      <h1>官厅水库 水体动态监测数字孪生大屏</h1>
      <div class="controls">
        <label>时间尺度：</label>
        <select v-model="timeScale" @change="onScaleChange">
          <option value="annual">年尺度</option>
          <option value="monthly">月尺度</option>
        </select>
        <label>选择时段：</label>
        <select v-model="selectedDate" @change="onDateChange">
          <option v-for="d in dateOptions" :key="d" :value="d">{{ d }}</option>
        </select>
      </div>
    </header>
    <div class="main-content">
      <div class="left-panel">
        <StatsPanel
          :timeseries="timeseries"
          :selected-date="selectedDate"
        />
        <div class="chart-wrapper">
          <AreaChart
            :timeseries="timeseries"
            :selected-date="selectedDate"
            @point-click="onChartPointClick"
          />
        </div>
      </div>
      <div class="map-container">
        <MapView
          :water-geojson-url="waterGeojsonUrl"
          :roi-url="roiUrl"
        />
      </div>
    </div>
    <footer class="app-footer">
      <span>数据来源: Esri Living Atlas / Copernicus Sentinel-2</span>
      <span>坐标系: EPSG:4326 (GeoJSON) | 面积投影: UTM Zone 50N (EPSG:32650)</span>
      <span>官厅水库 (115.6°E, 40.3°N) | 水文波动约束 ΔA ≥ 15%</span>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import MapView from './components/MapView.vue'
import AreaChart from './components/AreaChart.vue'
import StatsPanel from './components/StatsPanel.vue'

const timeScale = ref('annual')
const selectedDate = ref('2017')
const timeseries = ref([])
const annualDates = ['2017','2018','2019','2020','2021','2022','2023','2024','2025']
const monthlyDates = ['2024_05','2024_06','2024_07','2024_08','2024_09','2024_10']

const dateOptions = computed(() =>
  timeScale.value === 'annual' ? annualDates : monthlyDates
)

const roiUrl = '/data/reservoir_roi.geojson'

const waterGeojsonUrl = computed(() => {
  const folder = timeScale.value === 'annual' ? 'annual' : 'monthly'
  return `/data/water_layers/${folder}/water_${selectedDate.value}.geojson`
})

async function loadTimeseries() {
  const url = timeScale.value === 'annual'
    ? '/data/area_timeseries.json'
    : '/data/area_timeseries_monthly.json'
  try {
    const res = await fetch(url)
    const json = await res.json()
    timeseries.value = json.data
  } catch {
    timeseries.value = []
  }
}

function onScaleChange() {
  selectedDate.value = dateOptions.value[0]
  loadTimeseries()
}

function onDateChange() {}

function onChartPointClick(date) {
  selectedDate.value = date
}

onMounted(() => {
  loadTimeseries()
})
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app { width: 100%; height: 100%; font-family: 'Microsoft YaHei', sans-serif; }
#app { display: flex; flex-direction: column; background: #0a1929; color: #e0e0e0; }
.app-header {
  padding: 12px 24px;
  background: linear-gradient(135deg, #0d2137, #1a3a5c);
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid #1e4976;
}
.app-header h1 { font-size: 20px; color: #4fc3f7; }
.controls { display: flex; align-items: center; gap: 10px; }
.controls label { font-size: 13px; color: #90caf9; }
.controls select {
  background: #0d2137; color: #e0e0e0; border: 1px solid #1e4976;
  padding: 4px 8px; border-radius: 4px; font-size: 13px;
}
.main-content { flex: 1; display: flex; overflow: hidden; }
.left-panel {
  width: 360px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  overflow-y: auto;
  border-right: 1px solid #1e4976;
}
.chart-wrapper { flex: 1; min-height: 250px; }
.map-container { flex: 1; position: relative; }
.app-footer {
  padding: 8px 24px;
  background: #0d2137;
  border-top: 1px solid #1e4976;
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #607d8b;
}
</style>
