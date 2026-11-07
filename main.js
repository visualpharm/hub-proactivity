// «Proactivity»: вкладка в «Настройках» — что плагину разрешено делать с ответами людям и как часто писать сводку.
// Само слово владельца — пост {"kind":"settings", …} в канал плагина; действующие настройки процесс отдаёт постом
// {"kind":"config"} (то, что он принял, а не то, что вы нажали).
const PRESETS = [
  ["draft", "Черновик под сообщением, отправляю я"],
  ["colleagues", "Рутину коллегам отправляет плагин, остальным — черновик"],
  ["everyone", "Рутину отправляет плагин всем, кроме групп и каналов"],
  ["escalate", "Только сообщать в чат, без черновиков"],
];
const DIGEST = [[1, "каждый час"], [3, "раз в 3 часа"], [6, "раз в 6 часов"], [24, "раз в сутки"], [0, "без сводки"]];

let hub = null;
let settingsRoot = null;
let cfg = null;      // последний {"kind":"config"} от процесса плагина
let since = 0, loading = false, error = "", dirty = true;

async function sync() {
  if (loading) return false;
  loading = true;
  let changed = false;
  try {
    for (const p of await hub.feed(since)) {
      since = Math.max(since, Number(p.id.slice(1)));
      let d = null;
      try { d = JSON.parse(p.text); } catch { continue; }
      if (p.by === "плагин proactivity" && d?.kind === "config") { cfg = d; changed = true; dirty = true; }
    }
  } finally { loading = false; }
  return changed;
}

async function save(patch) {
  const body = { kind: "settings", preset: cfg?.preset || "draft", digest_h: cfg?.digest_h ?? 3, ...patch };
  try {
    const r = await hub.postFeed(JSON.stringify(body));
    error = r.error ? String(r.error) : "";
    if (!error) cfg = { ...(cfg || {}), ...patch };   // only accepted posts await collector config
  } catch { error = "Could not save. Try again."; }
  dirty = true;
  // hub.redraw refreshes navigation; this retained settings body owns its feedback.
  if (settingsRoot?.isConnected) { paint(settingsRoot); dirty = false; }
  hub.redraw();
}

function paint(root) {
  const el = hub.el;
  const preset = cfg?.preset || "draft";
  const box = el("div", "pa-box");
  for (const [id, label] of PRESETS) {
    const row = el("label", "pa-row");
    const input = el("input");
    input.type = "radio"; input.name = "pa-preset"; input.checked = id === preset;
    input.addEventListener("change", () => save({ preset: id }));
    row.append(input, el("span", null, label));
    box.append(row);
  }
  if ((preset === "colleagues" || preset === "everyone") && cfg && !cfg.level_send) {
    box.append(el("p", "pa-note", "Inbox пока не разрешил плагину отправку: ответы остаются черновиками."));
  }
  const digest = el("label", "pa-row");
  const select = el("select");
  for (const [h, label] of DIGEST) {
    const o = el("option", null, label);
    o.value = String(h); o.selected = h === (cfg?.digest_h ?? 3);
    select.append(o);
  }
  select.addEventListener("change", () => save({ digest_h: Number(select.value) }));
  digest.append(el("span", null, "Сводка в чат"), select);
  box.append(digest);
  if (error) box.append(el("p", "pa-note", error));
  root.replaceChildren(box);
}

export default function register(h) {
  hub = h;
  hub.addStyle("proactivity.css");
  hub.addSettings({
    id: "proactivity",
    title: "Proactivity",
    async render(root, snap) {
      settingsRoot = root;
      if ((snap?.feeds?.proactivity || 0) > since) await sync();
      if (dirty || !root.firstChild) { dirty = false; paint(root); }
    },
  });
}
