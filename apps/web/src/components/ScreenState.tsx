import { Button, Card } from './ui'

export function LoadingState() {
  return <Card className="state" aria-busy="true"><span className="loading-mark" aria-hidden="true" /><h1>Готовим приложение</h1><p role="status">Подождите немного…</p></Card>
}

export function ErrorState({ onRetry, missingHost, hostLaunch = false }: { onRetry: () => void; missingHost: boolean; hostLaunch?: boolean }) {
  if (hostLaunch) return <Card className="state" role="alert"><h1>Не удалось подтвердить вход</h1><p>Вернитесь в MAX и снова откройте приложение кнопкой. Если ошибка повторяется, попробуйте позже.</p></Card>
  return <Card className="state" role="alert"><span className="state-symbol" aria-hidden="true">!</span><h1>{missingHost ? 'Запуск пока недоступен' : 'Не удалось открыть приложение'}</h1><p>{missingHost ? 'Откройте приложение через подключённый сервис MAX. Для просмотра в браузере доступна отдельная демоверсия.' : 'Произошёл временный сбой. Попробуйте ещё раз.'}</p>{!missingHost && <Button onClick={onRetry}>Попробовать снова</Button>}</Card>
}
