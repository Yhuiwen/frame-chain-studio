import { ElMessage } from "element-plus";
import { onBeforeUnmount, ref } from "vue";

import { useStudioStore } from "@/stores/studio";

const BASE_INTERVAL_MS = 1800;
const HIDDEN_INTERVAL_MS = 5000;
const MAX_FAILURES = 3;

export function useProjectPolling() {
  const store = useStudioStore();
  const timerId = ref<number | null>(null);
  const inFlight = ref(false);
  const failureCount = ref(0);

  function stopPolling() {
    if (timerId.value !== null) {
      window.clearTimeout(timerId.value);
      timerId.value = null;
    }
  }

  function scheduleNext() {
    if (!store.hasActiveTasks || failureCount.value >= MAX_FAILURES || timerId.value !== null) return;
    const delay = document.visibilityState === "hidden" ? HIDDEN_INTERVAL_MS : BASE_INTERVAL_MS;
    timerId.value = window.setTimeout(() => {
      timerId.value = null;
      void tick();
    }, delay);
  }

  async function tick() {
    if (inFlight.value) {
      scheduleNext();
      return;
    }
    inFlight.value = true;
    try {
      await store.refreshProjectDetail();
      failureCount.value = 0;
    } catch (error) {
      failureCount.value += 1;
      ElMessage.warning(error instanceof Error ? error.message : "Project refresh failed.");
    } finally {
      inFlight.value = false;
      if (store.hasActiveTasks && failureCount.value < MAX_FAILURES) {
        scheduleNext();
      } else {
        stopPolling();
      }
    }
  }

  function startPolling() {
    if (timerId.value !== null || inFlight.value) return;
    scheduleNext();
  }

  function handleVisibilityChange() {
    if (document.visibilityState === "visible") {
      stopPolling();
      void tick();
    }
  }

  document.addEventListener("visibilitychange", handleVisibilityChange);
  onBeforeUnmount(() => {
    stopPolling();
    document.removeEventListener("visibilitychange", handleVisibilityChange);
  });

  return {
    startPolling,
    stopPolling,
    tick,
    failureCount,
  };
}
