import { useId } from 'react'
import { Icon } from './Icon'
import type { IconName } from './Icon'
import { VoiceInput } from './VoiceInput'
import type { VoiceOptions } from './VoiceInput'
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'

export function Button({ variant = 'primary', className = '', type = 'button', icon, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary'; icon?: IconName }) {
  return <button type={type} className={`button button--${variant} ${className}`} {...props}>
    {icon && <Icon name={icon} />}<span className="button-label">{children}</span>
  </button>
}

export function Card({ className = '', ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={`card ${className}`} {...props} />
}

export function SelectField({ label, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label: string; children: ReactNode }) {
  const id = useId()
  return <div className="field"><label htmlFor={id}>{label}</label><select id={id} {...props}>{children}</select></div>
}

export function TextAreaField({ label, hint, voice, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint: string; voice?: VoiceOptions }) {
  const id = useId()
  const control = <textarea id={id} aria-describedby={`${id}-hint`} {...props} />
  return <div className="field"><label htmlFor={id}>{label}</label>{voice ? <VoiceInput label={label} {...voice}>{control}</VoiceInput> : control}<p id={`${id}-hint`} className="field-hint">{hint}</p></div>
}


export function TextField({ label, hint, voice, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint: string; voice?: VoiceOptions }) {
  const id = useId()
  const control = <input id={id} aria-describedby={id + '-hint'} {...props} />
  return <div className="field"><label htmlFor={id}>{label}</label>{voice ? <VoiceInput label={label} {...voice}>{control}</VoiceInput> : control}<p id={id + '-hint'} className="field-hint">{hint}</p></div>
}
