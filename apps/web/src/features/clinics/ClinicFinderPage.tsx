import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import type { AddressCandidate, Clinic, ClinicSearch, ClinicSearchResult, ClinicsClient, Coordinates, PatientGroup } from '../../api/clinics'
import { Button, Card } from '../../components/ui'
import { ClinicMap } from './ClinicMap'
import type { MapStatus } from './ClinicMap'
import { ClinicResult } from './ClinicResult'
import { isChildSpecialty, specialties } from './specialties'
import './clinics.css'

const payments = [['oms', 'ОМС'], ['paid', 'Платно']] as const
const pilotMessage = 'Каталог сейчас покрывает только Курган.'
const locationErrors: Record<number, string> = {
  1: 'Доступ к местоположению запрещён. Введите адрес вручную.',
  2: 'Не удалось определить местоположение. Введите адрес вручную.',
  3: 'Истекло время ожидания местоположения. Введите адрес вручную или повторите попытку.',
}
const noItems: Clinic[] = []
const radii = [5, 10, 20, 30]
const specialtyOptions = Object.entries(specialties).sort(([, left], [, right]) => left.localeCompare(right, 'ru'))
const buildingAddress = (value: string) => value.replace(/(?:,\s*|\s+)(?:кв(?:артира)?\.?|подъезд|этаж)\s*№?\s*\d.*$/iu, '').trim()

type SearchState = { query: ClinicSearch; attempt: number; result: ClinicSearchResult }
  | { query: ClinicSearch; attempt: number; error: string; outside: boolean }
type SearchLocation = { point: Coordinates; source: 'address' | 'geolocation' | 'map' }

