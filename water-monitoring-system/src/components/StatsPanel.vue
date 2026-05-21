<template>
  <div class="stats-panel">
    <h3>水库监测指标</h3>
    <div class="stats-grid">
      <div class="stat-card">
        <span class="stat-label">当前水面面积</span>
        <span class="stat-value">{{ currentArea }} <em>km²</em></span>
      </div>
      <div class="stat-card">
        <span class="stat-label">历史最大面积</span>
        <span class="stat-value max">{{ maxArea }} <em>km²</em></span>
      </div>
      <div class="stat-card">
        <span class="stat-label">历史最小面积</span>
        <span class="stat-value min">{{ minArea }} <em>km²</em></span>
      </div>
      <div class="stat-card">
        <span class="stat-label">极差相对均值比 ΔA</span>
        <span class="stat-value" :class="{ pass: deltaA >= 15 }">{{ deltaA }}%</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">均值面积</span>
        <span class="stat-value">{{ meanArea }} <em>km²</em></span>
      </div>
      <div class="stat-card">
        <span class="stat-label">数据年份跨度</span>
        <span class="stat-value">{{ yearSpan }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  timeseries: Array,
  selectedDate: String
})

const currentArea = computed(() => {
  const item = props.timeseries.find(d => d.date === props.selectedDate)
  return item ? item.water_area_km2 : '--'
})

const maxArea = computed(() => {
  if (!props.timeseries.length) return '--'
  return Math.max(...props.timeseries.map(d => d.water_area_km2))
})

const minArea = computed(() => {
  if (!props.timeseries.length) return '--'
  return Math.min(...props.timeseries.map(d => d.water_area_km2))
})

const meanArea = computed(() => {
  if (!props.timeseries.length) return '--'
  const sum = props.timeseries.reduce((s, d) => s + d.water_area_km2, 0)
  return (sum / props.timeseries.length).toFixed(1)
})

const deltaA = computed(() => {
  if (!props.timeseries.length) return '--'
  const areas = props.timeseries.map(d => d.water_area_km2)
  const aMax = Math.max(...areas)
  const aMin = Math.min(...areas)
  const aMean = areas.reduce((s, v) => s + v, 0) / areas.length
  return ((aMax - aMin) / aMean * 100).toFixed(1)
})

const yearSpan = computed(() => {
  if (!props.timeseries.length) return '--'
  const dates = props.timeseries.map(d => d.date)
  return `${dates[0]} ~ ${dates[dates.length - 1]}`
})
</script>

<style scoped>
.stats-panel {
  padding: 16px;
  background: rgba(13, 33, 55, 0.9);
  border: 1px solid #1e4976;
  border-radius: 8px;
}
.stats-panel h3 {
  font-size: 14px;
  color: #4fc3f7;
  margin-bottom: 12px;
  border-bottom: 1px solid #1e4976;
  padding-bottom: 8px;
}
.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.stat-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  background: rgba(30, 73, 118, 0.3);
  border-radius: 4px;
}
.stat-label {
  font-size: 11px;
  color: #90caf9;
}
.stat-value {
  font-size: 18px;
  font-weight: bold;
  color: #e0e0e0;
}
.stat-value em {
  font-size: 12px;
  font-style: normal;
  color: #90caf9;
}
.stat-value.max { color: #ef5350; }
.stat-value.min { color: #66bb6a; }
.stat-value.pass { color: #66bb6a; }
</style>
