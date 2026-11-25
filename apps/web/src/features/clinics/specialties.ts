export const specialties: Record<string, string> = {
  therapist: 'Терапевт',
  pediatrician: 'Педиатр',
  dermatologist: 'Дерматолог',
  cardiologist: 'Кардиолог',
  neurologist: 'Невролог',
  otolaryngologist: 'Оториноларинголог',
  ophthalmologist: 'Офтальмолог',
  gynecologist: 'Гинеколог',
  surgeon: 'Хирург',
  general_practitioner: 'Врач общей практики',
  preventive_care: 'Диспансеризация',
}

export function specialtyCode(specialty: string | null) {
  const normalized = specialty?.trim().toLocaleLowerCase('ru-RU').replace(/[‑–—]/g, '-')
    .replace(/^врач[\s-]+(?!общей практики)/, '').replace(/^детский\s+|\s+участковый$/g, '')
  if (!normalized) return ''
  if (Object.hasOwn(specialties, normalized)) return normalized
  if (normalized === 'лор' || normalized === 'лор-врач') return 'otolaryngologist'
  if (normalized === 'окулист') return 'ophthalmologist'
  if (normalized === 'акушер-гинеколог') return 'gynecologist'
  if (normalized === 'дерматовенеролог') return 'dermatologist'
  return Object.entries(specialties).find(([, label]) => label.toLocaleLowerCase('ru-RU') === normalized)?.[0] ?? ''
}
