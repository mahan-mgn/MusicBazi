/**
 * Glass rendering for the floating navigation capsule matching BitChord.
 *
 * BitChord uses a backdrop refraction shader with 7-band chromatic dispersion,
 * 8dp blur, 24dp biconvex lens refraction, 45-degree specular highlight, and
 * 24dp soft drop shadow for its floating navigation bar, with CSS glass as the
 * high-performance universal fallback.
 */
import type { LiquidGlass as LiquidGlassInstance } from '@ybouane/liquidglass'
import { useSettings } from '../store/settings'

let instance: LiquidGlassInstance | null = null
let pendingRoot: HTMLElement | null = null

export async function mountLiquidGlass(root: HTMLElement): Promise<void> {
  if (!root || typeof WebGLRenderingContext === 'undefined') return

  // Respect user preference in settings (or reduce dynamic blur fallback)
  if (!useSettings.getState().liquidGlass) {
    unmountLiquidGlass()
    return
  }

  // The WebGL library strictly requires targets to be direct children of the capture root
  const targets = Array.from(root.children).filter(
    (child): child is HTMLElement => child instanceof HTMLElement && child.hasAttribute('data-lg'),
  )
  if (!targets.length) return

  instance?.destroy()
  instance = null
  pendingRoot = root

  try {
    const { LiquidGlass } = await import('@ybouane/liquidglass')
    if (pendingRoot !== root || !useSettings.getState().liquidGlass) return

    for (const target of targets) {
      target.dataset.config = JSON.stringify({
        blurAmount: 0.25,
        refraction: 0.5,
        chromAberration: 0.05,
        edgeHighlight: 0.1,
        specular: 0.2,
        fresnel: 1.0,
        cornerRadius: Number(target.dataset.lgRadius) || 28,
        zRadius: 24,
        opacity: 1.0,
        saturation: 0.5,
        tintStrength: 0.0,
        shadowOpacity: 0.1,
        shadowSpread: 24,
        shadowOffsetY: 4,
        bevelMode: 0,
      })
    }

    instance = await LiquidGlass.init({ root, glassElements: targets })
    if (pendingRoot !== root || !useSettings.getState().liquidGlass) {
      instance.destroy()
      instance = null
    }
  } catch {
    // WebGL, SVG foreignObject capture, and some WebViews are not available everywhere.
    // The CSS backdrop blur and glass tokens remain the complete, performant fallback.
    instance?.destroy()
    instance = null
    for (const target of targets) delete target.dataset.config
  }
}

export function unmountLiquidGlass(): void {
  pendingRoot = null
  instance?.destroy()
  instance = null
}

// React to Liquid Glass setting toggles dynamically
if (typeof window !== 'undefined') {
  useSettings.subscribe((state, prevState) => {
    if (state.liquidGlass !== prevState.liquidGlass) {
      if (state.liquidGlass && pendingRoot) {
        void mountLiquidGlass(pendingRoot)
      } else {
        unmountLiquidGlass()
      }
    }
  })
}
