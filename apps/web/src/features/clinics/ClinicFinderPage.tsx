import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import type { AddressCandidate, Clinic, ClinicSearch, ClinicSearchResult, ClinicsClient, Coordinates, PatientGroup, PaymentMethod } from '../../api/clinics'
import { Button, Card } from '../../components/ui'
import { ClinicMap } from './ClinicMap'
import type { MapStatus } from './ClinicMap'
import { ClinicResult } from './ClinicResult'
import { specialties } from './specialties'
import './clinics.css'

const payments = { oms: 'ОМС', dms: 'ДМС', paid: 'Платно' }
const pilotMessage = 'Каталог сейчас покрывает только Курган.'
const locationErrors: Record<number, string> = {
  1: 'Доступ к местоположению запрещён. Введите адрес вручную.',
  2: 'Не удалось определить местоположение. Введите адрес вручную.',
  3: 'Истекло время ожидания местоположения. Введите адрес вручную или повторите попытку.',
}
const noItems: Clinic[] = []
const radii = [5, 10, 20, 30]
const buildingAddress = (value: string) => value.replace(/(?:,\s*|\s+)(?:кв(?:артира)?\.?|подъезд|этаж)\s*№?\s*\d.*$/iu, '').trim()

type SearchState = { query: ClinicSearch; attempt: number; result: ClinicSearchResult }
  | { query: ClinicSearch; attempt: number; error: string; outside: boolean }

