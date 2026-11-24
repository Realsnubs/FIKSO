import { useId, useState } from 'react'
import { useLanguage } from '../i18n/LanguageContext'
import { t } from '../i18n/lv'
import type { CityApi, CommunicationLanguageApi } from '../types/work'
import { cityName, languageName, matches, usePlaces } from './placesData'

const tp = t.app.places

interface CityPickerProps {
  id: string
  label: string
  hint?: string
  cities: CityApi[]
  value: string
  onChange: (code: string) => void
  invalid?: boolean
  /** The surrounding section already shows the same heading: keep the legend for screen readers only. */
  hideLegend?: boolean
}

/** One city from a searchable list: a search box filtering a radio group (keyboard and screen-reader friendly). */
export function CityPicker({ id, label, hint, cities, value, onChange, invalid, hideLegend }: CityPickerProps) {
  const { language } = useLanguage()
  const [query, setQuery] = useState('')
  const shown = cities.filter((c) => c.code === value || matches(query, c.name.lv, c.name.en, c.name.ru, c.code))
  const selected = cities.find((c) => c.code === value)
  return (
    <fieldset className="field pick" aria-invalid={invalid || undefined} aria-describedby={hint ? `${id}-hint` : undefined}>
      <legend className={hideLegend ? 'sr-only' : undefined}>{label}</legend>
      {hint && (
        <small id={`${id}-hint`} className="hint">
          {hint}
        </small>
      )}
      <p className="pick-current" aria-live="polite">
        {selected ? tp.citySelected(cityName(selected, language)) : tp.cityNotSet}
      </p>
      <input
        id={`${id}-search`}
        type="search"
        aria-label={tp.citySearch}
        placeholder={tp.citySearch}
        autoComplete="off"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="pick-list" role="radiogroup" aria-label={label}>
        {shown.map((c) => (
          <label key={c.code} className={c.code === value ? 'on' : undefined}>
            <input type="radio" name={id} value={c.code} checked={c.code === value} onChange={() => onChange(c.code)} />
            {cityName(c, language)}
          </label>
        ))}
        {shown.length === 0 && <p className="muted">{tp.cityNone}</p>}
      </div>
    </fieldset>
  )
}

interface LanguagePickerProps {
  id: string
  languages: CommunicationLanguageApi[]
  value: string[]
  onChange: (codes: string[]) => void
  hideLegend?: boolean
}

/** Several communication languages: selected ones as removable chips, the rest in a searchable checkbox list. */
export function LanguagePicker({ id, languages, value, onChange, hideLegend }: LanguagePickerProps) {
  const { language } = useLanguage()
  const [query, setQuery] = useState('')
  const hintId = useId()
  const toggle = (code: string) => onChange(value.includes(code) ? value.filter((c) => c !== code) : [...value, code])
  const shown = languages.filter((l) => matches(query, l.name.lv, l.name.en, l.name.ru, l.native_name, l.code))
  return (
    <fieldset className="field pick" aria-describedby={hintId}>
      <legend className={hideLegend ? 'sr-only' : undefined}>{tp.languages}</legend>
      <small id={hintId} className="hint">
        {tp.languagesHint}
      </small>
      <p className="pick-current" aria-live="polite">
        {tp.languagesSelected(value.length)}
      </p>
      {value.length > 0 && (
        <ul className="plain pick-chips">
          {value.map((code) => (
            <li key={code}>
              <button type="button" aria-label={tp.remove(languageName(code, languages, language))} onClick={() => toggle(code)}>
                {languageName(code, languages, language)} <span aria-hidden="true">×</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <input
        id={`${id}-search`}
        type="search"
        aria-label={tp.languageSearch}
        placeholder={tp.languageSearch}
        autoComplete="off"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="pick-list" role="group" aria-label={tp.languages}>
        {shown.map((l) => (
          <label key={l.code} className={value.includes(l.code) ? 'on' : undefined}>
            <input type="checkbox" checked={value.includes(l.code)} onChange={() => toggle(l.code)} />
            <span aria-hidden="true">{l.flag ?? ''}</span>
            <span>
              {l.name[language] ?? l.name.lv}
              {l.native_name !== l.name[language] && <span className="muted"> · {l.native_name}</span>}
            </span>
          </label>
        ))}
        {shown.length === 0 && <p className="muted">{tp.languageNone}</p>}
      </div>
    </fieldset>
  )
}

/** City and communication language as two rows of a summary list (`<dl>`). */
export function PlaceFacts({ city, communicationLanguage }: { city: CityApi | null; communicationLanguage: string }) {
  const { language } = useLanguage()
  const { languages } = usePlaces()
  return (
    <>
      <dt>{tp.city}</dt>
      <dd>{cityName(city, language)}</dd>
      <dt>{tp.communicationLanguage}</dt>
      <dd>{languageName(communicationLanguage, languages, language)}</dd>
    </>
  )
}
