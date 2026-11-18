import iconsUrl from '../assets/medved-icons.svg?url'

export type IconName = 'arrow-left' | 'arrow-right' | 'home' | 'close' | 'chevron-down'
  | 'check' | 'restart' | 'text-size' | 'clipboard' | 'edit' | 'map-pin' | 'info'
  | 'shield' | 'warning' | 'phone' | 'pain' | 'temperature' | 'breathing' | 'stomach'
  | 'skin' | 'injury' | 'more'

export function Icon({ name, className = '' }: { name: IconName; className?: string }) {
  return <svg className={`icon ${className}`} width="24" height="24" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <use href={`${iconsUrl}#${name}`} />
  </svg>
}