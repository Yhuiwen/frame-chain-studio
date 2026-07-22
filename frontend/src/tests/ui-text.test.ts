import { describe, expect, it } from "vitest";

import { productionBlockerLabel, reviewReasonLabel, statusLabel } from "@/constants/uiText";

describe("中文界面文案映射", () => {
  it("只转换显示文案并保留可审计的原始代码", () => {
    expect(statusLabel("RUNNING")).toBe("进行中");
    expect(statusLabel("UNEXPECTED_STATE")).toContain("UNEXPECTED_STATE");
    expect(productionBlockerLabel("HUMAN_VISUAL_REJECTED")).toBe("人工视觉审核未通过（HUMAN_VISUAL_REJECTED）");
    expect(reviewReasonLabel("CHARACTER_STYLE_DRIFT")).toBe("角色画风发生漂移（CHARACTER_STYLE_DRIFT）");
  });
});
