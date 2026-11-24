import { t } from '../i18n/lv'

export function duration(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  return minutes >= 60 ? t.app.hoursMinutes(Math.floor(minutes / 60), minutes % 60) : t.app.minutes(minutes)
}
