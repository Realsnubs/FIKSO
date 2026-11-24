// Dates as the UI shows them: timestamps in Riga time in the chosen language's locale, calendar dates as they are.
import { currentLocale } from './language'

type Style = 'dateTime' | 'date' | 'timestamp'
const OPTIONS: Record<Style, Intl.DateTimeFormatOptions> = {
  dateTime: { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Riga' },
  date: { dateStyle: 'medium', timeZone: 'Europe/Riga' },
  timestamp: { dateStyle: 'short', timeStyle: 'medium', timeZone: 'Europe/Riga' },
}
const cache = new Map<string, Intl.DateTimeFormat>()

function formatter(style: Style): Intl.DateTimeFormat {
  const key = `${currentLocale()}:${style}`
  let found = cache.get(key)
  if (!found) {
    found = new Intl.DateTimeFormat(currentLocale(), OPTIONS[style])
    cache.set(key, found)
  }
  return found
}

/** A timestamp shown in Riga time (ARCHITECTURE: stored UTC, displayed in Europe/Riga). */
export function rigaDateTime(value: string): string {
  return formatter('dateTime').format(new Date(value))
}

export function rigaDate(value: string): string {
  return formatter('date').format(new Date(value))
}

/** With seconds: the moment a snapshot (e.g. an impact preview) was computed. */
export function rigaTimestamp(value: string): string {
  return formatter('timestamp').format(new Date(value))
}

/** A calendar date (YYYY-MM-DD) shown as is — it has no time and no time zone to convert. */
export function calendarDate(value: string): string {
  const [year, month, day] = value.split('-')
  return `${day}.${month}.${year}`
}

/** Today's calendar date in Riga (YYYY-MM-DD) — the business day, which differs from UTC after midnight. */
export function rigaToday(now: Date = new Date()): string {
  // en-CA formats as YYYY-MM-DD.
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Riga', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
}

/** Catalogue descriptions are stored as sentence fragments ("izlietņu uzstādīšana, …"); shown capitalised. */
export function sentence(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}
