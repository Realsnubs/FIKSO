import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { applyLanguage, storedLanguage } from './i18n/language'
import { registerServiceWorker } from './pwa/register'

// The stored language (Latvian by default) before the first render.
applyLanguage(storedLanguage())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

registerServiceWorker()
