import { Button, Card } from '../components/ui'

const steps = [
  ['Расскажите, что беспокоит', 'Выберите жалобу и ответьте на уточняющие вопросы.'],
  ['Добавьте важные сведения', 'Сообщите об особенностях здоровья, которые нужно учесть.'],
  ['Узнайте, куда обратиться', 'Получите ориентир по срочности и профилю врача.'],
]

export function WelcomePage({ onOpenDemo }: { onOpenDemo: () => void }) {
  return <div className="welcome-layout">
    <div className="intro">
      <p className="eyebrow">Рядом, когда нужен ориентир</p>
      <h1 tabIndex={-1}>Первый шаг <br />к нужной помощи</h1>
      <p className="lead">МедВед поможет разобраться, к какому врачу обратиться и насколько срочно нужна помощь.</p>
      <div className="route-illustration" aria-hidden="true"><span className="route-point" /><span className="route-line" /><span className="route-destination">+</span></div>
      <p className="intro-note">Спокойно, последовательно,<br />с вниманием к вашему самочувствию.</p>
    </div>
    <div className="welcome-content">
      <Card className="overview" aria-labelledby="overview-title">
        <h2 id="overview-title">Как это будет работать</h2>
        <ol className="steps">{steps.map(([title, text], index) => <li key={title}><span className="step-number" aria-hidden="true">{index + 1}</span><div><h3>{title}</h3><p>{text}</p></div></li>)}</ol>
        <div className="notice"><h3>Помогаем с маршрутом, а не с диагнозом</h3><p>Бот не ставит диагноз и не заменяет врача.</p></div>
        <Button className="wide" onClick={onOpenDemo}><span>Открыть пример интерфейса</span><span aria-hidden="true">→</span></Button>
        <p className="demo-note">Сейчас доступен пример на вымышленных данных. Опрос появится на следующем этапе.</p>
      </Card>
      <Card className="privacy-note"><span className="privacy-symbol" aria-hidden="true">✓</span><div><h2>Без личных данных</h2><p>Для демонстрации не нужны имя, телефон или медицинские документы.</p></div></Card>
    </div>
  </div>
}
