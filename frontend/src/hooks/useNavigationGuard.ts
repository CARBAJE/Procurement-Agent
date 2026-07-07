"use client"

import { useEffect, useRef, useState } from "react"

/**
 * Intercepts navigation away from the current page and shows a confirmation
 * modal. Handles:
 *  - Browser back/forward button (popstate)
 *  - Tab/window close or refresh (beforeunload)
 *  - In-app <Link> clicks (DOM capture phase listener on <a> elements)
 *
 * @param enabled   When false, all interception is removed immediately.
 * @param onConfirmLeave  Called with the intended navigation target when the
 *                        user confirms leaving. Responsible for cancelling the
 *                        request and performing the actual navigation.
 */
export function useNavigationGuard(
  enabled: boolean,
  onConfirmLeave: (target: string) => Promise<void>,
) {
  const [showModal,  setShowModal]  = useState(false)
  const [confirming, setConfirming] = useState(false)

  // Stores the <a href> the user clicked so we can navigate there on confirm.
  // null means the trigger was browser-back (navigate to "/").
  const intendedHref = useRef<string | null>(null)

  // ── Browser back / forward ──────────────────────────────────────────────────
  useEffect(() => {
    if (!enabled) return

    // Push an extra history entry so the first "back" press is interceptable.
    window.history.pushState(null, "", window.location.href)

    const handle = () => {
      // Re-push so subsequent back presses keep triggering this handler.
      window.history.pushState(null, "", window.location.href)
      intendedHref.current = null
      setShowModal(true)
    }

    window.addEventListener("popstate", handle)
    return () => window.removeEventListener("popstate", handle)
  }, [enabled])

  // ── Tab / window close ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!enabled) return

    const handle = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      // Modern browsers show their own generic dialog — we cannot customise it.
      e.returnValue = ""
    }

    window.addEventListener("beforeunload", handle)
    return () => window.removeEventListener("beforeunload", handle)
  }, [enabled])

  // ── In-app <Link> / <a> clicks ──────────────────────────────────────────────
  useEffect(() => {
    if (!enabled) return

    const handle = (e: MouseEvent) => {
      const anchor = (e.target as HTMLElement).closest("a[href]") as HTMLAnchorElement | null
      if (!anchor) return

      const href = anchor.getAttribute("href") ?? ""
      // Let external links, mailto, anchors, and same-page links pass through.
      if (
        !href ||
        href.startsWith("#") ||
        href.startsWith("mailto:") ||
        href.startsWith("http://") ||
        href.startsWith("https://") ||
        href === window.location.pathname
      ) return

      e.preventDefault()
      e.stopPropagation()
      intendedHref.current = href
      setShowModal(true)
    }

    // Capture phase so we intercept before Next.js's router handles the click.
    document.addEventListener("click", handle, true)
    return () => document.removeEventListener("click", handle, true)
  }, [enabled])

  function dismiss() {
    setShowModal(false)
    intendedHref.current = null
  }

  async function confirmLeave() {
    setConfirming(true)
    const target = intendedHref.current ?? "/"
    intendedHref.current = null
    try {
      await onConfirmLeave(target)
    } catch {
      // Cancel API failure is not fatal — still navigate away.
    } finally {
      setConfirming(false)
      setShowModal(false)
    }
  }

  /** Programmatically trigger the leave modal (e.g. from a Cancel button). */
  function trigger(href: string) {
    intendedHref.current = href
    setShowModal(true)
  }

  return { showModal, confirming, dismiss, confirmLeave, trigger }
}
