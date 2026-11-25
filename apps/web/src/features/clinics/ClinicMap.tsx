import { useEffect, useRef } from 'react'
import { divIcon, latLngBounds, layerGroup, map as createMap, marker, TileLayer, tileLayer } from 'leaflet'
import type { Coords, DoneCallback, Map as LeafletMap, Marker, TileEvent, TileLayerOptions } from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { Clinic, Coordinates } from '../../api/clinics'
import { Button } from '../../components/ui'

const yandexKey: string | undefined = import.meta.env.VITE_YANDEX_TILES_API_KEY
const yandexTiles = 'https://tiles.api-maps.yandex.ru/v1/tiles/?x={x}&y={y}&z={z}&lang=ru_RU&l=map&projection=web_mercator&apikey='
const osmTiles = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const osmAttribution = '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>'
const tileOptions: TileLayerOptions = { referrerPolicy: 'origin', keepBuffer: 0, maxNativeZoom: 19, updateWhenIdle: true }

let lastYandexTile = 0
class YandexTileLayer extends TileLayer {
  private queue = new Map<HTMLElement, () => void>()
  private timer?: number

  constructor(key: string) {
    super(yandexTiles + encodeURIComponent(key), tileOptions)
    this.on('tileunload', ({ tile }: TileEvent) => this.queue.delete(tile))
    this.on('remove', () => {
      window.clearTimeout(this.timer)
      this.timer = undefined
      this.queue.clear()
    })
  }

  createTile(coords: Coords, done: DoneCallback) {
    const image = document.createElement('img')
    image.alt = ''
    image.referrerPolicy = 'origin'
    image.onload = () => done(undefined, image)
    image.onerror = () => done(new Error('Tile unavailable'), image)
    this.queue.set(image, () => { image.src = this.getTileUrl(coords) })
    this.schedule()
    return image
  }

  private schedule() {
    if (this.timer !== undefined || !this.queue.size) return
    this.timer = window.setTimeout(() => {
      this.timer = undefined
      const next = this.queue.entries().next().value
      if (!next) return
      const [image, load] = next
      this.queue.delete(image)
      lastYandexTile = performance.now()
      load()
      this.schedule()
    }, Math.max(0, lastYandexTile + 40 - performance.now()))
  }
}

export type MapStatus = 'loading' | 'ready' | 'error'

export function ClinicMap({ items, selection, picking, onSelect, onPoint, onStatus }: {
  items: Clinic[]; selection?: { id: string; focusMarker: boolean }; picking: boolean
  onSelect: (id: string) => void; onPoint: (point: Coordinates) => void; onStatus: (status: MapStatus) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const instance = useRef<LeafletMap>(null)
  const layers = useRef<ReturnType<typeof layerGroup>>(null)
  const markers = useRef(new Map<string, Marker>())
  const callbacks = useRef({ picking, onPoint, onSelect, onStatus })

  useEffect(() => { callbacks.current = { picking, onPoint, onSelect, onStatus } }, [picking, onPoint, onSelect, onStatus])
  useEffect(() => {
    if (!container.current) return
    const tileMap = createMap(container.current, {
      scrollWheelZoom: false, maxZoom: 19, minZoom: 9, attributionControl: true, zoomControl: false,
    })
    tileMap.attributionControl.setPrefix(false)
    tileMap.on('click', ({ latlng }) => {
      if (callbacks.current.picking) callbacks.current.onPoint({ lat: latlng.lat, lon: latlng.lng })
    })
    instance.current = tileMap
    layers.current = layerGroup().addTo(tileMap)
    let active = true
    let layer: TileLayer | undefined
    let logo: HTMLAnchorElement | undefined
    let timer: number | undefined

    function addTiles(useYandex: boolean) {
      layer?.remove()
      logo?.remove()
      window.clearTimeout(timer)
      callbacks.current.onStatus('loading')
      const next = useYandex && yandexKey ? new YandexTileLayer(yandexKey)
        : tileLayer(osmTiles, { ...tileOptions, attribution: osmAttribution })
      layer = next
      if (useYandex) {
        logo = document.createElement('a')
        logo.className = 'clinic-map-logo'
        logo.href = 'https://yandex.ru/maps/'
        logo.target = '_blank'
        logo.rel = 'noopener noreferrer'
        const image = document.createElement('img')
        image.src = '/brand/yandex-tiles-logo.png'
        image.alt = 'Яндекс Карты'
        logo.append(image)
        container.current?.append(logo)
      }
      const fallback = () => queueMicrotask(() => {
        if (!active || layer !== next) return
        if (useYandex) addTiles(false)
        else callbacks.current.onStatus('error')
      })
      next.once('tileload', () => {
        if (!active || layer !== next) return
        window.clearTimeout(timer)
        callbacks.current.onStatus('ready')
      })
      next.once('tileerror', fallback)
      timer = window.setTimeout(fallback, 9000)
      next.addTo(tileMap)
    }

    addTiles(!!yandexKey)
    return () => {
      active = false
      window.clearTimeout(timer)
      logo?.remove()
      tileMap.remove()
      instance.current = null
      layers.current = null
    }
  }, [])

  useEffect(() => {
    const tileMap = instance.current
    const group = layers.current
    if (!tileMap || !group) return
    group.clearLayers()
    markers.current.clear()
    items.forEach((clinic, index) => {
      const pin = marker([clinic.lat, clinic.lon], {
        title: clinic.name, alt: clinic.name,
        icon: divIcon({ className: 'clinic-pin', html: String(index + 1), iconSize: [36, 36], iconAnchor: [18, 34] }),
      }).on('click', () => callbacks.current.onSelect(clinic.id)).addTo(group)
      markers.current.set(clinic.id, pin)
      pin.getElement()?.setAttribute('aria-label', clinic.name)
    })
    if (items.length) tileMap.fitBounds(latLngBounds(items.map(({ lat, lon }) => [lat, lon])), { padding: [42, 42], maxZoom: 16 })
    else tileMap.setView([55.445, 65.34], 13)
  }, [items])

  useEffect(() => {
    for (const [id, pin] of markers.current) pin.getElement()?.setAttribute('aria-pressed', String(id === selection?.id))
    const selected = selection && markers.current.get(selection.id)
    if (selected) {
      instance.current?.panTo(selected.getLatLng(), { animate: false })
      if (selection.focusMarker) selected.getElement()?.focus({ preventScroll: true })
    }
  }, [selection, items])

  return <div className="clinic-map">
    <div className="clinic-map-canvas" ref={container} role="region" aria-label="Карта медучреждений" />
    <div className="clinic-map-controls">
      <Button variant="secondary" aria-label="Приблизить карту" onClick={() => instance.current?.zoomIn()}>+</Button>
      <Button variant="secondary" aria-label="Отдалить карту" onClick={() => instance.current?.zoomOut()}>−</Button>
      {picking && <Button variant="secondary" onClick={() => {
        const center = instance.current?.getCenter()
        if (center) onPoint({ lat: center.lat, lon: center.lng })
      }}>Искать от центра карты</Button>}
    </div>
  </div>
}
