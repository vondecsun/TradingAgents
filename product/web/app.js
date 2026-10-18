// No external scripts, unsafe HTML rendering, or embedded credentials.
const root = document.querySelector("#app");
const API_BASE = String(window.HENGYAN_API_BASE || "").replace(/\/$/, "");
const state = {
  token: sessionStorage.getItem("hy_token") || "",
  view: "dashboard",
  me: null,
  market: [],
  paperMarket: [],
  account: null,
  jobs: [],
  history: { orders: [], fills: [], ledger: [] },
  selected: "",
  bars: [],
  report: null,
  register: false,
};
const names = {
  "600519.SH": "贵州茅台",
  "000001.SZ": "平安银行",
  "600036.SH": "招商银行",
};
const statusNames = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  cancelled: "已取消",
  failed: "失败",
  accepted: "待撮合",
  filled: "已成交",
  rejected: "已拒绝",
};
const navs = [
  ["dashboard", "◈", "工作台"],
  ["watchlist", "☆", "自选行情"],
  ["jobs", "▤", "研究任务"],
  ["paper", "⇄", "模拟交易"],
  ["data", "▦", "数据中心"],
  ["subscription", "◇", "订阅管理"],
  ["settings", "⚙", "连接与设置"],
];
const labels = Object.fromEntries(navs.map((x) => [x[0], x[2]]));
let timer;
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = v;
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
function button(text, action, cls = "") {
  return h(
    "button",
    {
      class: "btn " + cls,
      type: "button",
      onClick: async (e) => {
        const b = e.currentTarget;
        b.disabled = true;
        try {
          await action();
        } catch (err) {
          toast(err.message);
        } finally {
          if (b.isConnected) b.disabled = false;
        }
      },
    },
    text,
  );
}
function badge(text, type = "") {
  return h("span", { class: "badge " + type }, text);
}
function toast(text) {
  const el = document.querySelector("#toast");
  el.textContent = text;
  el.classList.add("visible");
  clearTimeout(timer);
  timer = setTimeout(() => el.classList.remove("visible"), 5000);
}
async function api(path, method = "GET", data) {
  const res = await fetch(API_BASE + "/api/v1" + path, {
    method,
    headers: {
      ...(state.token ? { Authorization: "Bearer " + state.token } : {}),
      ...(data ? { "Content-Type": "application/json" } : {}),
    },
    ...(data ? { body: JSON.stringify(data) } : {}),
  });
  const body = await res.json();
  if (!res.ok) {
    if (res.status === 401 && state.me) {
      sessionStorage.removeItem("hy_token");
      state.token = "";
      state.me = null;
      render();
    }
    throw new Error(
      body.error?.message || body.detail?.[0]?.msg || "请求失败，请重试",
    );
  }
  return body;
}
function cash(cents) {
  return (
    "¥ " +
    (Number(cents || 0) / 100).toLocaleString("zh-CN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  );
}
function number(x) {
  return Number(x || 0).toLocaleString("zh-CN");
}
function stamp(s) {
  return s ? new Date(s).toLocaleString("zh-CN", { hour12: false }) : "—";
}
function field(label, type, name, value = "", extra = {}) {
  return h(
    "label",
    { class: "field" },
    label,
    h("input", { type, name, value, required: true, ...extra }),
  );
}
function table(headers, rows) {
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      {},
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          headers.map((x) => h("th", {}, x)),
        ),
      ),
      h("tbody", {}, rows),
    ),
  );
}
function empty(title, description, action) {
  return h(
    "div",
    { class: "empty" },
    h("strong", {}, title),
    h("div", {}, description),
    action ? h("div", { class: "chips", style: undefined }, action) : null,
  );
}
function card(title, content, action) {
  return h(
    "section",
    { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, title), action),
    content,
  );
}
function download(name, text, type = "text/plain;charset=utf-8") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = h("a", { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function refresh() {
  const [me, market, account, jobs, history, paperMarket] = await Promise.all([
    api("/me"),
    api("/instruments"),
    api("/paper/account"),
    api("/analysis-jobs"),
    api("/paper/history"),
    api("/instruments?scope=paper"),
  ]);
  Object.assign(state, {
    me,
    market: market.items,
    paperMarket: paperMarket.items,
    account,
    jobs: jobs.items,
    history,
  });
  if (
    (!state.selected ||
      !state.market.some((x) => x.symbol === state.selected)) &&
    state.market.length
  )
    state.selected = state.market[0].symbol;
  if (state.selected)
    state.bars = (await api("/instruments/" + state.selected + "/bars")).items;
}
async function navigate(view) {
  state.view = view;
  state.report = null;
  try {
    await refresh();
    render();
  } catch (e) {
    toast(e.message);
  }
}
async function loadDemo() {
  await api("/data/demo", "POST");
  await refresh();
  render();
  toast("已载入合成演示数据，非真实行情");
}
async function job(symbol) {
  const engine = document.querySelector("#engine")?.value || "facts";
  await api("/analysis-jobs", "POST", {
    symbol,
    engine,
    idempotency_key: crypto.randomUUID(),
  });
  state.view = "jobs";
  await refresh();
  render();
  toast("任务已提交，服务端将继续运行");
}
function login() {
  const form = h(
    "form",
    {
      onSubmit: async (e) => {
        e.preventDefault();
        const b = e.currentTarget.querySelector("button[type=submit]");
        b.disabled = true;
        try {
          const f = new FormData(e.currentTarget);
          const res = await api(
            state.register ? "/auth/register" : "/auth/login",
            "POST",
            Object.fromEntries(f),
          );
          state.register = false;
          state.token = res.token;
          sessionStorage.setItem("hy_token", res.token);
          await refresh();
          render();
        } catch (err) {
          toast(err.message);
        } finally {
          b.disabled = false;
        }
      },
    },
    field("邮箱地址", "email", "email", "", {
      placeholder: "you@example.com",
      autocomplete: "username",
    }),
    field("密码 · 至少12个字符", "password", "password", "", {
      minlength: 12,
      maxlength: 200,
      autocomplete: state.register ? "new-password" : "current-password",
    }),
    h(
      "button",
      { class: "btn primary", type: "submit" },
      state.register ? "创建测试账户" : "进入工作台",
    ),
    button(
      state.register ? "已有账户？返回登录" : "首次使用？创建测试账户",
      () => {
        state.register = !state.register;
        render();
      },
    ),
  );
  return h(
    "div",
    { class: "login" },
    h(
      "section",
      { class: "login-intro" },
      brand(),
      h("h1", {}, "让每一次研究，", h("br"), "都有据可循。"),
      h(
        "p",
        {},
        "从可核查数据出发，连接研究、模拟与复盘。一个为中国 A 股设计的独立研究工作台。",
      ),
      h(
        "div",
        { class: "chips" },
        badge("开发测试版"),
        badge("模拟交易", "warn"),
      ),
    ),
    h(
      "section",
      { class: "login-form" },
      h(
        "div",
        { class: "inner" },
        h("div", { class: "eyebrow" }, "WELCOME TO HENGYAN"),
        h("h2", {}, state.register ? "建立研究工作区" : "欢迎回来"),
        h("p", { class: "sub" }, "独立账户 · 私有任务 · 可追溯报告"),
        form,
        h(
          "p",
          { class: "login-note" },
          "当前为开发测试系统，尚未开放商业销售、实时行情和真实券商交易。注册邮箱尚未验证，请勿使用证券账户密码。",
        ),
      ),
    ),
  );
}
function brand() {
  return h(
    "div",
    { class: "brand" },
    h("span", { class: "brandmark" }, "衡"),
    h("div", {}, "衡研", h("small", {}, "HENGYAN RESEARCH")),
  );
}
function shell(content) {
  return h(
    "div",
    { class: "shell" },
    h(
      "aside",
      { class: "sidebar" },
      brand(),
      h("div", { class: "navlabel" }, "RESEARCH WORKSPACE"),
      h(
        "nav",
        { class: "nav", "aria-label": "主导航" },
        navs.map(([id, icon, title]) =>
          h(
            "button",
            {
              class: state.view === id ? "active" : "",
              onClick: () => navigate(id),
            },
            h("i", {}, icon),
            title,
          ),
        ),
      ),
      h(
        "div",
        { class: "sidebar-bottom" },
        h("b", {}, "研究有边界，数据有出处"),
        h("p", {}, "当前仅提供数据核对与模拟操作。国金实盘尚未连接。"),
        badge("PILOT · v0.2", "muted"),
      ),
    ),
    h(
      "main",
      { class: "main" },
      h(
        "header",
        { class: "topbar" },
        h(
          "div",
          { class: "breadcrumb" },
          "研究空间 / ",
          labels[state.view] || "报告",
        ),
        h(
          "div",
          { class: "userbox" },
          badge("开发测试", "warn"),
          h("span", { class: "email" }, state.me.email),
          h("span", { class: "avatar" }, state.me.email[0].toUpperCase()),
          button(
            "退出",
            async () => {
              await api("/auth/logout", "POST");
              state.token = "";
              state.me = null;
              state.register = false;
              sessionStorage.removeItem("hy_token");
              render();
            },
            "small",
          ),
        ),
      ),
      content,
      h(
        "footer",
        {},
        h("span", {}, "衡研 HENGYAN · 数据核对与模拟研究工作台"),
        h("span", {}, "虚拟资金 · 无实时行情 · 非实盘交易"),
      ),
    ),
  );
}
function heading(title, subtitle, actions) {
  return h(
    "div",
    { class: "heading" },
    h(
      "div",
      {},
      h("div", { class: "eyebrow" }, "A-SHARE RESEARCH / 中国 A 股"),
      h("h1", {}, title),
      h("p", { class: "sub" }, subtitle),
    ),
    h("div", { class: "actions" }, actions),
  );
}
function banner() {
  const demo = (state.view === "paper" ? state.paperMarket : state.market).some(
    (x) => x.mode === "demo",
  );
  return h(
    "div",
    { class: "banner " + (demo ? "warn" : "") },
    h("span", {}, "ⓘ"),
    h(
      "span",
      {},
      demo
        ? "当前行情为合成演示数据，不代表真实价格。模拟时钟：" +
            state.account.as_of +
            "；推进日期才会尝试撮合委托。"
        : "在线日线自动保存并可直接研究；按行情表显示的数据日期为准，非实时行情。在线研究与历史模拟使用独立数据，下载不会覆盖模拟记录。",
    ),
  );
}
function stats() {
  const a = state.account,
    s = state.me.subscription;
  return h(
    "div",
    { class: "stats" },
    stat("模拟总资产", cash(a.equity), "虚拟资金，不可充值或提现", "◈"),
    stat(
      "可用模拟资金",
      cash(a.available_cash),
      "委托冻结 " + cash(a.reserved),
      "⇄",
    ),
    stat(
      "模拟累计盈亏",
      cash(a.pnl),
      "相对初始虚拟本金 " + cash(a.initial_cash),
      "↗",
    ),
    stat(
      "本月研究额度",
      s.remaining + " / " + s.quota,
      "已占用 " + s.used + " · " + s.period,
      "▤",
    ),
  );
}
function stat(label, value, foot, icon) {
  return h(
    "div",
    { class: "card" },
    h("div", { class: "stat-label" }, label, h("span", {}, icon)),
    h("div", { class: "stat-value" }, value),
    h("div", { class: "stat-foot" }, foot),
  );
}
function stockTable(items, compact = false) {
  if (!items.length)
    return empty(
      "工作区还没有行情",
      "输入股票代码即可一键获取日线，不需要下载或上传文件。",
      button("一键获取行情", () => navigate("data"), "primary small"),
    );
  return table(
    ["证券 / 代码", "收盘价", "数据日期", "来源", "操作"],
    items.map((x) =>
      h(
        "tr",
        {},
        h(
          "td",
          {},
          h("strong", {}, names[x.symbol] || x.symbol),
          h("div", { class: "symbol" }, x.symbol),
        ),
        h("td", { class: "mono" }, Number(x.close).toFixed(2)),
        h("td", {}, x.date),
        h(
          "td",
          {},
          badge(
            x.mode === "demo"
              ? "合成演示"
              : x.mode === "online"
                ? "在线日线"
                : "用户导入",
            x.mode === "demo" ? "warn" : "muted",
          ),
        ),
        h(
          "td",
          {},
          h(
            "div",
            { class: "actions" },
            button("研究", () => job(x.symbol), "small"),
            compact
              ? null
              : button(
                  x.watched ? "★" : "☆",
                  async () => {
                    await api(
                      "/watchlist/" + x.symbol,
                      x.watched ? "DELETE" : "POST",
                    );
                    await refresh();
                    render();
                  },
                  "small",
                ),
          ),
        ),
      ),
    ),
  );
}
function chart() {
  if (state.bars.length < 2)
    return h("div", { class: "chart-empty" }, "载入日线后显示价格图");
  const data = state.bars.map((b) => Number(b.close));
  const min = Math.min(...data) * 0.999,
    max = Math.max(...data) * 1.001;
  const coords = data.map((v, i) => [
    (i / (data.length - 1)) * 600,
    175 - ((v - min) / (max - min)) * 155,
  ]);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 600 200");
  svg.setAttribute("class", "chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "截至模拟时点的收盘价格走势");
  for (let i = 0; i < 4; i++) {
    const line = document.createElementNS(ns, "line");
    Object.entries({
      x1: 0,
      x2: 600,
      y1: 20 + i * 50,
      y2: 20 + i * 50,
      stroke: "#edf2ef",
      "stroke-dasharray": "4 4",
    }).forEach(([k, v]) => line.setAttribute(k, v));
    svg.append(line);
  }
  const area = document.createElementNS(ns, "path");
  area.setAttribute(
    "d",
    "M" + coords.map((c) => c.join(",")).join(" L") + " L600,200 L0,200 Z",
  );
  area.setAttribute("fill", "#e5f2ec");
  svg.append(area);
  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", coords.map((c) => c.join(",")).join(" "));
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "#268a74");
  line.setAttribute("stroke-width", "2.5");
  svg.append(line);
  return h(
    "div",
    {},
    svg,
    h(
      "div",
      { class: "chart-labels" },
      state.bars[0].date,
      state.bars.at(-1).date,
    ),
  );
}
function selectStock() {
  const select = h("select", {
    "aria-label": "选择证券",
    onChange: async (e) => {
      state.selected = e.target.value;
      state.bars = (
        await api("/instruments/" + state.selected + "/bars")
      ).items;
      render();
    },
  });
  for (const x of state.market) {
    const option = h(
      "option",
      { value: x.symbol },
      (names[x.symbol] || x.symbol) + " · " + x.symbol,
    );
    option.selected = x.symbol === state.selected;
    select.append(option);
  }
  return select;
}
function tasksList(items) {
  if (!items.length)
    return empty(
      "尚无研究任务",
      "从自选行情发起数据核对，报告会保存在你的账户中。",
    );
  return h(
    "div",
    {},
    items
      .slice(0, 5)
      .map((j) =>
        h(
          "div",
          { class: "row" },
          h(
            "div",
            { class: "row-left" },
            h("div", { class: "step" }, j.status === "completed" ? "✓" : "◌"),
            h("div", {}, h("strong", {}, j.symbol), h("p", {}, j.stage)),
          ),
          j.status === "completed"
            ? button("查看报告", () => openReport(j.id), "small")
            : badge(
                statusNames[j.status],
                j.status === "failed" ? "error" : "muted",
              ),
        ),
      ),
  );
}
function dashboard() {
  return [
    heading(
      "研究工作台",
      "先核对事实，再形成自己的判断。",
      button(
        "＋ 发起研究",
        () => {
          state.view = "watchlist";
          render();
        },
        "primary",
      ),
    ),
    banner(),
    stats(),
    h(
      "div",
      { class: "grid" },
      card(
        "市场观察 · 收盘走势",
        h("div", {}, h("div", { class: "field" }, selectStock()), chart()),
        badge("按模拟时点截断", "muted"),
      ),
      card(
        "工作区进度",
        h(
          "div",
          {},
          [
            [
              "01",
              "数据准备",
              state.market.length
                ? state.market.length + " 个证券，均明确标注来源"
                : "输入代码即可获取日线",
            ],
            [
              "02",
              "数据核对",
              state.jobs.filter((x) => x.status === "completed").length +
                " 份已完成报告",
            ],
            ["03", "模拟复盘", state.history.fills.length + " 笔模拟成交"],
            ["04", "券商连接", "国金证券 · 尚未配置"],
          ].map(([n, t, s]) =>
            h(
              "div",
              { class: "row" },
              h(
                "div",
                { class: "row-left" },
                h("div", { class: "step" }, n),
                h("div", {}, h("h3", {}, t), h("p", {}, s)),
              ),
            ),
          ),
        ),
      ),
    ),
    h(
      "div",
      { class: "grid" },
      card(
        "我的行情",
        stockTable(state.market.slice(0, 5), true),
        button("全部行情 →", () => navigate("watchlist"), "small"),
      ),
      card("最近研究", tasksList(state.jobs), badge("服务端任务", "muted")),
    ),
    card(
      "公告与信息来源",
      empty(
        "公告数据源尚未接入",
        "将在获得商业数据授权后开放；当前不展示生成或虚构的公告。",
      ),
    ),
  ];
}
function watchlist() {
  const input = h("input", {
    type: "search",
    placeholder: "搜索代码或证券名称",
    "aria-label": "搜索证券",
    onInput: (e) => {
      const q = e.target.value.toLowerCase();
      container.replaceChildren(
        stockTable(
          state.market.filter((x) =>
            (x.symbol + (names[x.symbol] || "")).toLowerCase().includes(q),
          ),
        ),
      );
    },
  });
  const engine = h(
    "select",
    { id: "engine", "aria-label": "研究引擎" },
    h("option", { value: "facts" }, "数据核对（非AI荐股）"),
    state.me.internal_research
      ? h("option", { value: "tradingagents" }, "TradingAgents · 内部研究")
      : null,
  );
  const container = h("div", {}, stockTable(state.market));
  return [
    heading(
      "自选行情",
      "价格与日期可核对，数据来源始终可见。",
      button("＋ 获取行情", () => navigate("data"), "primary"),
    ),
    banner(),
    card("收盘日线 · " + (state.selected || "待获取"), chart(), selectStock()),
    card(
      "证券列表",
      h("div", {}, h("div", { class: "toolbar" }, input, engine), container),
    ),
    h(
      "div",
      { class: "grid" },
      card(
        "已收藏",
        stockTable(
          state.market.filter((x) => x.watched),
          true,
        ),
      ),
      card(
        "使用说明",
        h(
          "p",
          { class: "sub" },
          "研究只读取当前模拟日期及以前的日线。数据核对报告使用确定性计算；多代理LLM引擎需服务端配置并仅限内部账户。点击星号管理自选。",
        ),
      ),
    ),
  ];
}
function jobs() {
  return [
    heading(
      "研究任务",
      "任务、报告和数据快照保存在服务器，关闭页面也能继续。",
      button("＋ 新建研究", () => navigate("watchlist"), "primary"),
    ),
    card(
      "全部任务",
      state.jobs.length
        ? table(
            ["证券", "引擎", "状态", "创建时间", "进度 / 说明", "操作"],
            state.jobs.map((j) =>
              h(
                "tr",
                {},
                h("td", {}, j.symbol),
                h("td", {}, j.engine === "facts" ? "数据核对" : "内部多代理"),
                h(
                  "td",
                  {},
                  badge(
                    statusNames[j.status],
                    j.status === "failed"
                      ? "error"
                      : j.status === "completed"
                        ? ""
                        : "muted",
                  ),
                ),
                h("td", {}, stamp(j.created)),
                h("td", {}, j.stage),
                h(
                  "td",
                  {},
                  j.status === "completed"
                    ? button("阅读报告", () => openReport(j.id), "small")
                    : ["queued", "running"].includes(j.status)
                      ? button(
                          "取消",
                          async () => {
                            await api(
                              "/analysis-jobs/" + j.id + "/cancel",
                              "POST",
                            );
                            await refresh();
                            render();
                          },
                          "small",
                        )
                      : h("span", { class: "muted" }, "额度已释放"),
                ),
              ),
            ),
          )
        : tasksList([]),
    ),
    card(
      "额度与恢复",
      h(
        "p",
        { class: "sub" },
        "提交任务时原子预留1次额度，成功后计入用量，失败或取消释放额度。中断的运行任务标记失败，避免自动重复调用收费模型。失败原因以状态显示，不暴露服务端密钥或日志。",
      ),
    ),
  ];
}
async function openReport(id) {
  state.report = await api("/reports/" + id);
  state.view = "report";
  render();
}
function report() {
  const r = state.report;
  return [
    heading(
      r.title,
      "报告截至 " +
        r.as_of +
        " · " +
        (r.engine === "facts" ? "确定性数据核对" : "内部多代理研究"),
      [
        button("返回任务", () => navigate("jobs")),
        button(
          "导出 JSON",
          () =>
            download(
              "hengyan-report-" + r.as_of + ".json",
              JSON.stringify(r, null, 2),
              "application/json",
            ),
          "primary",
        ),
      ],
    ),
    h(
      "div",
      { class: "report-head" },
      badge(
        r.mode === "demo"
          ? "合成演示数据"
          : r.mode === "online"
            ? "在线获取日线"
            : "用户导入数据",
        r.mode === "demo" ? "warn" : "muted",
      ),
      badge(r.internal_only ? "仅限内部研究" : "事实核对"),
      badge("非实盘委托", "muted"),
    ),
    h(
      "div",
      { class: "card report" },
      h("p", { class: "sub" }, "来源：" + r.source),
      r.sections.map((s) =>
        h("section", {}, h("h3", {}, s.title), h("p", {}, s.text)),
      ),
      h(
        "section",
        {},
        h("h3", {}, "日线核对证据（至多20条）"),
        table(
          ["证券", "日期", "收盘", "来源"],
          r.evidence.map((e) =>
            h(
              "tr",
              {},
              h("td", {}, e.symbol),
              h("td", {}, e.date),
              h("td", {}, e.close),
              h("td", {}, e.source),
            ),
          ),
        ),
      ),
    ),
  ];
}
function paperPage() {
  const a = state.account;
  const form = h("form", {
    onSubmit: async (e) => {
      e.preventDefault();
      const b = e.currentTarget.querySelector("button[type=submit]");
      b.disabled = true;
      try {
        const f = Object.fromEntries(new FormData(e.currentTarget));
        await api("/paper/orders", "POST", {
          ...f,
          quantity: Number(f.quantity),
          idempotency_key: crypto.randomUUID(),
        });
        await refresh();
        render();
        toast("模拟委托已受理，等待后续交易日开盘价撮合");
      } catch (err) {
        toast(err.message);
      } finally {
        b.disabled = false;
      }
    },
  });
  const symbolSelect = h(
    "select",
    { name: "symbol", required: true },
    state.paperMarket.map((x) =>
      h(
        "option",
        { value: x.symbol },
        (names[x.symbol] || "证券") + " " + x.symbol,
      ),
    ),
  );
  const sideSelect = h(
    "select",
    { name: "side" },
    h("option", { value: "buy" }, "模拟买入"),
    h("option", { value: "sell" }, "模拟卖出"),
  );
  form.append(
    h(
      "div",
      { class: "order-note" },
      "仅模拟。限价委托最早在后续数据日期按开盘价撮合；不会使用当前收盘价。停牌、单一价日线保守不成交。",
    ),
    h("label", { class: "field" }, "证券", symbolSelect),
    h(
      "div",
      { class: "form-grid" },
      h("label", { class: "field" }, "方向", sideSelect),
      field("股数", "number", "quantity", "100", { min: 1, step: 1 }),
    ),
    field("限价（元）", "number", "limit_price", "", {
      min: 0.0001,
      step: 0.0001,
      placeholder: "请输入限价",
    }),
    h(
      "button",
      {
        class: "btn primary",
        type: "submit",
        disabled: !state.paperMarket.length,
      },
      "提交模拟委托",
    ),
  );
  const holdings = a.positions.map((p) =>
    h(
      "tr",
      {},
      h("td", {}, p.symbol),
      h("td", {}, number(p.quantity)),
      h("td", {}, number(p.available)),
      h("td", {}, p.price || "未知"),
      h("td", {}, p.market_value == null ? "未知" : cash(p.market_value)),
    ),
  );
  const orders = state.history.orders.map((o) => {
    const action =
      o.status === "accepted"
        ? button(
            "撤单",
            async () => {
              await api("/paper/orders/" + o.id + "/cancel", "POST");
              await refresh();
              render();
            },
            "small",
          )
        : h("span", {}, "—");
    return h(
      "tr",
      {},
      h("td", {}, o.symbol),
      h("td", {}, (o.side === "buy" ? "买入" : "卖出") + " " + o.qty),
      h("td", {}, o.limit_price),
      h(
        "td",
        {},
        badge(statusNames[o.status], o.status === "filled" ? "" : "muted"),
      ),
      h("td", {}, o.reason || "—"),
      h("td", {}, action),
    );
  });
  const fills = state.history.fills.map((f) =>
    h(
      "tr",
      {},
      h("td", {}, f.symbol),
      h("td", {}, f.side === "buy" ? "买" : "卖"),
      h("td", {}, f.qty),
      h("td", {}, f.price),
      h("td", {}, cash(f.fee)),
      h("td", {}, f.date),
    ),
  );
  const ledger = state.history.ledger
    .slice(0, 20)
    .map((l) =>
      h(
        "tr",
        {},
        h(
          "td",
          {},
          { initial: "初始虚拟本金", buy: "买入", sell: "卖出" }[l.kind],
        ),
        h("td", {}, cash(l.amount)),
        h("td", {}, cash(l.balance)),
        h("td", {}, l.date),
      ),
    );
  const holdingsCard = card(
    "模拟持仓",
    holdings.length
      ? table(["证券", "总持仓", "可卖", "参考收盘", "市值"], holdings)
      : empty("尚无持仓", "先提交模拟委托，再推进到后续数据日期。"),
  );
  const orderCard = card(
    "委托记录",
    orders.length
      ? table(
          ["证券", "方向 / 股数", "限价", "状态", "未成交原因", "操作"],
          orders,
        )
      : empty("暂无委托", "所有记录均为本账户模拟操作。"),
  );
  const fillsCard = card(
    "成交记录",
    fills.length
      ? table(["证券", "方向", "数量", "价格", "费用", "日期"], fills)
      : empty("暂无成交", "成交记录随模拟时钟推进生成。"),
  );
  const ledgerCard = card(
    "资金流水",
    table(["类型", "变动", "余额", "日期"], ledger),
  );
  const advanceButton = button(
    "推进下一数据日 →",
    async () => {
      await api("/paper/advance", "POST");
      await refresh();
      render();
      toast("已推进模拟日期并处理委托");
    },
    "primary",
  );
  return [
    heading(
      "模拟交易",
      "虚拟本金 " + cash(a.initial_cash) + " · 当前模拟日期 " + a.as_of,
      advanceButton,
    ),
    banner(),
    stats(),
    h(
      "div",
      { class: "grid" },
      holdingsCard,
      card("限价模拟委托", form, badge("不发送真实订单", "warn")),
    ),
    orderCard,
    h("div", { class: "grid" }, fillsCard, ledgerCard),
    h(
      "div",
      { class: "banner warn" },
      a.fee_assumptions +
        "。不处理分红送转、拆合股、真实涨跌停排队、部分成交及完整交易日历，不用于证明实盘收益。",
    ),
  ];
}
function onlineHistoryForm() {
  const chinaNow = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Shanghai" }),
  );
  chinaNow.setDate(chinaNow.getDate() - 1);
  const iso = (d) =>
    [
      d.getFullYear(),
      String(d.getMonth() + 1).padStart(2, "0"),
      String(d.getDate()).padStart(2, "0"),
    ].join("-");
  const end = iso(chinaNow);
  const startDate = new Date(chinaNow);
  startDate.setFullYear(startDate.getFullYear() - 1);
  const symbolInput = h("input", {
    name: "symbol",
    type: "text",
    required: true,
    maxlength: 12,
    placeholder: "例如 000001 或 600519",
    value: state.selected || "000001",
    autocomplete: "off",
  });
  const status = h(
    "p",
    { class: "sub", role: "status", "aria-live": "polite" },
    "自动识别沪深代码，获取后加入自选并打开图表。无需注册数据账号或处理CSV。",
  );
  const submit = h(
    "button",
    { class: "btn primary", type: "submit" },
    "一键获取行情",
  );
  const form = h(
    "form",
    {
      id: "online-history-form",
      onSubmit: async (e) => {
        e.preventDefault();
        submit.disabled = true;
        submit.textContent = "正在连接行情源…";
        status.textContent =
          "正在获取历史日线，请稍候。网络异常会显示具体原因，不会生成替代行情。";
        try {
          const fields = Object.fromEntries(new FormData(e.currentTarget));
          const result = await api("/data/fetch", "POST", fields);
          state.selected = result.symbol;
          await refresh();
          state.view = "watchlist";
          render();
          toast(
            (result.cached ? "已读取缓存" : "已获取") +
              " " +
              result.downloaded +
              " 条日线，最新日期 " +
              result.last,
          );
        } catch (err) {
          status.textContent = err.message;
          status.className = "sub fetch-error";
          toast(err.message);
        } finally {
          submit.disabled = false;
          submit.textContent = "一键获取行情";
        }
      },
    },
    h("label", { class: "field" }, "股票代码", symbolInput),
    h(
      "div",
      { class: "chips" },
      [
        ["000001", "平安银行"],
        ["600519", "贵州茅台"],
        ["600036", "招商银行"],
      ].map(([code, name]) =>
        button(
          name + " · " + code,
          () => {
            symbolInput.value = code;
            symbolInput.focus();
          },
          "small",
        ),
      ),
    ),
    h(
      "div",
      { class: "form-grid" },
      field("开始日期", "date", "start", iso(startDate), { max: end }),
      field("结束日期", "date", "end", end, { max: end }),
    ),
    submit,
    status,
  );
  return card("一键获取历史行情", form, badge("自动保存 · 无需上传"));
}
async function preparePaper(symbol) {
  const nonempty = state.paperMarket.length || state.history.orders.length;
  if (nonempty) {
    const value = prompt(
      "开始新的历史模拟将清空当前模拟订单、持仓与流水，保留在线行情和研究报告。输入 RESET SIMULATION 确认；取消则不更改：",
    );
    if (value !== "RESET SIMULATION") return;
    await api("/paper/reset", "POST", { confirmation: value });
  }
  await api("/data/use-for-paper", "POST", { symbol });
  await navigate("paper");
  toast("已用下载行情建立历史模拟；模拟时钟从最早数据日开始");
}
function onlineHistoryCard() {
  const online = state.market.filter((x) => x.mode === "online");
  if (!online.length)
    return card(
      "在线行情工作区",
      empty(
        "输入代码，一键开始",
        "获取完成后，日线会自动保存、加入自选并用于研究，不影响模拟账户。",
      ),
    );
  return card(
    "已获取的在线行情",
    h(
      "div",
      {},
      online.map((x) =>
        h(
          "div",
          { class: "row" },
          h(
            "div",
            {},
            h("strong", {}, (names[x.symbol] || x.symbol) + " · " + x.symbol),
            h("p", { class: "sub" }, "最新日线 " + x.date + " · " + x.source),
          ),
          button("用于历史模拟", () => preparePaper(x.symbol), "small"),
        ),
      ),
    ),
  );
}
function dataPage() {
  const source = field("数据出处（必填，用于报告溯源）", "text", "source", "", {
    placeholder: "例如：本人有权使用的数据供应商导出",
    maxlength: 150,
  });
  const file = h("input", {
    type: "file",
    accept: ".csv,text/csv",
    required: true,
    name: "file",
  });
  const form = h(
    "form",
    {
      onSubmit: async (e) => {
        e.preventDefault();
        const b = e.currentTarget.querySelector("button[type=submit]");
        b.disabled = true;
        try {
          const f = new FormData(e.currentTarget);
          const selected = f.get("file");
          if (selected.size > 1500000) throw Error("CSV最大1.5MB");
          const result = await api("/data/import", "POST", {
            source: f.get("source"),
            csv: await selected.text(),
          });
          await refresh();
          render();
          toast(
            "已导入 " + result.imported + " 行；来源标记为用户导入、未经验证",
          );
        } catch (err) {
          toast(err.message);
        } finally {
          b.disabled = false;
        }
      },
    },
    source,
    h("label", { class: "field" }, "日线 CSV 文件", file),
    h("button", { class: "btn primary", type: "submit" }, "验证并导入"),
  );
  return [
    heading(
      "数据中心",
      "输入代码 → 一键获取 → 自动保存、显示图表并开始研究。",
      button("查看自选行情 →", () => navigate("watchlist"), "small"),
    ),
    h("div", { class: "grid" }, onlineHistoryForm(), onlineHistoryCard()),
    h(
      "details",
      { class: "card secondary-import" },
      h("summary", {}, "备用方式：导入CSV或体验合成数据"),
      h(
        "div",
        { class: "grid" },
        card(
          "导入日线",
          form,
          button(
            "下载 CSV 模板",
            () =>
              download(
                "daily-bars-template.csv",
                "symbol,date,open,high,low,close,volume,tradable\n000001.SZ,2025-01-02,10,10.2,9.9,10.1,100000,1\n000001.SZ,2025-01-03,10.1,10.3,10,10.2,120000,1\n",
              ),
            "small",
          ),
        ),
        card(
          "快速体验",
          h(
            "div",
            {},
            h(
              "p",
              { class: "sub" },
              "生成35条工作日日线 × 3个示例代码，仅用于验证页面、任务和模拟账本；不代表交易所历史行情。",
            ),
            h(
              "div",
              { class: "chips" },
              button("载入合成演示数据", loadDemo, "primary"),
            ),
            h(
              "p",
              { class: "sub" },
              "演示数据和导入数据不可混用。同一证券、日期的数据导入后不能覆盖，避免改变历史分析依据。",
            ),
          ),
        ),
      ),
    ),
    card(
      "历史行情与模拟说明",
      h(
        "div",
        {},
        h(
          "p",
          { class: "sub" },
          "CSV列：symbol,date,open,high,low,close,volume,tradable。价格为未复权元价；tradable 为0或1。日期不晚于今天，周末拒绝；节假日及公司行动需由数据源保证。本版支持有限沪深主板证券，其他品种拒绝。",
        ),
        h(
          "p",
          { class: "sub" },
          "在线图表和研究使用已获取日线；历史模拟独立保存快照、从最早日期开始，并只显示模拟时点以前的数据。下载行情不会推进模拟时钟。",
        ),
      ),
      badge("非实时数据", "warn"),
    ),
    card(
      "重置模拟工作区",
      h(
        "div",
        {},
        h(
          "p",
          { class: "sub" },
          "清除本账户模拟订单、持仓、流水、自选和日线，恢复100万元虚拟本金。已有报告与用量保留。仅用于测试工作区。",
        ),
        h(
          "div",
          { class: "chips" },
          button(
            "重置模拟数据",
            async () => {
              const value = prompt(
                "这会清空本账户模拟工作区。输入 RESET SIMULATION 确认：",
              );
              if (value !== "RESET SIMULATION") return;
              await api("/paper/reset", "POST", { confirmation: value });
              state.selected = "";
              state.bars = [];
              await refresh();
              render();
              toast("已重置模拟工作区");
            },
            "danger",
          ),
        ),
      ),
    ),
  ];
}
function subscriptions() {
  const s = state.me.subscription;
  return [
    heading("订阅管理", "套餐与权益为开发测试配置，尚未开放对外销售。"),
    h(
      "div",
      { class: "banner warn" },
      "此页面不收款。订阅权益不包含证券投资咨询资格、行情再分发许可或实盘交易权限。",
    ),
    card(
      "当前用量",
      h(
        "div",
        {},
        h(
          "div",
          { class: "row" },
          h(
            "strong",
            {},
            { free: "体验版", research: "研究版", pro: "专业版" }[s.plan],
          ),
          badge(
            s.mode === "test"
              ? "测试激活 · 未扣款"
              : s.mode === "paid"
                ? "已付费"
                : "免费",
          ),
        ),
        h(
          "div",
          { class: "progress" },
          h("div", {
            style: undefined,
            "data-progress": Math.min(100, (s.used / s.quota) * 100),
          }),
        ),
        h(
          "p",
          { class: "sub" },
          s.period +
            " · 已占用 " +
            s.used +
            " / " +
            s.quota +
            " 次；到期 " +
            (s.expires
              ? new Date(s.expires * 1000).toLocaleDateString("zh-CN")
              : "—"),
        ),
      ),
    ),
    h(
      "div",
      { class: "plan-grid" },
      [
        ["free", "体验版", "0", 5],
        ["research", "研究版", "99", 100],
        ["pro", "专业版", "199", 500],
      ].map(([key, title, p, quota]) =>
        h(
          "section",
          { class: "card plan " + (key === "research" ? "featured" : "") },
          badge(
            key === s.plan ? "当前套餐" : "测试价格",
            key === s.plan ? "" : "muted",
          ),
          h("h2", {}, title),
          h("div", { class: "plan-price" }, "¥ " + p),
          h("p", { class: "sub" }, "每30天 · 价格仅用于开发测试"),
          h(
            "ul",
            {},
            h("li", {}, quota + " 次月度数据核对额度"),
            h("li", {}, "私有模拟账户与研究报告"),
            h("li", {}, "用量、任务和数据留痕"),
          ),
          key === "free"
            ? h("p", { class: "sub" }, "注册账户自动获得")
            : state.me.test_billing
              ? button(
                  "测试激活（不扣款）",
                  async () => {
                    await api("/subscription/test-activate", "POST", {
                      plan: key,
                    });
                    await refresh();
                    render();
                    toast("测试套餐已激活，没有扣款");
                  },
                  "primary",
                )
              : button(
                  "真实购买尚未开放",
                  async () => {
                    await api("/billing/orders", "POST", { plan: key });
                  },
                  "small",
                ),
        ),
      ),
    ),
    card(
      "发布前依赖",
      h(
        "p",
        { class: "sub" },
        "正式收款需接入商户订单创建、验签、退款与对账，并完成业务、数据授权和法律审查。当前只提供内部回调适配合同及测试，不能作为已接通微信或支付宝的证据。",
      ),
    ),
  ];
}
function settings() {
  return [
    heading("连接与设置", "将可用能力与尚未配置的服务明确分开。"),
    h(
      "div",
      { class: "grid" },
      card(
        "国金证券连接",
        h(
          "div",
          {},
          h("div", { class: "setup-icon" }, "⇄"),
          badge("未配置", "warn"),
          h(
            "p",
            { class: "sub" },
            "已预留券商适配边界。账户QMT/PTrade权限、SDK版本及第三方商业许可尚未确认；当前没有真实下单接口。",
          ),
          h(
            "div",
            { class: "chips" },
            h(
              "a",
              {
                href: "https://edu.gjzq.com.cn/main/company-overview/business-sysinfo.html",
                target: "_blank",
                rel: "noopener noreferrer",
              },
              "查看国金官方系统公示 ↗",
            ),
          ),
        ),
      ),
      card(
        "分析引擎",
        h(
          "div",
          {},
          h(
            "div",
            { class: "row" },
            h("span", {}, "确定性数据核对"),
            badge("可用"),
          ),
          h(
            "div",
            { class: "row" },
            h("span", {}, "TradingAgents内部研究"),
            badge(
              state.me.internal_research ? "已允许内部调用" : "未开放",
              state.me.internal_research ? "" : "muted",
            ),
          ),
          h(
            "p",
            { class: "sub" },
            "模型密钥仅在服务器环境中配置。内部研究连接上游原引擎，实际依赖与供应商可用性须单独验证。",
          ),
        ),
      ),
    ),
    h(
      "div",
      { class: "grid" },
      card(
        "数据与支付",
        h(
          "div",
          {},
          h(
            "div",
            { class: "row" },
            h("span", {}, "商业行情 / 公告"),
            badge("未连接", "muted"),
          ),
          h(
            "div",
            { class: "row" },
            h("span", {}, "真实支付商户"),
            badge("未连接", "muted"),
          ),
          h(
            "div",
            { class: "row" },
            h("span", {}, "测试套餐激活"),
            badge(state.me.test_billing ? "开发环境开启" : "关闭", "muted"),
          ),
        ),
      ),
      card(
        "运行与账户",
        h(
          "div",
          {},
          h(
            "p",
            { class: "sub" },
            "当前版本 v0.2.0 · 单主机试运行架构。会话有效期8小时，退出后服务端撤销当前会话。邮箱验证、密码找回、多端会话管理和运维后台尚未实现。",
          ),
          h(
            "div",
            { class: "chips" },
            button(
              "查看我的操作记录",
              async () => {
                const logs = await api("/audit");
                download(
                  "hengyan-audit.json",
                  JSON.stringify(logs, null, 2),
                  "application/json",
                );
              },
              "small",
            ),
          ),
        ),
      ),
    ),
  ];
}
function render() {
  if (!state.token || !state.me) {
    root.replaceChildren(login());
    return;
  }
  const pages = {
    dashboard,
    watchlist,
    jobs,
    paper: paperPage,
    data: dataPage,
    subscription: subscriptions,
    settings,
    report,
  };
  root.replaceChildren(shell(h("div", {}, pages[state.view]())));
  document.querySelectorAll("[data-progress]").forEach((el) => {
    el.style.width = el.dataset.progress + "%";
  });
}
if (state.token) {
  root.replaceChildren(h("div", { class: "loading" }, "正在加载研究空间…"));
  refresh()
    .then(render)
    .catch((err) => {
      state.token = "";
      state.me = null;
      sessionStorage.removeItem("hy_token");
      render();
      toast(err.message);
    });
} else render();
setInterval(async () => {
  if (!state.me || !["dashboard", "jobs"].includes(state.view)) return;
  try {
    const jobs = await api("/analysis-jobs");
    if (JSON.stringify(jobs.items) !== JSON.stringify(state.jobs)) {
      await refresh();
      render();
    }
  } catch {}
}, 3000);
