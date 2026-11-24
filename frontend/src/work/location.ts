import { useEffect, useRef, useState } from 'react'
import { workApi } from '../api/work'

/**
 * Shares the master's position about every 3 minutes, only while `enabled` (mode "available now") and while the
 * page is open (approved location model). Only the latest point is kept by the backend; nothing is stored here.
 */
export function useLocationSharing(enabled: boolean, intervalSeconds: number, onSent: () => void) {
  const [denied, setDenied] = useState(false)
  const sentRef = useRef(onSent)
  useEffect(() => {
    sentRef.current = onSent
  })
  useEffect(() => {
    if (!enabled || !('geolocation' in navigator)) return
    const send = () =>
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setDenied(false)
          workApi.sendLocation(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy).then(() => sentRef.current(), () => undefined)
        },
        () => setDenied(true),
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 },
      )
    send()
    const timer = window.setInterval(send, Math.max(60, intervalSeconds) * 1000)
    return () => window.clearInterval(timer)
  }, [enabled, intervalSeconds])
  return { denied }
}
