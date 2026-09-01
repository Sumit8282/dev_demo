import { useEffect, useRef } from 'react';
import {
  getReleaseApi,
  TERMINAL_WORKFLOW_STATUSES,
  type BackendReleaseState,
} from '../api/releases';

const POLL_INTERVAL_MS = 2500;

export function useReleasePolling(
  releaseId: string | undefined,
  onUpdate: (state: BackendReleaseState) => void,
  enabled = true
) {
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  useEffect(() => {
    if (!releaseId || !enabled) return;

    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const state = await getReleaseApi(releaseId);
        if (cancelled) return;

        onUpdateRef.current(state);

        if (!TERMINAL_WORKFLOW_STATUSES.has(state.workflow_status)) {
          timeoutId = setTimeout(poll, POLL_INTERVAL_MS);
        }
      } catch {
        if (!cancelled) {
          timeoutId = setTimeout(poll, POLL_INTERVAL_MS * 2);
        }
      }
    };

    poll();

    return () => {
      cancelled = true;
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [releaseId, enabled]);
}
