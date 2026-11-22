// Date-based schedule board: places every phase and install batch on its real date.
// Dates come only from the run payload; nothing here derives business numbers.

type TaskKind = 'phase' | 'install';

type Task = {
  start: string;
  end: string;
  title: string;
  meta: string;
  detail: string;
  kind: TaskKind;
  key?: boolean;
};

const DOW = '日一二三四五六';
const pad = (n: number) => String(n).padStart(2, '0');

function parse(day: string): Date {
  const [y, m, d] = day.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function iso(date: Date): string {
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

function shift(day: string, days: number): string {
  const d = parse(day);
  d.setUTCDate(d.getUTCDate() + days);
  return iso(d);
}

function spanDays(a: string, b: string): number {
  return Math.round((+parse(b) - +parse(a)) / 86400000) + 1;
}

function fmt(day: string): string {
  return `${+day.slice(5, 7)}月${+day.slice(8, 10)}日`;
}

function weekday(day: string): string {
  return DOW[parse(day).getUTCDay()];
}

function monthKey(day: string): string {
  return day.slice(0, 7);
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls = '', text = ''): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text) node.textContent = text;
  return node;
}

/** Phases (real start/end) + install batches (real night) become dated tasks. */
function collect(sched: Record<string, any>): Task[] {
  const tasks: Task[] = [];

  for (const p of sched.phases || []) {
    if (!p?.start) continue;
    const end = p.end || p.start;
    const days = spanDays(p.start, end);
    tasks.push({
      start: p.start,
      end,
      title: p.name || '阶段',
      meta: ['阶段', p.owner].filter(Boolean).join(' · '),
      detail: days > 1 ? `${fmt(p.start)} → ${fmt(end)} · 共 ${days} 天` : fmt(p.start),
      kind: 'phase',
      key: p.start === sched.go_live || /上刊|下刊/.test(p.name || ''),
    });
  }

  for (const b of sched.batches || []) {
    if (!b?.date) continue;
    const media = b.media === 'metro' ? '地铁' : '公交';
    tasks.push({
      start: b.date,
      end: b.date,
      title: `安装 · ${b.crew || `${media}班组`}`,
      meta: [b.id, b.window, `${media} ${b.units ?? '—'} 单元`].filter(Boolean).join(' · '),
      detail: b.rain_backup ? `雨备 ${fmt(b.rain_backup)}` : '—',
      kind: 'install',
    });
  }

  tasks.sort((a, b) => a.start.localeCompare(b.start) || (a.kind === b.kind ? 0 : a.kind === 'phase' ? -1 : 1));
  return tasks;
}

