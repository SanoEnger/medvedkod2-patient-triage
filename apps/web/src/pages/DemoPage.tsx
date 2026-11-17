import { useState } from 'react'
import { Button, Card, SelectField, TextAreaField } from '../components/ui'

export function DemoPage({ onBack }: { onBack: () => void }) {
  const [saved, setSaved] = useState(false)

  return <div className="demo-page">
    <Button variant="secondary" onClick={onBack}><span aria-hidden="true">←</span> На главную</Button>
    <Card>
      <p className="eyebrow">Знакомство с интерфейсом</p>
      <h1 tabIndex={-1}>Попробуйте пример формы</h1>
      <p className="lead">Это демонстрация элементов управления. Используйте только вымышленные данные.</p>
      <form onSubmit={(event) => { event.preventDefault(); setSaved(true) }} onChange={() => setSaved(false)}>
        <SelectField label="Пример варианта" defaultValue="first"><option value="first">Пример 1</option><option value="second">Пример 2</option></SelectField>
        <TextAreaField label="Пример текстового ответа" hint="Не вводите настоящие жалобы и личные данные. Текст никуда не отправляется и не сохраняется после выхода из примера." defaultValue="Вымышленный текст для знакомства с формой." rows={4} maxLength={500} />
        <div className="form-actions"><Button type="submit">Проверить форму</Button><Button variant="secondary" type="reset" onClick={() => setSaved(false)}>Сбросить</Button></div>
        {saved && <p className="form-feedback" role="status">Готово. Пример проверен, данные никуда не отправлены.</p>}
      </form>
    </Card>
  </div>
}