export function ClinicFinderPage({ client, initialSpecialty, initialPatientGroup, onBack }: {
  client: ClinicsClient; initialSpecialty: string; initialPatientGroup?: PatientGroup; onBack: () => void
}) {
  const [address, setAddress] = useState('')
  const [editingAddress, setEditingAddress] = useState(false)
  const [candidates, setCandidates] = useState<AddressCandidate[]>([])
  const [location, setLocation] = useState<Coordinates | null>(null)
  const [locating, setLocating] = useState('')
  const [locationError, setLocationError] = useState('')
  const [specialty, setSpecialty] = useState(initialSpecialty)
  const [patientGroup, setPatientGroup] = useState<PatientGroup | ''>(initialPatientGroup ?? '')
  const [payment, setPayment] = useState<PaymentMethod | ''>('')
  const [insurer, setInsurer] = useState('')
  const [radius, setRadius] = useState(5)
  const [search, setSearch] = useState<SearchState>()
  const [insurers, setInsurers] = useState<ClinicSearchResult['insurers']>([])
  const [attempt, setAttempt] = useState(0)
  const [selected, setSelected] = useState<{ id: string; focusMarker: boolean }>()
  const [mapStatus, setMapStatus] = useState<MapStatus>('loading')
  const [picking, setPicking] = useState(false)
  const [offerMap, setOfferMap] = useState(false)
  const lookup = useRef<AbortController>(null)
  const clinicCards = useRef(new Map<string, HTMLElement>())

  const query = useMemo<ClinicSearch | undefined>(() => location && patientGroup ? {
    ...location, radius_km: radius, specialty_code: specialty || undefined,
    payment_method: payment || undefined, insurer_id: insurer || undefined, patient_group: patientGroup,
  } : undefined, [location, radius, specialty, payment, insurer, patientGroup])
  const current = search?.query === query && search?.attempt === attempt ? search : undefined
  const items = current && 'result' in current ? current.result.items : undefined
  const selectedItem = items?.some((item) => item.id === selected?.id) ? selected : undefined
  const showMap = (!!items?.length || picking) && mapStatus !== 'error'

  useEffect(() => () => lookup.current?.abort(), [])
  const lookupAddress = useCallback(async (value: string, controller: AbortController, submitted: boolean) => {
    try {
      const { candidates } = await client.geocode(value, controller.signal)
      if (controller.signal.aborted) return
      setCandidates(candidates)
      if (submitted && !candidates.length) {
        setLocationError('Дом не найден в справочнике. Уточните улицу, номер дома, корпус или строение.')
        setOfferMap(true)
      }
    } catch (cause) {
      if (controller.signal.aborted) return
      if (cause instanceof ApiError && cause.code === 'clinic_outside_pilot') setLocationError(pilotMessage)
      else if (submitted) {
        setLocationError('Справочник адресов временно недоступен. Повторите поиск или определите местоположение.')
        setOfferMap(true)
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
        setInsurers(result.insurers)
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
    setInsurer('')
    setInsurers([])
    setMapStatus('loading')
    setOfferMap(false)
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
        setAddress('')
        setLocation({ lat: coords.latitude, lon: coords.longitude })
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
    setLocation({ lat: candidate.lat, lon: candidate.lon })
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

  function selectOnMap(id: string) {
    const card = clinicCards.current.get(id)
    if (!card) return
    setSelected({ id, focusMarker: false })
    card.focus()
    card.scrollIntoView({ block: 'nearest' })
  }

  return <div className="clinic-page">
    <div><Button icon="arrow-left" variant="secondary" onClick={onBack}>Назад</Button></div>
    <h1 tabIndex={-1}>Медучреждения рядом</h1>
    <Card className="clinic-controls">
      <div><Button variant="secondary" onClick={findLocation}>Определить моё местоположение</Button></div>
      <form className="clinic-address" onSubmit={(event) => { event.preventDefault(); void findAddress() }}>
        <label>Адрес пациента
          <input type="text" value={address} maxLength={240} autoComplete="off" placeholder="Курган, улица и номер дома"
            onChange={(event) => { resetLocation(); setAddress(event.target.value); setEditingAddress(true) }} />
        </label>
        <Button type="submit">Найти по адресу</Button>
      </form>
      <p className="field-hint">Укажите улицу и номер дома. От этого адреса считаем расстояние до клиник. Номер квартиры не нужен.</p>
      <p className="field-hint">Адресный справочник © <a href="https://www.openstreetmap.org/copyright"
        target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a></p>
      {locating && <p role="status">{locating}</p>}
      {locationError && <p role="alert">{locationError}</p>}
      {offerMap && !picking && mapStatus !== 'error' && <div>
        <Button variant="secondary" onClick={() => { lookup.current?.abort(); setEditingAddress(false); setPicking(true) }}>Поставить точку на карте</Button>
      </div>}
      {picking && <p role="status">{mapStatus === 'error'
        ? 'Карта недоступна. Уточните адрес или определите местоположение.'
        : 'Выберите точку на карте или переместите карту стрелками и подтвердите её центр.'}</p>}
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
          <label><input type="radio" name="clinic-payment" checked={!payment} onChange={() => { setPayment(''); setInsurer('') }} />Все</label>
          {(Object.keys(payments) as PaymentMethod[]).map((method) => <label key={method}>
            <input type="radio" name="clinic-payment" checked={payment === method}
              onChange={() => { setPayment(method); setInsurer('') }} />{payments[method]}
          </label>)}
        </div>
      </fieldset>
      <div className="clinic-filters">
        <label>Возраст пациента
          <select value={patientGroup} onChange={(event) => {
            setPatientGroup(event.target.value as PatientGroup | ''); setInsurer(''); setInsurers([])
          }}>
            <option value="" disabled>Выберите возрастную группу</option>
            <option value="child">Младше 18 лет</option>
            <option value="adult">18 лет и старше</option>
          </select>
        </label>
        <label>Специалист
          <select value={specialty} onChange={(event) => { setSpecialty(event.target.value); setInsurer(''); setInsurers([]) }}>
            <option value="">Любой специалист</option>
            {Object.entries(specialties).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
          </select>
        </label>
        <label>Радиус
          <select value={radius} onChange={(event) => { setRadius(Number(event.target.value)); setInsurer(''); setInsurers([]) }}>
            {radii.map((km) => <option key={km} value={km}>{km} км</option>)}
          </select>
        </label>
        {payment === 'dms' && insurers.length > 0 && <label>Страховая
          <select value={insurer} onChange={(event) => setInsurer(event.target.value)}>
            <option value="">Любая страховая</option>
            {insurers.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
          </select>
        </label>}
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
      {specialty && <Button variant="secondary" onClick={() => { setSpecialty(''); setInsurer(''); setInsurers([]) }}>
        Показать клиники без фильтра по специалисту
      </Button>}
      {radius < 30 && <Button variant="secondary" onClick={() => { setRadius(radii[radii.indexOf(radius) + 1]); setInsurer(''); setInsurers([]) }}>
        Увеличить радиус
      </Button>}
    </div>}
    <div className={showMap && items?.length ? 'clinic-results' : undefined}>
      {showMap && <ClinicMap items={items ?? noItems} selection={selectedItem} picking={picking}
        onSelect={selectOnMap} onStatus={setMapStatus} onPoint={(point) => { resetLocation(); setLocation(point) }} />}
      {items && items.length > 0 && <div className="clinic-results-list">
        {mapStatus === 'loading' && <p role="status">Загружаем карту…</p>}
        {mapStatus === 'error' && <p role="status">Карта недоступна. Медучреждения показаны списком.</p>}
        {items.map((item) => <ClinicResult key={item.id} clinic={item} paidSearch={payment === 'paid'} selected={selectedItem?.id === item.id}
          onSelect={mapStatus === 'ready' ? () => setSelected({ id: item.id, focusMarker: true }) : undefined}
          register={(card) => { if (card) clinicCards.current.set(item.id, card); else clinicCards.current.delete(item.id) }} />)}
      </div>}
    </div>
  </div>
}
