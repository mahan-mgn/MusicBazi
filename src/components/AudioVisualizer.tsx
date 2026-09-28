import { useEffect, useRef } from 'react'
import { engine } from '../lib/audioEngine'

interface AudioVisualizerProps {
  playing: boolean
  tint?: [number, number, number] | null
  className?: string
  barCount?: number
}

/**
 * ویژوالایزر فرکانسی بلادرنگ با رندرینگ بهینه ۶۰ فریم روی بوم Canvas.
 * فرکانس‌ها را به صورت لگاریتمی دسته‌بندی می‌کند تا بیس، وکال و سازها به شکل متوازن جلوه کنند.
 */
export default function AudioVisualizer({
  playing,
  tint,
  className = 'w-full h-8',
  barCount = 32,
}: AudioVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const smoothedRef = useRef<Float32Array>(new Float32Array(barCount))
  const animIdRef = useRef<number | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.max(1, Math.round(rect.width * dpr))
      canvas.height = Math.max(1, Math.round(rect.height * dpr))
    }
    resize()
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null
    observer?.observe(canvas)

    const smoothed = smoothedRef.current
    const rawData = new Uint8Array(128)

    // بررسی تنظیمات کاهش حرکت در سیستم‌عامل
    const prefersReducedMotion =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches

    let active = true

    const render = () => {
      if (!active) return

      const width = canvas.clientWidth
      const height = canvas.clientHeight
      const dpr = window.devicePixelRatio || 1

      ctx.save()
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, width, height)

      const hasFreq = playing && !prefersReducedMotion && engine.getFrequencyData(rawData) !== null

      const totalBars = barCount
      const gap = 2
      const barWidth = Math.max(2, (width - (totalBars - 1) * gap) / totalBars)

      // پالت گرادیان ستون‌ها بر اساس رنگ کاور
      const r = tint ? tint[0] : 132
      const g = tint ? tint[1] : 204
      const b = tint ? tint[2] : 22

      for (let i = 0; i < totalBars; i++) {
        let targetVal = 0

        if (hasFreq) {
          // نگاشت لگاریتمی به بازه فرکانس‌ها
          const p = i / totalBars
          const binStart = Math.floor(Math.pow(p, 1.8) * 64)
          const binEnd = Math.max(binStart + 1, Math.floor(Math.pow((i + 1) / totalBars, 1.8) * 64))

          let sum = 0
          let count = 0
          for (let bIdx = binStart; bIdx < binEnd && bIdx < rawData.length; bIdx++) {
            sum += rawData[bIdx]
            count++
          }
          targetVal = count > 0 ? (sum / (count * 255)) : 0
        }

        // اینرسی فیزیکی: پرش سریع به اوج، افت تدریجی نرم
        if (targetVal > smoothed[i]) {
          smoothed[i] += (targetVal - smoothed[i]) * 0.45
        } else {
          smoothed[i] *= 0.88
        }

        const barHeight = Math.max(2, smoothed[i] * (height - 4))
        const x = i * (barWidth + gap)
        const y = (height - barHeight) / 2

        // رنگ گرادیان با شفافیت هماهنگ
        const alpha = Math.min(0.9, Math.max(0.35, smoothed[i] * 1.1))
        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`
        ctx.beginPath()
        ctx.roundRect(x, y, barWidth, barHeight, barWidth / 2)
        ctx.fill()
      }

      ctx.restore()
      animIdRef.current = requestAnimationFrame(render)
    }

    render()

    return () => {
      active = false
      observer?.disconnect()
      if (animIdRef.current) cancelAnimationFrame(animIdRef.current)
    }
  }, [playing, tint, barCount])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={`${className} pointer-events-none transition-opacity duration-500 ${
        playing ? 'opacity-90' : 'opacity-40'
      }`}
    />
  )
}
