// ── Cancellation guard for long-running loops ─────────────────────────────────
// start()       -> begins a run, returns an AbortSignal for fetch/callLLM
// stop()        -> requests cancellation (loop checks isCancelled() between items)
// isCancelled() -> true after stop() or after the component unmounts
import { useRef, useEffect, useCallback } from "react";

export function useRunGuard() {
  const cancelled = useRef(false);
  const ctrl      = useRef(null);

  useEffect(() => {
    // StrictMode mounts twice in dev; reset the flag on (re)mount.
    cancelled.current = false;
    return () => { cancelled.current = true; ctrl.current?.abort(); };
  }, []);

  const start = useCallback(() => {
    ctrl.current?.abort();
    cancelled.current = false;
    ctrl.current = new AbortController();
    return ctrl.current.signal;
  }, []);

  const stop = useCallback(() => {
    cancelled.current = true;
    ctrl.current?.abort();
  }, []);

  const isCancelled = useCallback(() => cancelled.current, []);

  return { start, stop, isCancelled };
}
