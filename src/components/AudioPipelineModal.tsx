/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

import { useEffect, useState } from 'react'
import { getNativeAudioDiagnostics, type AudioDiagnostics } from '../lib/native'
import { isNativeApp } from '../lib/server'
import { useI18n } from '../lib/i18n'
import { useSettings } from '../store/settings'

interface Props {
  open: boolean
  onClose: () => void
}

export default function AudioPipelineModal({ open, onClose }: Props) {
  const { lang } = useI18n()
  const { spatialAudio, eq, normalize, setSpatialAudio } = useSettings()
  const [diag, setDiag] = useState<AudioDiagnostics | null>(null)

  useEffect(() => {
    if (!open || !isNativeApp()) return
    let active = true

    const fetchDiag = async () => {
      const data = await getNativeAudioDiagnostics()
      if (active) setDiag(data)
    }

    void fetchDiag()
    const timer = setInterval(fetchDiag, 1000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [open])

  if (!open) return null

  const isFa = lang === 'fa'
  const isBitPerfect = diag?.outputExact && eq === 'off' && !spatialAudio

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-line bg-panel p-5 shadow-2xl space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line pb-3">
          <h2 className="text-sm font-semibold tracking-wide text-fg">
            {isFa ? 'مسیر و وضعیت پردازش صوتی (Audio Pipeline)' : 'Audio Pipeline Diagnostics'}
          </h2>
          <button
            onClick={onClose}
            className="text-xs text-muted hover:text-fg rounded-md p-1"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Status Badges */}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span
            className={`rounded-full px-2.5 py-0.5 font-medium ${
              isBitPerfect
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                : 'bg-zinc-800 text-zinc-400 border border-zinc-700'
            }`}
          >
            Bit-Perfect: {isBitPerfect ? 'TRUE' : 'FALSE'}
          </span>

          <span
            className={`rounded-full px-2.5 py-0.5 font-medium ${
              diag?.directPlaybackActual
                ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                : 'bg-zinc-800 text-zinc-400 border border-zinc-700'
            }`}
          >
            Direct: {diag?.directPlaybackActual ? 'ACTIVE' : 'AUDIO_TRACK'}
          </span>

          <span className="rounded-full bg-zinc-800 px-2.5 py-0.5 font-medium text-zinc-300 border border-zinc-700">
            DSP: {diag?.dspFormat ?? 'Float32'}
          </span>
        </div>

        {/* Diagnostics Sections */}
        <div className="space-y-3 text-xs divide-y divide-line-soft">
          {/* Decoder Section */}
          <div className="pt-2">
            <span className="text-[11px] font-semibold text-muted uppercase tracking-wider">
              {isFa ? 'دیکودر (Decoder)' : 'Decoder'}
            </span>
            <div className="mt-1 flex justify-between text-muted-2">
              <span>{isFa ? 'فرمت خروجی دیکودر' : 'Decoder Output'}</span>
              <span className="font-mono text-fg">{diag?.decoderOutputEncoding ?? 'Float32 PCM'}</span>
            </div>
            {diag?.actualSampleRateHz && (
              <div className="flex justify-between text-muted-2">
                <span>{isFa ? 'نرخ نمونه‌برداری' : 'Sample Rate'}</span>
                <span className="font-mono text-fg">{diag.actualSampleRateHz} Hz</span>
              </div>
            )}
          </div>

          {/* DSP Chain Section */}
          <div className="pt-2">
            <span className="text-[11px] font-semibold text-muted uppercase tracking-wider">
              {isFa ? 'زنجیره پردازش (Float32 DSP Chain)' : 'DSP Chain'}
            </span>
            <div className="mt-1 space-y-1">
              <div className="flex justify-between text-muted-2">
                <span>{isFa ? 'اکولایزر (Parametric SVF)' : 'Equalizer'}</span>
                <span className={`font-mono ${eq !== 'off' ? 'text-accent font-medium' : 'text-zinc-500'}`}>
                  {eq !== 'off' ? `ON (${eq})` : 'BYPASS'}
                </span>
              </div>
              <div className="flex items-center justify-between text-muted-2">
                <span>{isFa ? 'صدای فراگیر (Spatial Audio)' : 'Spatial Audio'}</span>
                <button
                  onClick={() => setSpatialAudio(!spatialAudio)}
                  className={`text-[11px] font-mono px-2 py-0.5 rounded border transition ${
                    spatialAudio
                      ? 'border-accent bg-accent/20 text-accent'
                      : 'border-line text-zinc-500 hover:text-zinc-300'
                  }`}
                >
                  {spatialAudio ? 'ON (Widener + Crossfeed)' : 'OFF'}
                </button>
              </div>
              <div className="flex justify-between text-muted-2">
                <span>{isFa ? 'هم‌ترازی بلندی (Loudness EBU R128)' : 'Loudness'}</span>
                <span className={`font-mono ${normalize ? 'text-fg' : 'text-zinc-500'}`}>
                  {normalize
                    ? diag?.loudnessGainDb != null
                      ? `${diag.loudnessGainDb > 0 ? '+' : ''}${diag.loudnessGainDb.toFixed(1)} dB`
                      : 'ACTIVE'
                    : 'OFF'}
                </span>
              </div>
            </div>
          </div>

          {/* Output Route Section */}
          <div className="pt-2">
            <span className="text-[11px] font-semibold text-muted uppercase tracking-wider">
              {isFa ? 'خروجی و مسیر سخت‌افزار (Output Route)' : 'Output Route'}
            </span>
            <div className="mt-1 space-y-1">
              <div className="flex justify-between text-muted-2">
                <span>{isFa ? 'دستگاه فعال' : 'Active Device'}</span>
                <span className="font-mono text-fg">{diag?.deviceName || 'Built-in Audio'}</span>
              </div>
              <div className="flex justify-between text-muted-2">
                <span>{isFa ? 'نوع مسیر' : 'Route Kind'}</span>
                <span className="font-mono text-fg">{diag?.routeKind || 'PHONE'}</span>
              </div>
              {diag?.bluetoothCodec && (
                <div className="flex justify-between text-muted-2">
                  <span>{isFa ? 'کدک بلوتوث' : 'Bluetooth Codec'}</span>
                  <span className="font-mono text-accent">{diag.bluetoothCodec}</span>
                </div>
              )}
              {diag?.usbProductName && (
                <div className="flex justify-between text-muted-2">
                  <span>{isFa ? 'دک USB' : 'USB DAC'}</span>
                  <span className="font-mono text-emerald-400">
                    {diag.usbProductName} {diag.usbUacVersion ? `(UAC${diag.usbUacVersion})` : ''}
                  </span>
                </div>
              )}
              {diag?.outputExactDetail && (
                <div className="flex justify-between text-muted-2 text-[11px]">
                  <span>{isFa ? 'تطابق نمونه' : 'Exactness Note'}</span>
                  <span className="font-mono text-zinc-400">{diag.outputExactDetail}</span>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="pt-2 text-end">
          <button
            onClick={onClose}
            className="rounded-lg bg-zinc-800 px-4 py-1.5 text-xs font-medium text-fg hover:bg-zinc-700 transition"
          >
            {isFa ? 'بستن' : 'Close'}
          </button>
        </div>
      </div>
    </div>
  )
}
