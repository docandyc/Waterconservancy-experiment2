<template>
  <div ref="chartEl" class="chart"></div>
</template>

<script setup>
import { ref, onMounted, watch, onUnmounted } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  timeseries: Array,
  selectedDate: String
})

const emit = defineEmits(['point-click'])

const chartEl = ref(null)
let chart = null

onMounted(() => {
  chart = echarts.init(chartEl.value)
  chart.on('click', (params) => {
    if (params.componentType === 'series') {
      emit('point-click', props.timeseries[params.dataIndex].date)
    }
  })
  renderChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
})

watch(() => props.timeseries, renderChart, { deep: true })
watch(() => props.selectedDate, renderChart)

function handleResize() {
  chart?.resize()
}

function renderChart() {
  if (!chart || !props.timeseries.length) return

  const dates = props.timeseries.map(d => d.date)
  const areas = props.timeseries.map(d => d.water_area_km2)
  const selectedIdx = dates.indexOf(props.selectedDate)

  chart.setOption({
    backgroundColor: 'transparent',
    title: {
      text: '水面面积历史变化',
      textStyle: { color: '#90caf9', fontSize: 14 },
      left: 'center'
    },
    tooltip: {
      trigger: 'axis',
      formatter: '{b}<br/>水面面积: {c} km²'
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { color: '#90caf9', fontSize: 11 },
      axisLine: { lineStyle: { color: '#1e4976' } }
    },
    yAxis: {
      type: 'value',
      name: '面积 (km²)',
      nameTextStyle: { color: '#90caf9' },
      axisLabel: { color: '#90caf9' },
      splitLine: { lineStyle: { color: '#1e4976', type: 'dashed' } }
    },
    series: [{
      type: 'line',
      data: areas,
      smooth: true,
      symbol: 'circle',
      symbolSize: (val, params) => params.dataIndex === selectedIdx ? 12 : 6,
      itemStyle: { color: '#42a5f5' },
      lineStyle: { color: '#42a5f5', width: 2 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(66,165,245,0.3)' },
          { offset: 1, color: 'rgba(66,165,245,0.02)' }
        ])
      },
      markPoint: selectedIdx >= 0 ? {
        data: [{ coord: [selectedIdx, areas[selectedIdx]], symbol: 'pin', symbolSize: 30, itemStyle: { color: '#ff7043' } }]
      } : {}
    }]
  })
}
</script>

<style scoped>
.chart { width: 100%; height: 100%; min-height: 300px; }
</style>
