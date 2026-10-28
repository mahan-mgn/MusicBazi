/*
 * گزارش یکپارچهٔ خط پردازش صوتی (Audio Pipeline Diagnostics) برای وب و اندروید
 */

import type { AudioDiagnostics } from '../native'
import { getNativeAudioDiagnostics } from '../native'
import { isNativeApp } from '../server'
import { engine } from '../audioEngine'

export async function getUnifiedAudioDiagnostics(): Promise<AudioDiagnostics | null> {
  if (isNativeApp()) {
    return await getNativeAudioDiagnostics()
  }
  return engine.getDiagnostics()
}