export function ClinicFinderPage({ client, initialSpecialty, initialPatientGroup, onBack }: {
  client: ClinicsClient; initialSpecialty: string; initialPatientGroup?: PatientGroup; onBack: () => void
}) {
  const [address, setAddress] = useState('')
  const [editingAddress, setEditingAddress] = useState(false)
  const [candidates, setCandidates] = useState<AddressCandidate[]>([])
  const [location, setLocation] = useState<SearchLocation | null>(null)
  const [locating, setLocating] = useState('')
  const [locationError, setLocationError] = useState('')
  const [specialty, setSpecialty] = useState(() =>
    initialPatientGroup === 'adult' && isChildSpecialty(initialSpecialty) ? '' : initialSpecialty)
  const [patientGroup, setPatientGroup] = useState<PatientGroup | ''>(initialPatientGroup ?? '')
  const [payment, setPayment] = useState<typeof payments[number][0] | ''>('')
  const [radius, setRadius] = useState(5)
  const [search, setSearch] = useState<SearchState>()
  const [attempt, setAttempt] = useState(0)
  const [selected, setSelected] = useState<{ id: string; focusMarker: boolean; query: ClinicSearch }>()
  const [mapStatus, setMapStatus] = useState<MapStatus>('loading')
  const [picking, setPicking] = useState(false)
  const lookup = useRef<AbortController>(null)
  const clinicCards = useRef(new Map<string, HTMLElement>())

  const query = useMemo<ClinicSearch | undefined>(() => location && patientGroup ? {
    ...location.point, radius_km: radius, specialty_code: specialty || undefined,
    payment_method: payment || undefined, patient_group: patientGroup,
  } : undefined, [location, radius, specialty, payment, patientGroup])
  const current = search?.query === query && search?.attempt === attempt ? search : undefined
  const items = current && 'result' in current ? current.result.items : undefined
  const selectedItem = selected && selected.query === query && items?.some((item) => item.id === selected.id) ? selected : undefined
  const refreshingMap = !!query && !current && search && 'result' in search && search.result.items.length > 0
    && search.query.lat === query.lat && search.query.lon === query.lon
  const hasMap = !!items?.length || picking || refreshingMap
  const showMap = hasMap && mapStatus !== 'error'

  useEffect(() => () => lookup.current?.abort(), [])
  const lookupAddress = useCallback(async (value: string, controller: AbortController, submitted: boolean) => {
    try {
      const { candidates } = await client.geocode(value, controller.signal)
      if (controller.signal.aborted) return
      setCandidates(candidates)
      if (submitted && !candidates.length) {
        setLocationError('Дом не найден в справочнике. Уточните улицу, номер дома, корпус или строение.')
      }
    } catch (cause) {
      if (controller.signal.aborted) return
      if (cause instanceof ApiError && cause.code === 'clinic_outside_pilot') setLocationError(pilotMessage)
      else if (submitted) {
        setLocationError('Справочник адресов временно недоступен. Повторите поиск или определите местоположение.')
      }
    } finally {
      if (!controller.signal.aborted) setLocating('')
    }
  }, [client])
  useEffect(() => {
    const value = buildingAddress(address)
    if (!editingAddress || value.length < 3) return
    const controller = new AbortController()
    lookup.current = controller
    const timer = window.setTimeout(() => { if (!controller.signal.aborted) void lookupAddress(value, controller, false) }, 300)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [address, editingAddress, lookupAddress])
  useEffect(() => {
    if (!query) return
    const controller = new AbortController()
    client.search(query, controller.signal).then(
      (result) => {
        if (controller.signal.aborted) return
        setSearch({ query, attempt, result })
      },
      (cause) => {
        if (controller.signal.aborted) return
        const outside = cause instanceof ApiError && cause.code === 'clinic_outside_pilot'
        setSearch({ query, attempt, outside, error: outside ? pilotMessage : 'Не удалось загрузить медучреждения.' })
      },
    )
    return () => controller.abort()
  }, [client, query, attempt])

  function resetLocation() {
    lookup.current?.abort()
    setLocation(null)
    setLocating('')
    setLocationError('')
    setCandidates([])
    setSelected(undefined)
    setMapStatus('loading')
    setPicking(false)
    setEditingAddress(false)
  }

  function findLocation() {
    resetLocation()
    if (!navigator.geolocation) {
      setLocationError('Геолокация недоступна в этом браузере. Введите адрес вручную.')
      return
    }
    const controller = new AbortController()
    lookup.current = controller
    setLocating('Определяем местоположение…')
    navigator.geolocation.getCurrentPosition(({ coords }) => {
      if (controller.signal.aborted) return
      setLocating('')
      if (!Number.isFinite(coords.accuracy) || coords.accuracy > 1000) {
        setLocationError('Точность местоположения ниже 1 км. Введите адрес вручную.')
      } else {
        selectLocationPoint({ lat: coords.latitude, lon: coords.longitude }, 'geolocation')
      }
    }, (failure) => {
      if (controller.signal.aborted) return
      setLocating('')
      setLocationError(locationErrors[failure.code] || locationErrors[2])
    }, { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 })
  }

  function chooseAddress(candidate: AddressCandidate) {
    resetLocation()
    if (candidate.city.trim().toLocaleLowerCase('ru-RU') !== 'курган') {
      setLocationError(pilotMessage)
      return
    }
    setAddress(candidate.label)
    setLocation({ source: 'address', point: { lat: candidate.lat, lon: candidate.lon } })
  }

  async function findAddress() {
    resetLocation()
    const value = buildingAddress(address)
    if (value.length < 3) {
      setLocationError('Введите адрес из трёх или более символов.')
      return
    }
    const controller = new AbortController()
    lookup.current = controller
    setLocating('Ищем адрес…')
    await lookupAddress(value, controller, true)
  }

  function chooseMapLocation() {
    if (!location) {
      lookup.current?.abort()
      setLocating('')
    }
    setEditingAddress(false)
    setCandidates([])
    setLocationError('')
    if (mapStatus === 'error') setMapStatus('loading')
    setPicking(true)
  }

  function selectLocationPoint(point: Coordinates, source: 'geolocation' | 'map') {
    resetLocation()
    setAddress('')
    setLocation({ source, point })
    if (source !== 'geolocation') return
    const controller = new AbortController()
    lookup.current = controller
    setLocating('Определяем ближайший адрес…')
    void client.reverseGeocode(point, controller.signal).then(
      ({ candidates: [nearest] }) => {
        if (!controller.signal.aborted && nearest) setAddress(nearest.label)
      },
      () => {},
    ).finally(() => {
      if (!controller.signal.aborted) setLocating('')
    })
  }

  function changePatientGroup(group: PatientGroup | '') {
    setPatientGroup(group)
    if (group === 'adult' && isChildSpecialty(specialty)) setSpecialty('')
  }

  function selectOnMap(id: string) {
    const card = clinicCards.current.get(id)
    if (!card || !query) return
    setSelected({ id, focusMarker: false, query })
    card.focus()
    card.scrollIntoView({ block: 'nearest' })
  }

  return <div className="clinic-page">
    <div><Button icon="arrow-left" variant="secondary" onClick={onBack}>Назад</Button></div>
    <h1 tabIndex={-1}>Медучреждения рядом</h1>
    <Card className="clinic-controls">
      <div className="clinic-actions">
        <Button variant="secondary" onClick={findLocation}>Определить моё местоположение</Button>
        <Button variant="secondary" aria-expanded={picking} onClick={picking ? () => setPicking(false) : chooseMapLocation}>
          {picking ? 'Закрыть выбор на карте' : 'Поставить точку на карте'}
        </Button>
      </div>
      <form className="clinic-address" onSubmit={(event) => { event.preventDefault(); void findAddress() }}>
        <label>Адрес пациента
          <input type="text" value={address} maxLength={240} autoComplete="off" placeholder="Курган, улица и номер дома"
            onChange={(event) => { resetLocation(); setAddress(event.target.value); setEditingAddress(true) }} />
        </label>
        <Button type="submit">Найти по адресу</Button>
      </form>
      <p className="field-hint">Укажите улицу и номер дома. От этого адреса считаем расстояние до клиник. Номер квартиры не нужен.</p>
      {location?.source === 'map' && <p className="field-hint">Точка поиска выбрана на карте.</p>}
      {location?.source === 'geolocation' && <p className="field-hint">
        Ищем от местоположения устройства.
        {address ? ' В поле указан ближайший адрес.' : !locating && ' Ближайший адрес не удалось определить.'}
      </p>}
      <p className="field-hint">Адресный справочник © <a href="https://www.openstreetmap.org/copyright"
        target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a></p>
      {locating && <p role="status">{locating}</p>}
      {locationError && <p role="alert">{locationError}</p>}
      {!!candidates.length && <div>
        <p id="clinic-candidates" role="status">{candidates.length === 1 ? 'Подтвердите найденный адрес.' : 'Выберите подходящий адрес.'}</p>
        <ul className="clinic-candidates" aria-labelledby="clinic-candidates">{candidates.map((candidate) =>
          <li key={JSON.stringify(candidate)}><Button variant="secondary" onClick={() => chooseAddress(candidate)}>
            {candidate.label}
          </Button></li>)}</ul>
      </div>}
      <fieldset className="clinic-payment">
        <legend>Способ оплаты</legend>
        <div className="clinic-payment-options">
          <label><input type="radio" name="clinic-payment" checked={!payment} onChange={() => setPayment('')} />Все</label>
          {payments.map(([method, label]) => <label key={method}>
            <input type="radio" name="clinic-payment" checked={payment === method}
              onChange={() => setPayment(method)} />{label}
          </label>)}
        </div>
      </fieldset>
      <div className="clinic-filters">
        <label>Возраст пациента
          <select value={patientGroup} onChange={(event) => changePatientGroup(event.target.value as PatientGroup | '')}>
            <option value="" disabled>Выберите возрастную группу</option>
            <option value="child">Младше 18 лет</option>
            <option value="adult">18 лет и старше</option>
          </select>
        </label>
        <label>Специалист
          <select value={specialty} onChange={(event) => setSpecialty(event.target.value)}>
            <option value="">Любой специалист</option>
            {specialtyOptions.filter(([code]) => patientGroup !== 'adult' || !isChildSpecialty(code))
              .map(([code, name]) => <option key={code} value={code}>{name}</option>)}
          </select>
        </label>
        <label>Радиус
          <select value={radius} onChange={(event) => setRadius(Number(event.target.value))}>
            {radii.map((km) => <option key={km} value={km}>{km} км</option>)}
          </select>
        </label>
      </div>
    </Card>
    {location && !patientGroup && <p role="status">Выберите возрастную группу пациента, чтобы подобрать медучреждения.</p>}
    {query && !current && <p role="status">Ищем медучреждения…</p>}
    {current && 'error' in current && <div className="survey-error" role="alert">
      <p>{current.error}</p>
      {!current.outside && <Button variant="secondary" onClick={() => setAttempt((value) => value + 1)}>Повторить поиск</Button>}
    </div>}
    {items && items.length === 0 && <div>
      <p role="status">Медучреждения не найдены. Измените фильтры или увеличьте радиус поиска.</p>
      {specialty && <Button variant="secondary" onClick={() => setSpecialty('')}>
        Показать клиники без фильтра по специалисту
      </Button>}
      {radius < 30 && <Button variant="secondary" onClick={() => setRadius(radii[radii.indexOf(radius) + 1])}>
        Увеличить радиус
      </Button>}
    </div>}
    {hasMap && mapStatus === 'error' && <div>
      {picking && <p role="status">Карта недоступна. Введите адрес или определите местоположение.</p>}
      {!picking && !!items?.length && <p role="status">Карта недоступна. Медучреждения показаны списком.</p>}
      <Button variant="secondary" onClick={() => setMapStatus('loading')}>Повторить загрузку карты</Button>
    </div>}
    <div className={showMap && !picking && (items?.length || refreshingMap) ? 'clinic-results' : undefined}>
      {showMap && <ClinicMap items={picking ? noItems : items ?? noItems} selection={picking ? undefined : selectedItem}
        picking={picking} origin={location?.point} ready={mapStatus === 'ready'}
        onSelect={selectOnMap} onStatus={setMapStatus} onPoint={(point) => selectLocationPoint(point, 'map')}
        onCancel={() => setPicking(false)} />}
      {!picking && items && items.length > 0 && <div className="clinic-results-list">
        {mapStatus === 'loading' && <p role="status">Загружаем карту…</p>}
        {items.map((item) => <ClinicResult key={item.id} clinic={item} paidSearch={payment === 'paid'} selected={selectedItem?.id === item.id}
          onSelect={mapStatus === 'ready' && query ? () => setSelected({ id: item.id, focusMarker: true, query }) : undefined}
          register={(card) => { if (card) clinicCards.current.set(item.id, card); else clinicCards.current.delete(item.id) }} />)}
      </div>}
    </div>
  </div>
}
