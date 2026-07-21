<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";

defineProps<{ leftUrl: string; rightUrl: string; leftLabel: string; rightLabel: string }>();
const mode = ref<"side" | "overlay" | "slider" | "blink" | "difference" | "edges">("side");
const opacity = ref(50);
const blinkLeft = ref(true);
let timer: ReturnType<typeof setInterval> | null = null;
const rightStyle = computed(() => mode.value === "slider"
  ? { clipPath: `inset(0 0 0 ${opacity.value}%)` }
  : { opacity: mode.value === "overlay" ? opacity.value / 100 : 1 });
function setMode(value: typeof mode.value) {
  mode.value = value;
  if (timer) { clearInterval(timer); timer = null; }
  if (value === "blink") timer = setInterval(() => { blinkLeft.value = !blinkLeft.value; }, 800);
}
onBeforeUnmount(() => { if (timer) clearInterval(timer); });
</script>

<template>
  <section class="frame-comparison" data-testid="frame-comparison">
    <div class="comparison-toolbar">
      <el-radio-group :model-value="mode" size="small" @change="setMode($event as typeof mode)">
        <el-radio-button value="side">并排</el-radio-button><el-radio-button value="overlay">叠加</el-radio-button>
        <el-radio-button value="slider">滑块</el-radio-button><el-radio-button value="blink">闪烁</el-radio-button>
        <el-radio-button value="difference">差异图</el-radio-button><el-radio-button value="edges">灰度边缘</el-radio-button>
      </el-radio-group>
      <el-slider v-if="mode === 'overlay' || mode === 'slider'" v-model="opacity" :min="5" :max="95" />
    </div>
    <div class="compare-stage" :class="mode">
      <figure v-show="mode !== 'blink' || blinkLeft"><img :src="leftUrl" :alt="leftLabel"/><figcaption>{{ leftLabel }}</figcaption></figure>
      <figure v-show="mode !== 'blink' || !blinkLeft" :style="rightStyle"><img :src="rightUrl" :alt="rightLabel"/><figcaption>{{ rightLabel }}</figcaption></figure>
    </div>
    <p class="comfort-note">闪烁默认关闭，启用后频率限制为 1.25 Hz。</p>
  </section>
</template>

<style scoped>
.comparison-toolbar{display:flex;gap:18px;align-items:center;flex-wrap:wrap}.comparison-toolbar .el-slider{width:180px}.compare-stage{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px;position:relative;min-height:220px}.compare-stage figure{margin:0;min-width:0}.compare-stage img{width:100%;height:240px;object-fit:contain;background:#111;border-radius:6px}.compare-stage figcaption{font-size:12px;color:#667085;margin-top:4px}.compare-stage.overlay,.compare-stage.slider,.compare-stage.difference,.compare-stage.edges,.compare-stage.blink{display:block}.compare-stage.overlay figure,.compare-stage.slider figure,.compare-stage.difference figure,.compare-stage.edges figure,.compare-stage.blink figure{position:absolute;inset:0}.compare-stage.difference figure:last-child{mix-blend-mode:difference}.compare-stage.edges img{filter:grayscale(1) contrast(3)}.comfort-note{font-size:12px}
</style>
