import { useId } from 'react'
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'

export function Button({ variant = 'primary', className = '', type = 'button', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' }) {
  return <button type={type} className={`button button--${variant} ${className}`} {...props} />
}

export function Card({ className = '', ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={`card ${className}`} {...props} />
}

export function SelectField({ label, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label: string; children: ReactNode }) {
  const id = useId()
  return <div className="field"><label htmlFor={id}>{label}</label><select id={id} {...props}>{children}</select></div>
}

export function TextAreaField({ label, hint, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint: string }) {
  const id = useId()
  return <div className="field"><label htmlFor={id}>{label}</label><textarea id={id} aria-describedby={`${id}-hint`} {...props} /><p id={`${id}-hint`} className="field-hint">{hint}</p></div>
}
