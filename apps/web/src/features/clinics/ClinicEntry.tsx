import type { Triage } from '../../api/contracts'
import { Button } from '../../components/ui'

export function ClinicEntry({ result, age, onOpen }: {
  result: Triage; age?: number | null; onOpen: (result: Triage, age?: number | null) => void
}) {
  if (result.urgency === 'EMERGENCY') return null
  const directory = result.urgency === 'UNKNOWN'
  return <div>
    <Button variant="secondary" onClick={() => onOpen(result, age)}>
      {directory ? 'Посмотреть медучреждения рядом' : 'Найти поликлиники рядом'}
    </Button>
    {directory && !result.specialty && <p className="field-hint">Это справочник медучреждений. По результату опроса пока нельзя подобрать специалиста.</p>}
  </div>
}
