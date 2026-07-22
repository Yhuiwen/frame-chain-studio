<template>
  <main class="page not-found-page">
    <section class="panel not-found-card">
      <span class="error-code">404</span>
      <h1>页面不存在</h1>
      <p>当前地址无对应页面，可能已被移动或删除。</p>
      <RouterLink to="/">
        <el-button type="primary">返回项目列表</el-button>
      </RouterLink>
    </section>
  </main>
</template>

<style scoped>
.not-found-page { display: grid; place-items: center; }
.not-found-card { width: min(100%, 520px); padding: 48px 28px; text-align: center; }
.error-code { color: var(--primary); font-size: 14px; font-weight: 750; letter-spacing: .12em; }
.not-found-card p { margin-bottom: 22px; }
</style>
