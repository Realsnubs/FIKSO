import { t } from '../i18n/lv'
import { LANGUAGES } from '../i18n/language'
import { useLanguage } from '../i18n/LanguageContext'

/** LV / EN / RU in the header. Each language is named in itself, so anyone can find their own. */
export function LanguageSwitcher() {
  const { language, setLanguage } = useLanguage()
  return (
    <div className="lang-switch" role="group" aria-label={t.language.label}>
      {LANGUAGES.map(({ code, name }) => (
        <button
          key={code}
          type="button"
          lang={code}
          aria-label={name}
          title={name}
          aria-pressed={language === code}
          onClick={() => setLanguage(code)}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  )
}
