<template>
  <div ref="mapEl" class="map"></div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const props = defineProps({
  waterGeojsonUrl: String,
  roiUrl: String
})

const mapEl = ref(null)
let map = null
let waterLayer = null
let roiLayer = null

onMounted(() => {
  map = L.map(mapEl.value, {
    center: [40.28, 115.65],
    zoom: 11,
    zoomControl: true
  })

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map)

  loadROI()
  loadWater(props.waterGeojsonUrl)
})

watch(() => props.waterGeojsonUrl, (url) => {
  loadWater(url)
})

async function loadROI() {
  try {
    const res = await fetch(props.roiUrl)
    const geojson = await res.json()
    roiLayer = L.geoJSON(geojson, {
      style: {
        color: '#ff4444',
        weight: 2,
        fillOpacity: 0,
        dashArray: '6 4'
      }
    }).addTo(map)
  } catch (e) {
    console.warn('ROI加载失败:', e)
  }
}

async function loadWater(url) {
  if (waterLayer) {
    map.removeLayer(waterLayer)
    waterLayer = null
  }
  try {
    const res = await fetch(url)
    const geojson = await res.json()
    waterLayer = L.geoJSON(geojson, {
      style: {
        color: '#1e88e5',
        weight: 1,
        fillColor: '#42a5f5',
        fillOpacity: 0.6
      },
      onEachFeature(feature, layer) {
        const p = feature.properties
        const popup = `
          <div style="font-size:13px;line-height:1.6">
            <b>水体面片属性</b><br/>
            时段: ${p.year || p.month || p.date || '--'}<br/>
            面积: ${p.water_area_km2 || '--'} km²
          </div>
        `
        layer.bindPopup(popup)
        layer.on('mouseover', () => {
          layer.setStyle({ fillOpacity: 0.85, weight: 2 })
        })
        layer.on('mouseout', () => {
          layer.setStyle({ fillOpacity: 0.6, weight: 1 })
        })
      }
    }).addTo(map)
  } catch (e) {
    console.warn('水体图层加载失败:', e)
  }
}
</script>

<style scoped>
.map { width: 100%; height: 100%; }
</style>