/** Render the schedule into ScheduleCalendar.astro's shell. */
export function renderSchedule(root: HTMLElement | null, sched: Record<string, any> | null | undefined): void {
  if (!root) return;

  const monthEl = root.querySelector<HTMLElement>('[data-sched-month]');
  const daysEl = root.querySelector<HTMLElement>('[data-sched-days]');
  const listEl = root.querySelector<HTMLElement>('[data-sched-list]');
  const countEl = root.querySelector<HTMLElement>('[data-sched-count]');
  const prevEl = root.querySelector<HTMLButtonElement>('[data-sched-prev]');
  const nextEl = root.querySelector<HTMLButtonElement>('[data-sched-next]');
  if (!monthEl || !daysEl || !listEl || !countEl || !prevEl || !nextEl) return;

  const data = sched || {};
  const tasks = collect(data);
  if (!tasks.length) {
    daysEl.replaceChildren();
    listEl.replaceChildren(el('p', 'sched-board__empty', '本方案暂无排期节点。'));
    countEl.textContent = '—';
    return;
  }

  const live: string | null = data.go_live || null;
  const down: string | null = data.take_down || null;

  // Months covered by the schedule, in order (June → August for a July campaign).
  const allDates = tasks.flatMap((t) => [t.start, t.end]).concat([live, down].filter(Boolean) as string[]);
  const sorted = [...allDates].sort();
  const months: string[] = [];
  let cursor = `${monthKey(sorted[0])}-01`;
  const lastMonth = monthKey(sorted[sorted.length - 1]);
  while (monthKey(cursor) <= lastMonth) {
    months.push(monthKey(cursor));
    cursor = shift(cursor, 32).slice(0, 7) + '-01';
  }
  let current = live && months.includes(monthKey(live)) ? monthKey(live) : months[0];

  // --- agenda, grouped by month, one row per date ---
  const byDate = new Map<string, Task[]>();
  for (const task of tasks) {
    byDate.set(task.start, [...(byDate.get(task.start) || []), task]);
  }
  const dates = [...byDate.keys()].sort();
  const perMonth = new Map<string, number>();
  for (const date of dates) perMonth.set(monthKey(date), (perMonth.get(monthKey(date)) || 0) + 1);

  listEl.replaceChildren();
  let lastMonthShown = '';
  for (const date of dates) {
    const mk = monthKey(date);
    if (mk !== lastMonthShown) {
      lastMonthShown = mk;
      const head = el('div', 'sched-board__month');
      head.append(el('span', '', `${date.slice(0, 4)} 年 ${+date.slice(5, 7)} 月`), el('small', '', `${perMonth.get(mk)} 个日期`));
      listEl.append(head);
    }

    const items = byDate.get(date)!;
    const row = el('div', 'sched-board__row');
    row.dataset.row = date;

    const tile = el('div', 'sched-board__tile');
    if (items.some((t) => t.key)) tile.classList.add('is-key');
    tile.append(el('b', '', String(+date.slice(8, 10))), el('i', '', `${+date.slice(5, 7)}月 · 周${weekday(date)}`));
    row.append(tile);

    const cell = el('div', 'sched-board__tasks');
    for (const task of items) {
      const node = el('div', 'sched-board__task');
      node.dataset.kind = task.kind;
      const line = el('div', 'sched-board__taskline');
      line.append(el('b', '', task.title), el('span', 'chip chip--quiet', task.meta));
      node.append(line, el('small', '', task.detail));
      cell.append(node);
    }
    row.append(cell);
    listEl.append(row);
  }
  countEl.textContent = `${dates.length} 个日期 · ${tasks.length} 项任务`;

  // --- month grid: campaign window as a band, task start days dotted ---
  function paint(): void {
    const [y, m] = current.split('-').map(Number);
    monthEl.textContent = `${y} 年 ${m} 月`;
    prevEl.disabled = current === months[0];
    nextEl.disabled = current === months[months.length - 1];

    const first = `${current}-01`;
    const offset = (parse(first).getUTCDay() + 6) % 7; // Monday-first
    const length = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const cells = Math.ceil((offset + length) / 7) * 7;

    daysEl.replaceChildren();
    for (let i = 0; i < cells; i++) {
      const day = shift(first, i - offset);
      const inMonth = monthKey(day) === current;
      const starting = tasks.filter((t) => t.start === day);
      const isLive = !!(live && down && day >= live && day <= down);

      const cell = document.createElement(inMonth && starting.length ? 'button' : 'span') as HTMLElement;
      cell.className = 'sched-board__cell';
      if (!inMonth) cell.classList.add('is-out');
      if (isLive) cell.classList.add('is-live');
      if (isLive && day === live) cell.classList.add('is-live-start');
      if (isLive && day === down) cell.classList.add('is-live-end');
      if (inMonth && starting.length) cell.classList.add('is-has');

      const num = el('span', 'sched-board__num', String(+day.slice(8, 10)));
      cell.append(num);

      if (inMonth && starting.length) {
        const dots = el('span', 'sched-board__dots');
        if (starting.some((t) => t.kind === 'phase')) dots.append(el('i', 'sched-board__dot'));
        if (starting.some((t) => t.kind === 'install')) {
          const dot = el('i', 'sched-board__dot');
          dot.dataset.kind = 'install';
          dots.append(dot);
        }
        cell.append(dots);

        const btn = cell as HTMLButtonElement;
        btn.type = 'button';
        btn.dataset.day = day;
        btn.setAttribute('aria-label', `${fmt(day)} 周${weekday(day)}：${starting.map((t) => t.title).join('、')}`);
      }
      daysEl.append(cell);
    }
  }

  prevEl.onclick = () => {
    const i = months.indexOf(current);
    if (i > 0) {
      current = months[i - 1];
      paint();
    }
  };
  nextEl.onclick = () => {
    const i = months.indexOf(current);
    if (i >= 0 && i < months.length - 1) {
      current = months[i + 1];
      paint();
    }
  };

  // A dated day jumps the agenda to that date's row.
  daysEl.onclick = (event) => {
    const day = (event.target as HTMLElement).closest<HTMLElement>('[data-day]')?.dataset.day;
    if (!day) return;
    daysEl.querySelectorAll('.is-sel').forEach((n) => n.classList.remove('is-sel'));
    daysEl.querySelector(`[data-day="${day}"]`)?.classList.add('is-sel');
    const row = listEl.querySelector<HTMLElement>(`[data-row="${day}"]`);
    if (!row) return;
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    listEl.querySelectorAll('.is-focus').forEach((n) => n.classList.remove('is-focus'));
    row.classList.add('is-focus');
  };

  paint();
}
