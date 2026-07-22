const labels: Record<string, string> = {
  DRAFT: "草稿", KEYFRAME_GENERATING: "正在生成关键帧", KEYFRAME_REVIEW: "关键帧待审核",
  KEYFRAME_APPROVED: "关键帧已通过", VIDEO_GENERATING: "正在生成视频", VIDEO_REVIEW: "视频待审核",
  VIDEO_APPROVED: "视频已通过", TAIL_FRAME_LOCKED: "尾帧已锁定", COMPLETED: "已完成",
  PENDING: "等待中", QUEUED: "排队中", SUBMITTING: "正在提交", RUNNING: "进行中",
  RETRY_WAIT: "等待重试", RESULT_READY: "结果已就绪", PROCESSING_RESULT: "正在处理结果",
  SUCCEEDED: "成功", FAILED: "失败", FAILED_BUT_BILLED: "失败但已计费", BLOCKED: "已阻断",
  CANCELLING: "正在取消", CANCELLED: "已取消", PASSED: "通过", WARNING: "需注意",
  ERROR: "错误", INFO: "提示", APPROVED: "已通过", REJECTED: "未通过", NOT_RUN: "未运行",
  UNKNOWN: "未知", NONE: "无", MANUAL: "手动指定", INHERITED: "继承", INCONCLUSIVE: "证据不足",
  ALLOWED: "允许进入生产", ACTIVE: "有效", STALE: "已过期", SUPERSEDED: "已被替代",
  STARTING: "正在启动", IDLE: "空闲", BUSY: "忙碌", STOPPING: "正在停止", STOPPED: "已停止",
  KEYFRAME: "关键帧", VIDEO: "视频", TAIL_FRAME: "尾帧", START_FRAME: "起始帧",
  KEYFRAME_GENERATION: "关键帧生成", VIDEO_GENERATION: "视频生成",
  PROJECT_RENDER: "项目成片", VIDEO_INPUT_FRAME: "视频输入帧", IMAGE: "图片", RENDER: "渲染",
  GENERATION: "生成", RESULT: "结果", TOAPIS_CREDIT: "TOAPIS 积分", USD: "美元",
  ESTIMATE: "预估", PROVIDER_REPORTED: "服务商上报", MANUAL_ADJUSTMENT: "手动调整",
  ESTIMATED: "预估", ACTUAL: "实际", WAIVED: "已豁免", FAKE_PROVIDER: "模拟服务商",
  PRICING_RULE: "价格规则", PROVIDER_RESPONSE: "服务商响应", PROJECT_TOTAL: "项目累计",
  MONTHLY: "每月", ALLOW_WITH_WARNING: "允许并警告", TEXT_TO_IMAGE: "文字生成图片",
  START_FRAME_ONLY: "仅起始帧", FIRST_LAST_FRAME: "首尾帧",
};

const blockers: Record<string, string> = {
  TECHNICAL_NOT_PASSED: "技术验证尚未通过", LINEAGE_NOT_PASSED: "素材血缘检查尚未通过",
  HUMAN_VISUAL_PENDING: "等待人工视觉审核", HUMAN_VISUAL_REJECTED: "人工视觉审核未通过",
  BLOCKING_VISUAL_EVIDENCE: "存在阻断性的视觉证据", UNEXPECTED_SCENE_CUT: "视频内部检测到意外硬切",
  AUTOMATED_VISUAL_CHECK_INCOMPLETE: "必要的自动视觉检查未完成",
  SUBJECT_REFERENCE_NOT_CONFIGURED: "尚未配置主体参考信息",
};

const reviewReasons: Record<string, string> = {
  CHARACTER_STYLE_DRIFT: "角色画风发生漂移", CHARACTER_GEOMETRY_DRIFT: "角色形体发生漂移",
  FACE_IDENTITY_DRIFT: "面部身份特征发生漂移", MATERIAL_COLOR_DRIFT: "材质或颜色发生漂移",
  CAMERA_DISCONTINUITY: "镜头运动不连续", CAMERA_DRIFT: "镜头发生漂移",
  COMPOSITION_DISCONTINUITY: "构图不连续", SUBJECT_POSITION_DRIFT: "主体位置漂移",
  SUBJECT_SCALE_DRIFT: "主体尺度漂移", BACKGROUND_DRIFT: "背景发生漂移", LIGHTING_DRIFT: "光照发生漂移",
  UNEXPECTED_SCENE_CUT: "出现意外场景硬切", INTRA_SHOT_SCENE_CUT: "镜头内部出现场景硬切",
  MOTION_ARTIFACT: "存在运动伪影", DECODE_OR_MEDIA_ISSUE: "视频解码或媒体文件异常",
  ANCHOR_MISMATCH: "起始锚点不匹配", TARGET_KEYFRAME_MISMATCH: "目标关键帧不匹配",
  CROSS_SHOT_SEAM_FAILURE: "镜头衔接不连续", EXTRA_OBJECT: "出现多余物体",
  TEXT_OR_WATERMARK: "出现文字或水印", CHARACTER_DEFORMATION: "角色发生形变", OTHER: "其他",
};

export function statusLabel(value: unknown): string {
  if (!value) return "暂无";
  const code = String(value);
  return labels[code] ?? `未知状态（${code}）`;
}

export function productionBlockerLabel(value: string): string {
  return `${blockers[value] ?? "未知阻断原因"}（${value}）`;
}

export function reviewReasonLabel(value: string): string {
  return `${reviewReasons[value] ?? "未知审核原因"}（${value}）`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "暂无";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "无效时间" : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "medium" }).format(date);
}

export const emptyStateText = { noData: "暂无数据", noTasks: "暂无任务", noAssets: "暂无素材" } as const;
