/* DOM integration test against a running local pilot server (not a real browser).
 * npm install --prefix /tmp/hengyan-dom-test jsdom@27.0.1
 * NODE_PATH=/tmp/hengyan-dom-test/node_modules node product/tests/frontend-smoke.cjs
 * Use a disposable database with PRODUCT_TEST_BILLING=true.
 */
const { JSDOM } = require("jsdom");
const fs = require("node:fs");
process.chdir(require("node:path").resolve(__dirname, "../.."));
const assert = require("node:assert/strict");
const base = process.env.PRODUCT_TEST_URL || "http://127.0.0.1:8765";
const dom = new JSDOM(fs.readFileSync("product/web/index.html", "utf8"), {
  url: base,
  runScripts: "outside-only",
  pretendToBeVisual: true,
});
const w = dom.window;
w.fetch = (url, opts) => fetch(new URL(url, base), opts);
w.prompt = () => null;
const code = fs.readFileSync("product/web/app.js", "utf8");
w.eval(code);
const text = () => w.document.body.textContent;
async function wait(predicate, label) {
  for (let i = 0; i < 150; i++) {
    if (predicate()) return;
    await new Promise((r) => setTimeout(r, 30));
  }
  throw Error("Timeout: " + label + "\n" + text().slice(-2000));
}
function click(label) {
  const el = [...w.document.querySelectorAll("button")].find(
    (x) =>
      x.textContent.trim() === label ||
      (x.closest("nav") && x.textContent.trim().endsWith(label)),
  );
  assert(el, "Button missing: " + label);
  assert(!el.disabled, "Button disabled: " + label);
  el.click();
}
async function main() {
  click("首次使用？创建测试账户");
  w.document.querySelector("[name=email]").value =
    "dom-" + Date.now() + "@example.com";
  w.document.querySelector("[name=password]").value = "dom-test-password-2026";
  w.document
    .querySelector("form")
    .dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true }));
  await wait(() => text().includes("模拟总资产"), "registration and dashboard");
  click("载入演示数据");
  await wait(() => text().includes("合成演示"), "demo workspace");
  click("自选行情");
  await wait(() => text().includes("证券列表"), "market navigation");
  const search = w.document.querySelector("input[type=search]");
  search.value = "000001";
  search.dispatchEvent(new w.Event("input", { bubbles: true }));
  assert(text().includes("平安银行"));
  click("研究");
  await wait(() => text().includes("全部任务"), "job create");
  await wait(() => text().includes("阅读报告"), "worker completed");
  click("阅读报告");
  await wait(() => text().includes("日线核对证据"), "report view");
  assert(text().includes("合成演示数据"));
  click("模拟交易");
  await wait(() => text().includes("限价模拟委托"), "paper navigation");
  w.document.querySelector("[name=symbol]").value = "000001.SZ";
  w.document.querySelector("[name=limit_price]").value = "11";
  w.document
    .querySelector("form")
    .dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true }));
  await wait(() => text().includes("待撮合"), "paper order");
  click("推进下一数据日 →");
  await wait(() => text().includes("已成交"), "paper fill");
  assert(text().includes("成交记录"));
  click("订阅管理");
  await wait(() => text().includes("测试激活（不扣款）"), "subscription");
  click("测试激活（不扣款）");
  await wait(() => text().includes("测试激活 · 未扣款"), "test entitlement");
  click("连接与设置");
  await wait(() => text().includes("国金证券连接"), "broker unavailable");
  assert(text().includes("没有真实下单接口"));
  click("数据中心");
  await wait(() => text().includes("验证并导入"), "data import page");
  assert(!w.document.querySelector('script[src*="http"]'));
  click("退出");
  await wait(() => text().includes("欢迎回来"), "logout");
  console.log(
    "PASS: registration, demo, search, durable analysis, report, order/fill, test subscription, settings, data and logout DOM flows",
  );
}
main()
  .then(() => {
    w.close();
  })
  .catch((e) => {
    console.error(e);
    w.close();
    process.exitCode = 1;
  });
