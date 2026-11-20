import { Button, Card } from '../components/ui'
import { Icon } from '../components/Icon'
import questionnaireUrl from '../assets/questionnaire.svg?url'
import medvedBearUrl from '../assets/medved-bear-button.svg?url'

const steps = [
  ['Расскажите, что беспокоит', 'Выберите жалобу и ответьте на уточняющие вопросы.'],
  ['Добавьте важные сведения', 'Сообщите об особенностях здоровья, которые нужно учесть.'],
  ['Узнайте, куда обратиться', 'Получите ориентир по срочности и профилю врача.'],
]

export function WelcomePage({ onStart, onChat, surveyInProgress = false, chatBlocked = false }: { onStart: () => void; onChat?: () => void; surveyInProgress?: boolean; chatBlocked?: boolean }) {
  return <div className="welcome-layout">
    <div className="intro">
      <h1 tabIndex={-1}>Привет, я МедВед</h1>
      <p className="lead">Подскажу, к какому врачу обратиться</p>
      <div className="route-illustration" aria-hidden="true"><img className="route-point" src={questionnaireUrl} width={22} height={22} alt="" /><span className="route-line" /><span className="route-destination"><img src={medvedBearUrl} width={32} height={32} alt="" /></span></div>
    </div>
    <div className="welcome-content">
      <Card className="overview" aria-labelledby="overview-title">
        <h2 id="overview-title">Как пройдёт опрос</h2>
        <ol className="steps">{steps.map(([title, text], index) => <li key={title}><span className="step-number" aria-hidden="true">{index + 1}</span><div><h3>{title}</h3><p>{text}</p></div></li>)}</ol>
        <div className="notice"><h3>Помогаем с маршрутом, а не с диагнозом</h3><p>Бот не ставит диагноз и не заменяет врача.</p></div>
        <Button icon="clipboard" className="wide" onClick={onStart}>{surveyInProgress ? 'Продолжить опрос' : 'Начать опрос'}</Button>
        {onChat && <Button icon="chat" variant="secondary" className="wide chat-start" disabled={chatBlocked} onClick={onChat}>Начать чат с МедВедом</Button>}
        {surveyInProgress && <p className="field-hint chat-start-hint">Чат станет доступен после завершения или удаления опроса.</p>}
        <p className="survey-note">Пять шагов — от жалобы до результата.</p>
      </Card>
      <Card className="privacy-note"><Icon name="shield" className="privacy-symbol" /><div><h2>Без личных данных</h2><p>Для опроса не нужны имя, телефон или медицинские документы.</p></div></Card>
    </div>
  </div>
}
