export type Coordinates = { lat: number; lon: number }
export type AddressCandidate = Coordinates & { label: string; city: string }
export type PaymentMethod = 'oms' | 'dms' | 'paid'
export type PatientGroup = 'child' | 'adult'
export type Insurer = { id: string; name: string }
export type ClinicPayment = { method: PaymentMethod; specialty_code: string; insurer: Insurer | null; program: string | null }
export type ClinicSource = { name: string; url: string; updated_at: string | null }
export type Clinic = Coordinates & {
  id: string; name: string; address: string; kind: 'public' | 'private'; phones: string[]
  website: string | null; booking_url: string | null; gosuslugi_url: string | null; gosuslugi_select_branch: boolean
  poliklinika45_url?: string | null
  demo: boolean; payments: ClinicPayment[]; distance_km: number
  specialties?: string[]; sources?: ClinicSource[]
}
export type ClinicSearch = Coordinates & {
  radius_km: number; specialty_code?: string; payment_method?: PaymentMethod; insurer_id?: string
  patient_group?: PatientGroup
}
export type ClinicSearchResult = { items: Clinic[]; insurers: Insurer[] }
export interface ClinicsClient {
  geocode(address: string, signal: AbortSignal): Promise<{ candidates: AddressCandidate[] }>
  search(query: ClinicSearch, signal: AbortSignal): Promise<ClinicSearchResult>
}
