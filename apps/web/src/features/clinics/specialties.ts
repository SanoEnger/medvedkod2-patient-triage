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
  allergist: 'Аллерголог-иммунолог',
  exercise_therapy: 'Врач по лечебной физкультуре',
  psychiatrist: 'Психиатр',
  geriatrician: 'Гериатр',
  dental_practitioner: 'Зубной врач',
  infectious_disease_specialist: 'Инфекционист',
  pediatric_cardiologist: 'Детский кардиолог',
  clinical_psychologist: 'Клинический психолог',
  oncologist: 'Онколог',
  occupational_physician: 'Профпатолог',
  addiction_psychiatrist: 'Психиатр-нарколог',
  psychotherapist: 'Психотерапевт',
  pulmonologist: 'Пульмонолог',
  rheumatologist: 'Ревматолог',
  pediatric_dentist: 'Детский стоматолог',
  dentist: 'Стоматолог общей практики',
  prosthodontist: 'Стоматолог-ортопед',
  dental_therapist: 'Стоматолог-терапевт',
  dental_surgeon: 'Стоматолог-хирург',
  orthopedic_traumatologist: 'Травматолог-ортопед',
  urologist: 'Уролог',
  pediatric_urologist: 'Детский уролог-андролог',
  feldsher: 'Фельдшер',
  physiotherapist: 'Физиотерапевт',
  tb_specialist: 'Фтизиатр',
  pediatric_surgeon: 'Детский хирург',
  endocrinologist: 'Эндокринолог',
  gastroenterologist: 'Гастроэнтеролог',
  nephrologist: 'Нефролог',
  hematologist: 'Гематолог',
  neurosurgeon: 'Нейрохирург',
  coloproctologist: 'Колопроктолог',
}

export function isChildSpecialty(code: string) {
  return code === 'pediatrician' || code.startsWith('pediatric_')
}

const aliases: Record<string, string> = {
  лор: 'otolaryngologist', 'лор-врач': 'otolaryngologist', окулист: 'ophthalmologist',
  'акушер-гинеколог': 'gynecologist', дерматовенеролог: 'dermatologist', аллерголог: 'allergist',
  травматолог: 'orthopedic_traumatologist', ортопед: 'orthopedic_traumatologist',
  стоматолог: 'dentist', 'стоматолог дежурный': 'dentist', проктолог: 'coloproctologist',
  нарколог: 'addiction_psychiatrist', 'кардиолог детский': 'pediatric_cardiologist',
  'хирург детский': 'pediatric_surgeon', 'стоматолог детский': 'pediatric_dentist',
  'уролог-андролог детский': 'pediatric_urologist',
}

const codesByName = new Map(Object.entries(specialties)
  .map(([code, name]) => [name.toLocaleLowerCase('ru-RU'), code]))

export function specialtyCode(specialty: string | null) {
  const name = specialty?.trim().toLocaleLowerCase('ru-RU').replace(/\s*[‑–—-]\s*/g, '-')
  if (!name) return ''
  if (Object.hasOwn(specialties, name)) return name
  const exact = codesByName.get(name)
  if (exact) return exact
  const normalized = name.replace(/^врач[\s-]+/, '').replace(/\s+участковый$/, '')
  return (Object.hasOwn(aliases, normalized) ? aliases[normalized] : undefined)
    ?? codesByName.get(normalized) ?? codesByName.get(normalized.replace(/^детский\s+/, '')) ?? ''
}
