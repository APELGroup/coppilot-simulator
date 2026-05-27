/**
 * Global simulation queue — at most one simulation runs at a time.
 *
 * Call `enqueue(execute)` from any handler. It returns the initial status
 * ("running" if the slot is free, "queued" if something is already running).
 * The queue drains automatically: when a job finishes, the next one starts.
 */

type Job = () => Promise<void>;

let _running = false;
const _queue: Job[] = [];

/**
 * Enqueue a simulation job.
 * - If nothing is running, the job starts immediately (after one microtask
 *   so callers can set up store state first).
 * - Otherwise the job is appended to the queue.
 *
 * @returns "running" | "queued" — the initial status the run should be given.
 */
export function enqueue(execute: Job): "running" | "queued" {
  if (!_running) {
    _running = true;
    Promise.resolve()
      .then(() => execute())
      .finally(() => {
        _running = false;
        _drain();
      });
    return "running";
  }
  _queue.push(execute);
  return "queued";
}

function _drain() {
  const next = _queue.shift();
  if (!next) return;
  _running = true;
  Promise.resolve()
    .then(() => next())
    .finally(() => {
      _running = false;
      _drain();
    });
}

export function isSimulationRunning(): boolean {
  return _running;
}

export function queueLength(): number {
  return _queue.length;
}
