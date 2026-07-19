import { ElMessage } from "element-plus";
import { onBeforeUnmount, ref } from "vue";

import { useStudioStore } from "@/stores/studio";

const BASE_INTERVAL_MS = 1800;
const HIDDEN_INTERVAL_MS = 5000;
const MAX_RETRY_INTERVAL_MS = 30_000;

export function useProjectPolling() {
  const store = useStudioStore();
  const timerId = ref<number | null>(null);
  const inFlight = ref(false);
  const failureCount = ref(0);
  const tickCount = ref(0);
  const manuallyStopped = ref(false);
  const outageNotified = ref(false);

  function stopPolling() {
    manuallyStopped.value = true;
    if (timerId.value !== null) {
      window.clearTimeout(timerId.value);
      timerId.value = null;
    }
  }

  function clearTimer() {
    if (timerId.value !== null) {
      window.clearTimeout(timerId.value);
      timerId.value = null;
    }
  }

  function scheduleNext() {
    if (manuallyStopped.value || !store.hasActiveTasks || timerId.value !== null) return;
    const retryDelay =
      failureCount.value > 0
        ? Math.min(2_000 * 2 ** Math.max(failureCount.value - 1, 0), MAX_RETRY_INTERVAL_MS)
        : BASE_INTERVAL_MS;
    const delay = document.visibilityState === "hidden" ? Math.max(HIDDEN_INTERVAL_MS, retryDelay) : retryDelay;
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
      tickCount.value += 1;
      await store.refreshProjectDetail();
      if (tickCount.value % 2 === 1) {
        await store.refreshWorkers();
      }
      if (failureCount.value > 0 && outageNotified.value) {
        ElMessage.success("连接已恢复");
      }
      failureCount.value = 0;
      outageNotified.value = false;
    } catch (error) {
      failureCount.value += 1;
      if (!outageNotified.value) {
        outageNotified.value = true;
        ElMessage.warning("连接中断，正在重试");
      }
    } finally {
      inFlight.value = false;
      if (store.hasActiveTasks) {
        scheduleNext();
      } else {
        clearTimer();
      }
    }
  }

  function startPolling() {
    manuallyStopped.value = false;
    if (timerId.value !== null || inFlight.value) return;
    scheduleNext();
  }

  function handleVisibilityChange() {
    if (document.visibilityState === "visible") {
      clearTimer();
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
