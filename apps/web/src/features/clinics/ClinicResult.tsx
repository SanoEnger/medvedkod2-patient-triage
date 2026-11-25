import type { Clinic } from '../../api/clinics'
import { Button, Card } from '../../components/ui'
import { specialties } from './specialties'

const kilometers = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

function ExternalLink({ url, label, className }: { url: string | null; label: string; className?: string }) {
  if (!url) return null
  let target: URL
  try {
    target = new URL(url)
  } catch {
    return null
  }
  if (target.protocol !== 'https:' || target.username || target.password) return null
  return <a className={className} href={target.href} target="_blank" rel="noopener noreferrer">{label}</a>
}

export function ClinicResult({ clinic, paidSearch, selected, onSelect, register }: {
  clinic: Clinic; paidSearch: boolean; selected?: boolean; onSelect?: () => void; register?: (card: HTMLElement | null) => void
}) {
  const paymentNotes = [...new Set(clinic.payments.filter((payment) => payment.method !== 'dms').map((payment) =>
    [payment.method === 'oms' ? 'ОМС' : 'Платно', specialties[payment.specialty_code]]
      .filter(Boolean).join(' · ')))]
  const oms = clinic.payments.some((payment) => payment.method === 'oms')
  const paid = clinic.payments.some((payment) => payment.method === 'paid')
  const phoneOnly = clinic.kind === 'private' || paidSearch || (paid && !oms && !clinic.oms_needs_confirmation)
  const gosuslugi = phoneOnly ? null : clinic.gosuslugi_url
  const poliklinika45 = phoneOnly ? null : clinic.poliklinika45_url ?? null
  const namedSpecialties = clinic.specialties?.map((code) => specialties[code]).filter(Boolean) ?? []
  return <article tabIndex={-1} ref={register} aria-labelledby={`clinic-${clinic.id}`}>
    <Card className={`clinic-card${selected ? ' clinic-card--selected' : ''}`}>
      {clinic.demo && <p className="notice">Демонстрационная карточка. Контакты и услуги вымышлены.</p>}
      <h2 id={`clinic-${clinic.id}`}>{clinic.name}</h2>
      <p>{clinic.address}</p>
      <p>{clinic.kind === 'public' ? 'Государственная' : 'Частная'} · {kilometers.format(clinic.distance_km)} км по прямой</p>
      {namedSpecialties.length > 0 && <p>Специалисты · {namedSpecialties.join(', ')}</p>}
      {paymentNotes.length > 0 ? <ul className="clinic-payments">{paymentNotes.map((note) => <li key={note}>{note}</li>)}</ul>
        : clinic.oms_needs_confirmation
          ? <p>Учреждение участвует в программе ОМС. Уточните условия приёма в этом филиале в регистратуре.</p>
          : <p>Уточните способы оплаты в клинике.</p>}
      {oms && <p>Уточните условия приёма по ОМС в регистратуре.</p>}
      {paid && <p>Уточните стоимость в клинике.</p>}
      {phoneOnly && <p>Запись по телефону</p>}
      <ul className="clinic-contacts" aria-label={phoneOnly ? 'Телефоны для записи' : 'Контакты'}>
        {clinic.phones.filter((phone) => /^(?:\+[1-9][0-9]{6,14}|122)$/.test(phone)).map((phone) =>
          <li key={phone}><a href={`tel:${phone}`}>{phone}</a></li>)}
        {!phoneOnly && clinic.website && <li><ExternalLink url={clinic.website} label="Сайт учреждения" /></li>}
      </ul>
      {(gosuslugi || poliklinika45 || onSelect) && <div className="clinic-actions">
        <ExternalLink url={gosuslugi} label="Записаться через Госуслуги" className="button button--primary" />
        <ExternalLink url={poliklinika45} label="Записаться через Поликлинику45" className="button button--secondary" />
        {onSelect && <Button variant="secondary" aria-pressed={selected} onClick={onSelect}>Показать на карте</Button>}
      </div>}
      {gosuslugi && clinic.gosuslugi_select_branch && <p>Выберите нужный филиал на Госуслугах.</p>}
    </Card>
  </article>
}
