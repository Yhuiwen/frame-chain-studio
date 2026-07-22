import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import NotFoundView from "@/views/NotFoundView.vue";

describe("NotFoundView", () => {
  it("explains the missing route and offers a safe way back", () => {
    const wrapper = mount(NotFoundView, {
      global: {
        stubs: {
          RouterLink: { template: "<a href='/'><slot /></a>" },
          ElButton: { template: "<button><slot /></button>" },
        },
      },
    });

    expect(wrapper.text()).toContain("404");
    expect(wrapper.text()).toContain("页面不存在");
    expect(wrapper.get("a").attributes("href")).toBe("/");
  });
});
