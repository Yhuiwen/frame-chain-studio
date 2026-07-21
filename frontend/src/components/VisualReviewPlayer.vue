<script setup lang="ts">
import { computed, ref } from "vue";

export interface TimelineMarker {
  seconds: number;
  label: string;
  kind: "boundary" | "candidate" | "confirmed" | "note";
}

const props = defineProps<{ src: string; markers: TimelineMarker[]; fps?: number }>();
const video = ref<HTMLVideoElement | null>(null);
const current = ref(0);
const duration = ref(0);
const speed = ref(1);
const markerPositions = computed(() => props.markers.map((marker) => ({
  ...marker, left: `${Math.min(100, Math.max(0, marker.seconds / Math.max(duration.value, 0.001) * 100))}%`,
})));

function seek(seconds: number) {
  if (video.value) video.value.currentTime = Math.max(0, Math.min(duration.value, seconds));
}
function step(direction: number) { seek(current.value + direction / (props.fps || 24)); }
function changeSpeed() { if (video.value) video.value.playbackRate = speed.value; }
</script>

<template>
  <section class="review-player" data-testid="visual-player">
    <video ref="video" :src="src" controls preload="metadata"
      @loadedmetadata="duration = video?.duration || 0" @timeupdate="current = video?.currentTime || 0" />
    <div class="player-controls">
      <el-button size="small" @click="seek(0)">首帧</el-button>
      <el-button size="small" @click="step(-1)">上一帧</el-button>
      <el-button size="small" @click="step(1)">下一帧</el-button>
      <el-button size="small" @click="seek(duration)">尾帧</el-button>
      <el-select v-model="speed" size="small" style="width: 90px" @change="changeSpeed">
        <el-option v-for="item in [0.25, 0.5, 1, 2]" :key="item" :label="`${item}×`" :value="item" />
      </el-select>
      <span>{{ current.toFixed(3) }} / {{ duration.toFixed(3) }} 秒</span>
    </div>
    <div class="review-timeline" aria-label="异常时间轴">
      <button v-for="marker in markerPositions" :key="`${marker.kind}-${marker.seconds}`"
        class="timeline-marker" :class="marker.kind" :style="{ left: marker.left }"
        :title="`${marker.label} ${marker.seconds.toFixed(3)}s`" @click="seek(marker.seconds)" />
    </div>
    <div class="marker-legend"><span>蓝色：正式 Shot 边界</span><span>橙色：自动候选</span><span>红色：确认异常</span></div>
  </section>
</template>

<style scoped>
.review-player video{width:100%;max-height:430px;background:#111;border-radius:8px}.player-controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px}.review-timeline{height:18px;background:#e5e7eb;border-radius:9px;position:relative;margin-top:14px}.timeline-marker{position:absolute;top:-4px;width:10px;height:26px;border:0;border-radius:4px;transform:translateX(-5px);cursor:pointer}.boundary{background:#2563eb}.candidate{background:#f59e0b}.confirmed{background:#dc2626}.note{background:#7c3aed}.marker-legend{display:flex;gap:14px;font-size:12px;color:#667085;margin-top:6px}
</style>
