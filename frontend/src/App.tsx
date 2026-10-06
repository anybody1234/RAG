import { useEffect, useState } from 'react'

type Health =
  | { state: 'loading' }
  | { state: 'ok'; configVersion: string }
  | { state: 'error'; message: string }

function App() {
  const [health, setHealth] = useState<Health>({ state: 'loading' })

  useEffect(() => {
    fetch('/api/health/live')
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json() as Promise<{ config_version: string }>
      })
      .then((body) => setHealth({ state: 'ok', configVersion: body.config_version }))
      .catch((error: Error) => setHealth({ state: 'error', message: error.message }))
  }, [])

  return (
    <main className="app">
      <h1>RAG Chatbot</h1>
      <p>Hỏi đáp văn bản pháp luật Việt Nam và tài liệu tiếng Anh, có trích dẫn nguồn.</p>
      <p className={`status status-${health.state}`}>
        {health.state === 'loading' && 'Đang kết nối backend…'}
        {health.state === 'ok' && `Backend đang chạy · config ${health.configVersion}`}
        {health.state === 'error' && `Không kết nối được backend (${health.message})`}
      </p>
    </main>
  )
}

export default App
