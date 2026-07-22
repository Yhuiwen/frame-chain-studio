import { describe, expect, it } from "vitest";
import { router } from "@/router";

const projectPages = [
  ["/projects/4", "project-workbench", "项目工作台"],
  ["/projects/4/library", "project-library", "连续性资料库"],
  ["/projects/4/scripts", "project-scripts", "脚本与分镜"],
  ["/projects/4/shot/4/spec", "project-shot-spec", "镜头规范"],
  ["/projects/4/visual-review", "project-visual-review", "视觉连续性审核"],
  ["/projects/4/usage", "project-usage", "用量与预算"],
  ["/projects/4/settings/providers", "project-provider-settings", "服务商设置"],
] as const;

describe("project workspace nested routes", () => {
  it.each(projectPages)("resolves %s under exactly one shared layout", (path, name, title) => {
    const resolved = router.resolve(path);
    expect(resolved.name).toBe(name);
    expect(resolved.params.projectId).toBe("4");
    expect(resolved.meta.workspaceTitle).toBe(title);
    expect(resolved.matched).toHaveLength(2);
    expect(resolved.matched[0].path).toBe("/projects/:projectId");
  });

  it("keeps global provider settings outside the project layout", () => {
    const resolved = router.resolve("/settings/providers");
    expect(resolved.name).toBe("provider-settings");
    expect(resolved.matched).toHaveLength(1);
  });
});
