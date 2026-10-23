export interface SearchData {
  url: string;
  meta: { title?: string };
  excerpt: string;
}
export interface SearchIndex {
  search(query: string): Promise<{ results: { data(): Promise<SearchData> }[] }>;
  destroy(): Promise<void>;
}
interface SearchModule {
  createInstance(options: { basePath: string }): SearchIndex;
}

export async function withinDeadline<T>(operation: Promise<T>, milliseconds: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      operation,
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('Search request timed out')), milliseconds);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

/** Idle/intent warming and opening the dialog share the same bounded startup. */
export function createSearchBootstrap(
  importModule: (path: string) => Promise<SearchModule>,
  locale: 'zh' | 'en',
) {
  let ready: SearchIndex | null = null;
  let pending: Promise<SearchIndex> | null = null;
  let candidate: SearchIndex | null = null;
  let generation = 0;
  let attempt = 0;
  const disposed = new WeakSet<SearchIndex>();
  function dispose(index: SearchIndex | null) {
    if (!index || disposed.has(index)) return;
    disposed.add(index);
    // Cleanup must not extend a startup timeout while a network operation hangs.
    void index.destroy().catch(() => {});
  }
  function reset() {
    generation++;
    dispose(ready);
    dispose(candidate);
    ready = null;
    candidate = null;
    pending = null;
  }
  function load(): Promise<SearchIndex> {
    if (ready) return Promise.resolve(ready);
    if (pending) return pending;
    const current = generation;
    let abandoned = false;
    let active: SearchIndex | null = null;
    const ensureCurrent = () => {
      if (abandoned || current !== generation) throw new Error('Search initialization superseded');
    };
    const path = `/pagefind/pagefind.js${++attempt > 1 ? `?retry=${Date.now()}-${attempt}` : ''}`;
    pending = withinDeadline((async () => {
      const module = await importModule(path);
      ensureCurrent();
      active = module.createInstance({ basePath: '/pagefind/' });
      candidate = active;
      // init() alone does not await the language index, WASM, chunks or fragments.
      const probe = await active.search(locale === 'zh' ? '审批' : 'approval');
      ensureCurrent();
      if (!probe.results.length) throw new Error('Search index readiness check failed');
      await probe.results[0].data();
      ensureCurrent();
      return active;
    })(), 30_000).then((index) => {
      ensureCurrent();
      ready = index;
      return index;
    }).catch((error) => {
      abandoned = true;
      dispose(active);
      throw error;
    }).finally(() => {
      if (current === generation) {
        candidate = null;
        pending = null;
      }
    });
    return pending;
  }
  return { load, reset };
}
